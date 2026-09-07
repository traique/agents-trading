"""Scheduler chạy thật cho Scheduled Jobs (trước đây chỉ là preview).

Vòng đời:
  - ``start_scheduler()`` được gọi trong lifespan của FastAPI, spawn một
    asyncio task duy nhất.
  - Mỗi 60 giây task quét các Job ``active`` (trong window start→end), xác
    định job nào đến hạn bằng ``next_due_at`` và chạy phân tích tương ứng
    qua ``ResearchAgentRunner`` — đúng runner mà chat handoff dùng, nên
    provider chain, depth, ngôn ngữ… đều nhất quán.
  - Kết quả lưu vào bảng ``reports`` với ``job_id`` — trang Report History
    và metrics của Jobs page đã hiển thị theo job_id nên không cần schema
    mới. Lỗi chạy được ghi vào ``config["last_error"]`` của job.
  - ``_running_jobs`` chặn double-run khi một job kẹt quá lâu; ``run_job_now``
    tái dùng cùng đường ống cho nút "Run now" trên UI.

Job được đánh dấu đến hạn dựa trên cột ``config.next_run_at`` (ISO string,
UTC) do scheduler tự cập nhật sau mỗi lần chạy — tránh parse lại cột
``frequency`` văn bản của UI tại nhiều nơi.
"""
from __future__ import annotations

import asyncio
import contextlib
import datetime
import json
import logging
import os
from typing import Any, Dict, Optional, Set

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.routers.v1.jobs.models.relational import Job
from app.routers.v1.users.repositories.setting import SettingRepository

logger = logging.getLogger(__name__)

SCAN_INTERVAL_SECONDS = 60

# Chuỗi frequency của UI → khoảng cách giữa hai lần chạy.
_FREQUENCY_DELTAS = {
    "every hour": datetime.timedelta(hours=1),
    "hourly": datetime.timedelta(hours=1),
    "every 4 hours": datetime.timedelta(hours=4),
    "daily": datetime.timedelta(days=1),
    "weekly": datetime.timedelta(weeks=1),
}


def frequency_delta(frequency: str) -> datetime.timedelta:
    """Parse chuỗi frequency tự do của UI thành timedelta (mặc định daily)."""
    freq = (frequency or "").lower().strip()
    for key, delta in _FREQUENCY_DELTAS.items():
        if key in freq:
            return delta
    return datetime.timedelta(days=1)


def next_due_after(job: Job, from_dt: datetime.datetime) -> datetime.datetime:
    """Lần chạy kế tiếp của job tính từ ``from_dt`` (timezone-aware UTC)."""
    start = job.start_date
    if start.tzinfo is None:
        start = start.replace(tzinfo=datetime.timezone.utc)
    delta = frequency_delta(job.frequency)
    if from_dt <= start:
        return start
    elapsed = (from_dt - start).total_seconds()
    steps = int(elapsed // delta.total_seconds()) + 1
    return start + delta * steps


def _due_at(job: Job) -> Optional[datetime.datetime]:
    """Thời điểm job đến hạn: config.next_run_at nếu có, else start_date."""
    cfg = job.config if isinstance(job.config, dict) else {}
    raw = cfg.get("next_run_at")
    if raw:
        try:
            dt = datetime.datetime.fromisoformat(str(raw))
            return dt if dt.tzinfo else dt.replace(tzinfo=datetime.timezone.utc)
        except ValueError:
            pass
    start = job.start_date
    return start if start.tzinfo else start.replace(tzinfo=datetime.timezone.utc)


def _is_due(job: Job, now: datetime.datetime) -> bool:
    if job.status != "active":
        return False
    if job.end_date is not None:
        end = job.end_date if job.end_date.tzinfo else job.end_date.replace(tzinfo=datetime.timezone.utc)
        if now > end:
            return False
    due = _due_at(job)
    return now >= due


class JobScheduler:
    """Background loop chạy các scheduled job đến hạn."""

    def __init__(self) -> None:
        self._task: Optional[asyncio.Task] = None
        self._running_jobs: Set[int] = set()
        # Event loop chỉ giữ weak reference cho task — caller phải giữ strong
        # reference để pipeline hàng phút không bị GC giữa chừng (py docs).
        self._tasks: Set[asyncio.Task] = set()

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop(), name="job-scheduler")
            logger.info("Job scheduler started (scan every %ss)", SCAN_INTERVAL_SECONDS)

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _loop(self) -> None:
        while True:
            try:
                await self.scan_and_run()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.error("Scheduler scan failed", exc_info=True)
            await asyncio.sleep(SCAN_INTERVAL_SECONDS)

    async def scan_and_run(self) -> int:
        """Chạy mọi job đến hạn; trả về số job đã kích hoạt."""
        now = datetime.datetime.now(datetime.timezone.utc)
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(Job).where(Job.status == "active"))
            jobs = result.scalars().all()

        count = 0
        for job in jobs:
            if not _is_due(job, now) or job.id in self._running_jobs:
                continue
            self._running_jobs.add(job.id)
            count += 1
            # Fire-and-forget: pipeline có thể chạy hàng phút, scan tiếp tục.
            self._spawn(self._run_job_safe(job.id))
        return count

    def _spawn(self, coro) -> None:
        """create_task kèm giữ strong reference + tự dọn khi xong."""
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _run_job_safe(self, job_id: int) -> None:
        try:
            await run_job(job_id)
        except Exception:
            logger.error("Job %s failed", job_id, exc_info=True)
            await self._record_failure(job_id)
        finally:
            self._running_jobs.discard(job_id)

    async def _record_failure(self, job_id: int) -> None:
        with contextlib.suppress(Exception):
            async with AsyncSessionLocal() as session:
                job = await session.get(Job, job_id)
                if job:
                    cfg = dict(job.config or {})
                    cfg["last_error"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
                    await session.execute(
                        Job.__table__.update().where(Job.id == job_id).values(config=cfg)
                    )
                    await session.commit()


scheduler = JobScheduler()


def start_scheduler() -> None:
    scheduler.start()


async def stop_scheduler() -> None:
    await scheduler.stop()


async def _build_job_config(job: Job, user_id: int) -> Optional[Dict[str, Any]]:
    """Dựng config cho ResearchAgentRunner từ job + user settings.

    Trả về None khi user không có API key khả dụng — job không thể chạy mà
    không biết lỗi gì, nên ghi lý do vào config và bỏ qua lần này.
    """
    from app.routers.v1.config.service import map_provider_for_client

    async with AsyncSessionLocal() as session:
        setting_repo = SettingRepository(session)
        user_settings = await setting_repo.get_by_user_id(user_id)
    job_cfg = job.config if isinstance(job.config, dict) else {}
    provider = str(
        job_cfg.get("selectedProvider")
        or (user_settings.llm_provider if user_settings else None)
        or os.getenv("LLM_PROVIDER", "openai")
    ).lower()

    api_keys: Dict[str, str] = {}
    if user_settings and user_settings.api_keys:
        api_keys = {
            k: v.strip()
            for k, v in user_settings.api_keys.items()
            if isinstance(v, str) and v.strip()
        }
    for p in [provider]:  # key env bổ sung cho provider chính (Render đặt ở env)
        if p and p not in api_keys:
            env_key = os.getenv(f"{p.upper()}_API_KEY")
            if env_key:
                api_keys[p] = env_key.strip()

    deep_model = (
        job_cfg.get("selectedDeepModel")
        or (user_settings.deep_think_model if user_settings else None)
        or "gpt-4o"
    )
    quick_model = (
        job_cfg.get("selectedQuickModel")
        or (user_settings.quick_think_model if user_settings else None)
        or "gpt-4o-mini"
    )

    if not api_keys.get(provider):
        # cho phép provider keyless (ollama/lmstudio/openai_compatible)
        if map_provider_for_client(provider) not in ("openai_compatible",) and provider not in ("ollama", "lmstudio"):
            return None

    config: Dict[str, Any] = {
        "ticker": job.ticker,
        "asset_type": job_cfg.get("asset_type", "stock"),
        "analysis_date": datetime.datetime.now().strftime("%Y-%m-%d"),
        "llm_provider": provider,
        "model": deep_model,
        "deep_think_model": deep_model,
        "quick_think_model": quick_model,
        "depth": str(job.depth or "medium").lower(),
        "api_keys": api_keys,
        "api_key": api_keys.get(provider),
        "active_teams": [
            "fundamentals" if job_cfg.get("teamFundamentals", True) else None,
            "sentiment" if job_cfg.get("teamSentiment", True) else None,
            "news" if job_cfg.get("teamNews", True) else None,
            "technical" if job_cfg.get("teamTechnical", True) else None,
        ],
        "output_language": (user_settings.language if user_settings else None) or "English",
    }
    config["active_teams"] = [t for t in config["active_teams"] if t]
    if user_settings and user_settings.llm_backend_url and provider in ("ollama", "lmstudio"):
        config["backend_url"] = user_settings.llm_backend_url
    if user_settings and user_settings.temperature is not None:
        config["temperature"] = user_settings.temperature
    return config


async def run_job(job_id: int) -> Optional[int]:
    """Chạy một job ngay bây giờ; trả về report_id (None khi bị chặn).

    Dùng chung cho scheduler loop và endpoint "Run now" của UI.
    """
    # Import muộn để tránh circular import qua app.main.
    from app.agent_core.agents.research_agent import ResearchAgentRunner
    from app.agent_core.common.callbacks import MongoStatsCallbackHandler
    from app.routers.v1.agent_reports.models.relational import (
        Report,
        ReportAgentOutput,
        ReportForecast,
    )

    async with AsyncSessionLocal() as session:
        job = await session.get(Job, job_id)
        if job is None:
            raise ValueError(f"Job {job_id} not found")
        user_id = job.user_id
        ticker = job.ticker
        job_cfg = dict(job.config or {})
        config = await _build_job_config(job, user_id)

        if config is None:
            job_cfg["last_error"] = "no API key available for provider"
            await session.execute(
                Job.__table__.update().where(Job.id == job_id).values(config=job_cfg)
            )
            await session.commit()
            logger.warning("Job %s skipped: no API key for provider", job_id)
            return None

        report = Report(user_id=user_id, job_id=job_id, ticker=ticker, status="running")
        session.add(report)
        await session.commit()
        await session.refresh(report)
        report_id = report.id

    callback = MongoStatsCallbackHandler(user_id=user_id, message_id=None)
    runner = ResearchAgentRunner(config=config, callbacks=[callback])

    final_state: Dict[str, Any] = {}
    try:
        async for event in runner.run_and_stream(report_id=report_id):
            if event.get("type") == "pipeline_complete":
                final_state = event.get("final_state") or {}
            elif event.get("type") == "pipeline_error":
                raise RuntimeError(event.get("content", "pipeline error"))
    except Exception:
        # Không set failed thì report treo "running" vĩnh viễn trên UI.
        with contextlib.suppress(Exception):
            async with AsyncSessionLocal() as session:
                report = await session.get(Report, report_id)
                if report is not None:
                    report.status = "failed"
                    report.summary = "Pipeline error (xem log backend / job last_error)"
                    await session.commit()
        raise

    update: Dict[str, Any] = {
        "status": "completed",
        "summary": (final_state.get("investment_plan") or "")[:4000],
    }
    structured = final_state.get("structured_report") or {}
    if structured:
        update["recommendation"] = structured.get("recommendation")
        update["confidence"] = structured.get("confidence")
        update["summary"] = structured.get("summary", update["summary"])
        for field in ("current_price", "target_price", "stop_loss", "risk_reward"):
            val = structured.get(field)
            if val is not None:
                update[field] = val

    now = datetime.datetime.now(datetime.timezone.utc)
    async with AsyncSessionLocal() as session:
        report = await session.get(Report, report_id)
        if report is not None:
            for k, v in update.items():
                setattr(report, k, v)
            if structured:
                for out in structured.get("agent_outputs", []):
                    session.add(ReportAgentOutput(
                        report_id=report_id,
                        team_name=out.get("team", ""),
                        agent_name=out.get("agent", ""),
                        recommendation=out.get("recommendation", ""),
                        confidence=int(out.get("confidence", 0) or 0),
                        summary=out.get("summary", ""),
                    ))
                for f in structured.get("forecasts", []):
                    session.add(ReportForecast(
                        report_id=report_id,
                        day_offset=f.get("day") or "",
                        price_low=f.get("low") or 0.0,
                        price_high=f.get("high") or 0.0,
                        price_target=f.get("price") or 0.0,
                        signal=f.get("signal") or "",
                    ))
            await session.commit()

        job = await session.get(Job, job_id)
        if job is not None:
            job_cfg = dict(job.config or {})
            job_cfg["last_run_at"] = now.isoformat()
            job_cfg["last_report_id"] = report_id
            job_cfg.pop("last_error", None)
            job_cfg["next_run_at"] = next_due_after(job, now).isoformat()
            await session.execute(
                Job.__table__.update().where(Job.id == job_id).values(config=job_cfg)
            )
            await session.commit()

    logger.info("Job %s (%s) completed -> report %s", job_id, ticker, report_id)
    return report_id
