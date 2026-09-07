"""Tests cho consensus/kelly — điểm đồng thuận có trọng số + vị thế Kelly."""
from tradingagents.consensus.kelly import (
    consensus_from_outputs,
    kelly_fraction,
    position_sizing,
    render_consensus_markdown,
)


class TestConsensusFromOutputs:
    def test_empty_outputs(self):
        result = consensus_from_outputs([])
        assert result["score_0_10"] is None
        assert result["n_agents"] == 0

    def test_all_buy_full_score(self):
        outputs = [
            {"recommendation": "BUY", "confidence": 90},
            {"recommendation": "BUY", "confidence": 80},
        ]
        result = consensus_from_outputs(outputs)
        assert result["score_0_10"] == 10.0
        assert result["bullish"] == 2
        assert result["n_agents"] == 2

    def test_split_equals_five(self):
        outputs = [
            {"recommendation": "BUY", "confidence": 50},
            {"recommendation": "SELL", "confidence": 50},
        ]
        result = consensus_from_outputs(outputs)
        assert result["score_0_10"] == 5.0
        assert result["bullish"] == 1 and result["bearish"] == 1

    def test_confidence_weights_score(self):
        # BUY 90 conf + SELL 10 conf → nghiêng mạnh về BUY
        outputs = [
            {"recommendation": "BUY", "confidence": 90},
            {"recommendation": "SELL", "confidence": 10},
        ]
        result = consensus_from_outputs(outputs)
        assert result["score_0_10"] > 8.0

    def test_invalid_entries_skipped(self):
        outputs = [
            {"recommendation": "MAYBE", "confidence": 50},
            {"recommendation": "BUY", "confidence": 0},
            {"recommendation": "HOLD", "confidence": 40},
        ]
        result = consensus_from_outputs(outputs)
        # HOLD 40 conf là mục duy nhất hợp lệ → 5.0
        assert result["score_0_10"] == 5.0
        assert result["neutral"] == 1


class TestKellyFraction:
    def test_zero_when_no_edge(self):
        # p quá thấp so với b → f <= 0
        assert kelly_fraction(0.1, 1.0) == 0.0

    def test_positive_when_edge(self):
        # f* = 0.6 - 0.4/2 = 0.4, mặc định fraction=0.5 → half Kelly = 0.2
        assert kelly_fraction(0.6, 2.0) == 0.2
        # full Kelly nhưng vẫn bị cap bởi max_position mặc định 0.25
        assert kelly_fraction(0.6, 2.0, fraction=1.0) == 0.25
        # nới cap thì đạt full Kelly
        assert kelly_fraction(0.6, 2.0, fraction=1.0, max_position=0.5) == 0.4

    def test_half_kelly_cap(self):
        f = kelly_fraction(0.9, 3.0, fraction=0.5, max_position=0.25)
        assert f <= 0.25

    def test_invalid_inputs(self):
        assert kelly_fraction(0, 2) == 0.0
        assert kelly_fraction(1.5, 2) == 0.0
        assert kelly_fraction(0.5, 0) == 0.0
        assert kelly_fraction(0.5, -1) == 0.0


class TestPositionSizing:
    def test_buy_uses_kelly(self):
        sizing = position_sizing("BUY", 70, 2.0)
        assert sizing["recommendation"] == "BUY"
        assert sizing["win_prob"] == 0.7
        assert sizing["kelly_half"] > 0
        assert sizing["suggested_pct"] == sizing["kelly_half"] * 100

    def test_sell_and_hold_are_zero(self):
        assert position_sizing("SELL", 90, 3.0)["kelly_half"] == 0.0
        assert position_sizing("HOLD", 80, 3.0)["kelly_half"] == 0.0

    def test_missing_rr_falls_back_to_two(self):
        sizing = position_sizing("BUY", 50, None)
        assert sizing["win_loss_ratio"] == 2.0


class TestRenderMarkdown:
    def test_renders_both_lines(self):
        consensus = {
            "score_0_10": 7.2, "bullish": 3, "neutral": 1, "bearish": 0, "n_agents": 4,
        }
        sizing = {
            "recommendation": "BUY", "win_prob": 0.7, "win_loss_ratio": 2.0,
            "suggested_pct": 10.5,
        }
        md = render_consensus_markdown(consensus, sizing)
        assert "7.2/10" in md
        assert "3 Bull" in md
        assert "Kelly" in md
