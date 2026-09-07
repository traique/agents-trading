"""Cơ chế đồng thuận + vị thế Kelly (lấy cảm hứng từ augur).

Phần bổ sung này là deterministic (không gọi thêm LLM): sau khi pipeline
chạy xong, các output của từng agent (recommendation + confidence) được gộp
thành một điểm đồng thuận có trọng số, và khuyến nghị vị thế được tính theo
công thức Kelly từ cặp (win-probability ~ confidence, risk/reward của
entry/target/stop). Kết quả đính kèm vào executive summary thay vì để mỗi
agent tự phán một con số.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

# Map recommendation chuẩn hoá (BUY/HOLD/SELL) → điểm có dấu.
_REC_SCORE = {"BUY": 1.0, "HOLD": 0.0, "SELL": -1.0}


def consensus_from_outputs(agent_outputs: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Gộp danh sách output của các agent thành điểm đồng thuận có trọng số.

    Mỗi output cần ``recommendation`` (BUY/HOLD/SELL — đã chuẩn hoá) và
    ``confidence`` (0-100). Trọng số là confidence; điểm cuối ∈ [0, 10] trên
    thang tăng dần từ SELL tới BUY, kèm phân bố bull/neutral/bear.
    """
    scored: list[tuple[float, float]] = []
    bullish = neutral = bearish = 0
    for out in agent_outputs or []:
        rec = str(out.get("recommendation", "")).upper().strip()
        try:
            conf = float(out.get("confidence", 0))
        except (TypeError, ValueError):
            conf = 0.0
        if rec not in _REC_SCORE or conf <= 0:
            continue
        scored.append((_REC_SCORE[rec], conf))
        if rec == "BUY":
            bullish += 1
        elif rec == "SELL":
            bearish += 1
        else:
            neutral += 1

    total_conf = sum(c for _, c in scored)
    if not scored or total_conf <= 0:
        return {
            "score_0_10": None, "distribution": None,
            "bullish": 0, "neutral": 0, "bearish": 0, "n_agents": 0,
        }

    weighted = sum(s * c for s, c in scored) / total_conf  # [-1, 1]
    return {
        "score_0_10": round((weighted + 1) * 5, 1),  # 0..10
        "distribution": weighted,
        "bullish": bullish,
        "neutral": neutral,
        "bearish": bearish,
        "n_agents": len(scored),
    }


def kelly_fraction(
    win_prob: float,
    win_loss_ratio: float,
    *,
    fraction: float = 0.5,
    max_position: float = 0.25,
) -> float:
    """Tỷ lệ vị thế theo công thức Kelly: f* = p - (1-p)/b.

    ``fraction`` là mức Kelly dùng thật (mặc định nửa Kelly để giảm variance);
    kết quả được chặn trên bởi ``max_position`` (25% vốn) và chặn dưới 0.
    Trả về 0 khi input vô nghĩa (p ngoài (0,1) hoặc b <= 0).
    """
    try:
        p = float(win_prob)
        b = float(win_loss_ratio)
    except (TypeError, ValueError):
        return 0.0
    if not (0.0 < p < 1.0) or b <= 0:
        return 0.0
    f = p - (1.0 - p) / b
    if f <= 0:
        return 0.0
    return round(min(f * fraction, max_position), 4)


def position_sizing(
    recommendation: str,
    confidence: float,
    risk_reward: Optional[float],
) -> Dict[str, Any]:
    """Khuyến nghị vị thế Kelly cho khuyến nghị cuối của Portfolio Manager.

    Win probability xấp xỉ bằng confidence (0-100 → 0-1); b là risk/reward
    (target/stop). Fallback b = 2.0 khi không có cặp target/stop hợp lệ —
    giá trị trung bình của khuyến nghị có kỷ luật. SELL/HOLD luôn trả về 0
    vì Kelly chỉ định nghĩa cho vị thế dài.
    """
    rec = str(recommendation or "").upper().strip()
    w = max(0.05, min(0.95, (confidence or 0) / 100.0))
    b = risk_reward if risk_reward and risk_reward > 0 else 2.0
    if rec != "BUY":
        full = 0.0
    else:
        full = kelly_fraction(w, b, fraction=1.0, max_position=0.5)
    half = round(full * 0.5, 4)
    return {
        "recommendation": rec,
        "win_prob": round(w, 3),
        "win_loss_ratio": round(float(b), 2),
        "kelly_full": full,
        "kelly_half": half,
        "suggested_pct": half * 100,
    }


def render_consensus_markdown(consensus: Dict[str, Any], sizing: Dict[str, Any]) -> str:
    """Render hai dòng markdown cho executive summary (Consensus + Kelly)."""
    lines: list[str] = []
    score = consensus.get("score_0_10")
    if score is not None:
        dist = (
            f"{consensus['bullish']} Bull / {consensus['neutral']} Neutral"
            f" / {consensus['bearish']} Bear"
        )
        lines.append(f"**Consensus score:** {score}/10 ({dist}, {consensus['n_agents']} agents)")
    pct = sizing.get("suggested_pct")
    if sizing.get("recommendation") == "BUY" and pct:
        lines.append(
            f"**Position sizing (Kelly×½):** {pct:.1f}% vốn "
            f"(p={sizing['win_prob']:.0%}, b={sizing['win_loss_ratio']})"
        )
    elif sizing.get("recommendation") == "BUY":
        lines.append("**Position sizing (Kelly×½):** 0% — win-probability không đủ cho vị thế dài")
    return "\n".join(lines)
