"""Tests cho scheduler: parse frequency, tính due time, endpoint run-now."""
import asyncio
import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.services.job_scheduler import (
    JobScheduler,
    frequency_delta,
    next_due_after,
    _is_due,
)


def _job(**kw):
    now = datetime.datetime.now(datetime.timezone.utc)
    defaults = dict(
        id=1, user_id=7, ticker="HPG", frequency="Daily (00:00 UTC)",
        start_date=now - datetime.timedelta(days=3),
        end_date=None, status="active", config={},
    )
    defaults.update(kw)
    return SimpleNamespace(**defaults)


class TestFrequencyDelta:
    def test_ui_strings(self):
        assert frequency_delta("Every Hour") == datetime.timedelta(hours=1)
        assert frequency_delta("Every 4 Hours") == datetime.timedelta(hours=4)
        assert frequency_delta("Daily (00:00 UTC)") == datetime.timedelta(days=1)
        assert frequency_delta("Weekly (Mon 09:30 EST)") == datetime.timedelta(weeks=1)

    def test_fallback_daily(self):
        assert frequency_delta("Custom Cron") == datetime.timedelta(days=1)
        assert frequency_delta("") == datetime.timedelta(days=1)


class TestNextDue:
    def test_before_start_returns_start(self):
        job = _job(start_date=datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=1))
        assert next_due_after(job, datetime.datetime.now(datetime.timezone.utc)) == job.start_date

    def test_after_start_advances_one_period(self):
        now = datetime.datetime.now(datetime.timezone.utc)
        start = now - datetime.timedelta(days=3)
        job = _job(start_date=start)
        nxt = next_due_after(job, now)
        assert nxt > now
        assert (nxt - start).total_seconds() % 86400 == 0


class TestIsDue:
    def test_active_and_past_due(self):
        job = _job(config={"next_run_at": (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=5)).isoformat()})
        assert _is_due(job, datetime.datetime.now(datetime.timezone.utc)) is True

    def test_paused_not_due(self):
        job = _job(status="paused")
        assert _is_due(job, datetime.datetime.now(datetime.timezone.utc)) is False

    def test_end_date_passed(self):
        now = datetime.datetime.now(datetime.timezone.utc)
        job = _job(end_date=now - datetime.timedelta(days=1))
        assert _is_due(job, now) is False

    def test_future_next_run(self):
        job = _job(config={"next_run_at": (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=2)).isoformat()})
        assert _is_due(job, datetime.datetime.now(datetime.timezone.utc)) is False


class TestScanAndRun:
    @pytest.mark.asyncio
    async def test_dispatches_due_jobs(self):
        scheduler = JobScheduler()
        due_job = _job(id=11, config={"next_run_at": (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=1)).isoformat()})
        with patch("app.services.job_scheduler.select"), \
             patch("app.services.job_scheduler.AsyncSessionLocal") as mock_session_local:
            from unittest.mock import MagicMock
            ctx = AsyncMock()
            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = [due_job]
            ctx.execute = AsyncMock(return_value=mock_result)
            mock_session_local.return_value.__aenter__ = AsyncMock(return_value=ctx)
            mock_session_local.return_value.__aexit__ = AsyncMock(return_value=False)

            with patch.object(scheduler, "_run_job_safe", new=AsyncMock()) as run_mock:
                count = await scheduler.scan_and_run()
                assert count == 1
                # Task fire-and-forget cần event loop nhường lịch để chạy.
                await asyncio.sleep(0)
                run_mock.assert_awaited_once_with(11)
                assert 11 in scheduler._running_jobs
                scheduler._running_jobs.discard(11)
