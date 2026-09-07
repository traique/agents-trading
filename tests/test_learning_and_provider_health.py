"""Tests cho vòng tự học IC + provider health tracking."""
import json
import time

from tradingagents.consensus.learning import (
    learning_summary,
    rating_accuracy,
    write_rolling_ic,
    load_rolling_ic,
)
from tradingagents.dataflows.provider_health import (
    get_provider_health,
    record_provider_probe,
)


def _entry(ticker="HPG", date="2026-01-01", rating="Buy", raw=None, alpha="+1.0%",
           pending=False):
    e = {
        "ticker": ticker, "date": date, "rating": rating, "pending": pending,
        "raw": raw if raw is not None else ("pending" if pending else "+2.0%"),
        "alpha": alpha, "holding": "5d",
    }
    if pending:
        e["raw"] = None
    return e


class TestRatingAccuracy:
    def test_buy_hits_when_positive(self):
        entries = [_entry(rating="Buy", raw="+3.0%"), _entry(rating="Buy", raw="-1.0%")]
        stats = rating_accuracy(entries)
        buy = stats["per_rating"]["Buy"]
        assert buy["n"] == 2 and buy["hits"] == 1
        assert buy["hit_rate"] == 0.5
        assert stats["signal_ic"] == 0.0

    def test_sell_hits_when_negative(self):
        entries = [_entry(rating="Sell", raw="-2.0%"), _entry(rating="Sell", raw="-1.0%")]
        stats = rating_accuracy(entries)
        assert stats["per_rating"]["Sell"]["hits"] == 2
        assert stats["signal_ic"] == 1.0

    def test_single_directional_entry_has_no_ic(self):
        stats = rating_accuracy([_entry(rating="Sell", raw="-2.0%")])
        assert stats["signal_ic"] is None

    def test_hold_uses_tolerance(self):
        entries = [_entry(rating="Hold", raw="+0.3%")]
        stats = rating_accuracy(entries)
        assert stats["per_rating"]["Hold"]["hits"] == 1

    def test_pending_excluded(self):
        stats = rating_accuracy([_entry(pending=True)])
        assert stats["total_n"] == 0

    def test_empty(self):
        assert rating_accuracy([])["total_n"] == 0


class TestRollingIcFile:
    def test_write_and_load_roundtrip(self, tmp_path):
        entries = [_entry(rating="Buy", raw="+1.5%"), _entry(rating="Sell", raw="-2.5%")]
        path = write_rolling_ic(entries, str(tmp_path))
        assert path is not None and path.endswith("rolling_ic.json")
        stats = load_rolling_ic(str(tmp_path))
        assert stats["total_n"] == 2
        assert stats["signal_ic"] == 1.0

    def test_load_missing_returns_empty(self, tmp_path):
        assert load_rolling_ic(str(tmp_path)) == {}

    def test_history_capped(self, tmp_path):
        entries = [_entry()]
        for _ in range(35):
            write_rolling_ic(entries, str(tmp_path))
        with open(str(tmp_path / "feedback" / "rolling_ic.json")) as f:
            payload = json.load(f)
        assert len(payload["history"]) <= 30


class TestLearningSummary:
    def test_below_min_samples_returns_empty(self):
        assert learning_summary([_entry()], min_samples=3) == ""

    def test_summary_mentions_ratings_and_calibration(self):
        entries = [_entry(rating="Buy", raw="+2%"), _entry(rating="Buy", raw="+1%"),
                   _entry(rating="Sell", raw="-3%")]
        summary = learning_summary(entries, min_samples=3)
        assert "Self-evaluation" in summary
        assert "Buy" in summary and "Sell" in summary
        assert "calibration" in summary


class TestProviderHealth:
    def test_record_and_snapshot(self, tmp_path, monkeypatch):
        cache = str(tmp_path / "cache")
        monkeypatch.setenv("TRADINGAGENTS_DATA_CACHE_DIR", cache)
        record_provider_probe("dnse", True, symbol="HPG")
        record_provider_probe("dnse", False, detail="timeout", symbol="HPG")
        record_provider_probe("tcbs", True, symbol="HPG")
        health = get_provider_health(cache)
        assert health["dnse"]["attempts"] == 2
        assert health["dnse"]["successes"] == 1
        assert health["dnse"]["last_ok"] is False
        assert health["dnse"]["last_error"] == "timeout"
        assert health["tcbs"]["last_ok"] is True

    def test_recent_success_rate(self, tmp_path):
        cache = str(tmp_path / "cache2")
        for i in range(10):
            record_provider_probe("tcbs", i < 7, cache_dir=cache)
        health = get_provider_health(cache)
        assert health["tcbs"]["recent_success_rate"] == 70

    def test_unavailable_source_ignored(self, tmp_path):
        cache = str(tmp_path / "c3")
        record_provider_probe("unavailable", False, cache_dir=cache)
        assert get_provider_health(cache) == {}
