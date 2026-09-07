"""Vòng tự học kiểu IC (Information Coefficient) — lấy cảm hứng từ augur.

Memory log của pipeline đã lưu mỗi dự đoán dạng tag
``[date | ticker | rating | raw | alpha | holding]`` kèm kết quả thực tế
được đối chiếu khi giá đủ window. Module này gộp các entry đã resolve thành
thống kê độ chính xác theo từng tầng rating (mua đúng bao nhiêu %, bán đúng
bao nhiêu %...), ghi ra ``rolling_ic.json`` trong cache để quan sát được, và
sinh một đoạn markdown "bảng tự đánh giá" inject vào context của các agent
kỳ sau — tức là vòng: dự đoán → đối chiếu → hiệu chỉnh niềm tin.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from typing import Any, Dict, Iterable, List

logger = logging.getLogger(__name__)

# Rating 5 tầng → hướng kỳ vọng của alpha: Buy/Owerweight kỳ vọng dương,
# Sell/Underweight kỳ vọng âm, Hold kỳ vọng ~0 (đánh giá bằng |alpha| nhỏ).
RATING_DIRECTION = {
    "Buy": +1,
    "Overweight": +1,
    "Hold": 0,
    "Underweight": -1,
    "Sell": -1,
}

_HIT_TOLERANCE = 0.005  # |alpha| dưới 0.5% coi như side-ways, không tính đúng/sai


def _parse_pct(value: Any) -> float | None:
    """Parse '±x.y%' / float từ tag của memory log về số thực."""
    if value is None:
        return None
    s = str(value).strip()
    if s.endswith("%"):
        try:
            return float(s[:-1]) / 100.0
        except ValueError:
            return None
    try:
        return float(s)
    except ValueError:
        return None


def rating_accuracy(entries: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """Thống kê độ chính xác hướng (directional hit-rate) theo từng rating.

    Entry resolve phải có ``rating`` và ``raw``. BUY/Overweight được tính
    "đúng" khi raw > 0, Sell/Underweight khi raw < 0, Hold khi |raw| dưới
    ngưỡng side-ways. Trả về ``{rating: {n, hits, hit_rate, avg_return}}``
    và tổng hợp toàn cục.
    """
    buckets: Dict[str, Dict[str, Any]] = {}
    for e in entries:
        if e.get("pending"):
            continue
        rating = str(e.get("rating", "")).strip().capitalize()
        direction = RATING_DIRECTION.get(rating)
        raw = _parse_pct(e.get("raw"))
        if direction is None or raw is None:
            continue
        b = buckets.setdefault(rating, {"n": 0, "hits": 0, "sum_return": 0.0})
        b["n"] += 1
        b["sum_return"] += raw
        if direction == 0:
            if abs(raw) <= _HIT_TOLERANCE:
                b["hits"] += 1
        elif (raw > 0) == (direction > 0):
            b["hits"] += 1

    stats: Dict[str, Any] = {}
    total_n = total_hits = 0
    for rating, b in sorted(buckets.items(), key=lambda kv: -kv[1]["n"]):
        n = b["n"]
        total_n += n
        total_hits += b["hits"]
        stats[rating] = {
            "n": n,
            "hits": b["hits"],
            "hit_rate": round(b["hits"] / n, 3) if n else None,
            "avg_return": round(b["sum_return"] / n, 4) if n else None,
        }

    # Signal IC thô: tương quan dấu giữa hướng rating và dấu raw return
    # (chỉ tính trên các entry có hướng rõ ràng, bỏ Hold).
    directional = [
        (RATING_DIRECTION[str(e.get("rating", "")).strip().capitalize()], _parse_pct(e.get("raw")))
        for e in entries
        if not e.get("pending")
        and RATING_DIRECTION.get(str(e.get("rating", "")).strip().capitalize(), 0) != 0
    ]
    directional = [(d, r) for d, r in directional if r is not None]
    ic = None
    if len(directional) >= 2:
        agree = sum(1 for d, r in directional if (r > 0) == (d > 0))
        ic = round(2 * agree / len(directional) - 1, 3)  # 1.0 = hoàn toàn đúng chiều

    return {
        "per_rating": stats,
        "total_n": total_n,
        "total_hits": total_hits,
        "overall_hit_rate": round(total_hits / total_n, 3) if total_n else None,
        "signal_ic": ic,
    }


def write_rolling_ic(
    entries: Iterable[Dict[str, Any]],
    cache_dir: str | None,
    stats: Dict[str, Any] | None = None,
) -> str | None:
    """Ghi snapshot thống kê vào ``{cache_dir}/feedback/rolling_ic.json``.

    ``stats`` cho phép truyền sẵn kết quả ``rating_accuracy`` (caller đã tính
    cho learning_summary) để khỏi quét entries lần thứ hai.
    """
    try:
        base = cache_dir or os.getenv("TRADINGAGENTS_CACHE_DIR")
        if not base:
            return None
        if stats is None:
            stats = rating_accuracy(entries)
        fb_dir = os.path.join(base, "feedback")
        os.makedirs(fb_dir, exist_ok=True)
        path = os.path.join(fb_dir, "rolling_ic.json")
        payload = {"stats": stats}
        try:
            with open(path, "r", encoding="utf-8") as f:
                old = json.load(f)
            payload["history"] = (old.get("history") or [])[-29:]
        except (OSError, ValueError):
            payload["history"] = []
        payload["history"].append({"overall_hit_rate": stats["overall_hit_rate"], "signal_ic": stats["signal_ic"], "n": stats["total_n"]})
        fd, tmp = tempfile.mkstemp(dir=fb_dir, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        os.replace(tmp, path)
        return path
    except OSError as e:
        logger.debug("Không ghi được rolling_ic.json: %s", e)
        return None


def load_rolling_ic(cache_dir: str | None = None) -> Dict[str, Any]:
    """Đọc lại snapshot rolling IC đã ghi (mặc định rỗng nếu chưa có)."""
    base = cache_dir or os.getenv("TRADINGAGENTS_CACHE_DIR")
    if not base:
        return {}
    path = os.path.join(base, "feedback", "rolling_ic.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f).get("stats", {})
    except (OSError, ValueError):
        return {}


def learning_summary(
    entries: List[Dict[str, Any]],
    min_samples: int = 3,
    stats: Dict[str, Any] | None = None,
) -> str:
    """Markdown tự đánh giá inject vào context các agent ở lần chạy sau.

    Chỉ hiện khi đủ ``min_samples`` entry đã resolve — dưới ngưỡng đó, thống
    kê không đủ tin cậy và việc inject sẽ là noise (và nguy hiểm: agent có thể
    đọc sai tín hiệu từ 1-2 mẫu). Đây cũng là lý do đoạn này luôn kèm cảnh
    báo cỡ mẫu để agent không be quá tay. ``stats`` truyền sẵn kết quả
    ``rating_accuracy`` để tránh tính lại.
    """
    if stats is None:
        stats = rating_accuracy(entries)
    n = stats["total_n"]
    if n < min_samples:
        return ""
    lines = [
        f"### Self-evaluation (loop tự học — {n} quyết định đã đối chiếu kết quả thực tế)",
    ]
    ic = stats.get("signal_ic")
    if ic is not None:
        lines.append(f"- Signal IC (tương quan hướng rating ↔ hướng giá thực tế): {ic:+.2f}")
    for rating, s in stats["per_rating"].items():
        if not s["n"]:
            continue
        avg = s.get("avg_return")
        avg_txt = f", lợi nhuận trung bình {avg:+.2%}" if avg is not None else ""
        lines.append(
            f"- Rating **{rating}**: đúng hướng {s['hits']}/{s['n']} lần "
            f"({s['hit_rate']:.0%}){avg_txt}"
        )
    lines.append(
        "- Lưu ý: cỡ mẫu còn nhỏ, hãy dùng các con số này để hiệu chỉnh mức "
        "tin cậy (calibration) chứ không đảo ngược chiến lược."
    )
    return "\n".join(lines)
