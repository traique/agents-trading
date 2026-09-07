"""Theo dõi sức khỏe nguồn dữ liệu VN (lấy cảm hứng từ augur doctor).

Mỗi lần chuỗi dự phòng OHLCV chạy, kết quả của từng tầng (dnse, vnstock-vci,
tcbs) được ghi vào một file JSON nhỏ trong ``data_cache_dir``. File tích lũy
thành xu hướng: lần probe gần nhất, tổng lần thử/tổng lần thành công, và
timestamp thành công cuối cùng của từng nguồn. Từ đó trả lời được câu hỏi
"nguồn nào đang lặng lẽ chết" mà không cần đọc log.

File là append-only per-run JSON (atomic replace), an toàn khi nhiều process
ghi gần như đồng thời vì mỗi lần ghi là toàn bộ snapshot — biến mất tối đa
một vài probe khi đụng độ, không bao giờ hỏng file.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

MAX_HISTORY = 30  # số lần probe lưu gần nhất cho mỗi nguồn


def _stats_path(cache_dir: str | None = None) -> str:
    base = cache_dir or os.getenv("TRADINGAGENTS_DATA_CACHE_DIR", "./tradingagents/data/cache")
    return os.path.join(base, "vn_provider_stats.json")


def record_provider_probe(
    source: str,
    success: bool,
    *,
    cache_dir: str | None = None,
    detail: str | None = None,
    symbol: str | None = None,
) -> None:
    """Ghi kết quả một lần probe nguồn ``source`` (dnse / vnstock-vci / tcbs)."""
    if not source or source == "unavailable":
        return
    path = _stats_path(cache_dir)
    data = _load(path)
    now = time.time()
    entry = data.setdefault(source, {"attempts": 0, "successes": 0})
    entry["attempts"] = int(entry.get("attempts", 0)) + 1
    if success:
        entry["successes"] = int(entry.get("successes", 0)) + 1
        entry["last_success_ts"] = now
        entry["last_success_symbol"] = symbol
    entry["last_attempt_ts"] = now
    entry["last_ok"] = bool(success)
    if detail:
        entry["last_error"] = str(detail)[:300]
    history = entry.get("recent", [])
    history.append({"ts": round(now, 3), "ok": bool(success)})
    entry["recent"] = history[-MAX_HISTORY:]

    _save(path, data)


def get_provider_health(cache_dir: str | None = None) -> Dict[str, Any]:
    """Trả về snapshot sức khỏe hiện tại của các nguồn đã được probe."""
    data = _load(_stats_path(cache_dir))
    health: Dict[str, Any] = {}
    for source, entry in data.items():
        recent = entry.get("recent", [])
        health[source] = {
            "attempts": int(entry.get("attempts", 0)),
            "successes": int(entry.get("successes", 0)),
            "last_ok": entry.get("last_ok"),
            "last_attempt_ts": entry.get("last_attempt_ts"),
            "last_success_ts": entry.get("last_success_ts"),
            "last_error": entry.get("last_error"),
            "recent_success_rate": (
                round(100 * sum(1 for r in recent if r.get("ok")) / len(recent))
                if recent
                else None
            ),
        }
    return health


def _load(path: str) -> Dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(path: str, data: Dict[str, Any]) -> None:
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, path)
    except OSError as e:
        logger.debug("Không ghi được provider stats (%s): %s", path, e)
