"""Unit tests cho chuỗi dự phòng OHLCV VN (vn_ohlcv) - không gọi network."""
from unittest.mock import patch

import pytest

from tradingagents.dataflows.vn_ohlcv import (
    OhlcvSeries,
    fetch_vn_ohlcv,
    validate_ohlcv,
)


def _series(source="dnse", closes=None, **overrides):
    closes = [25000.0, 25200.0, 25100.0, 25400.0, 25500.0] if closes is None else closes
    n = len(closes)
    data = dict(
        symbol="HPG",
        opens=[c - 100 for c in closes],
        highs=[c + 200 for c in closes],
        lows=[c - 200 for c in closes],
        closes=closes,
        volumes=[1_000_000.0] * n,
        dates=["2026-09-01", "2026-09-02", "2026-09-03", "2026-09-04", "2026-09-07"][:n],
        source=source,
    )
    data.update(overrides)
    return OhlcvSeries(**data)


class TestValidateOhlcv:
    def test_valid_series_has_no_errors(self):
        assert validate_ohlcv(_series()) == []

    def test_empty_series_rejected(self):
        assert validate_ohlcv(_series(closes=[])) == ["empty"]

    def test_too_few_bars_rejected(self):
        errors = validate_ohlcv(_series(closes=[25000.0, 25100.0]))
        assert any("too few bars" in e for e in errors)

    def test_negative_price_rejected(self):
        errors = validate_ohlcv(_series(closes=[25000.0, 25200.0, -1.0, 25400.0, 25500.0]))
        assert any("invalid close" in e for e in errors)

    def test_high_below_low_rejected(self):
        s = _series()
        s.highs[0], s.lows[0] = s.lows[0] - 1, s.lows[0]
        assert any("high < low" in e for e in validate_ohlcv(s))

    def test_stale_series_rejected(self):
        errors = validate_ohlcv(_series(dates=["2025-01-01"] * 5))
        assert any("stale" in e for e in errors)


class TestFetchDnse:
    # epoch 2026-09-02/03 UTC - gần hiện tại để không bị validate coi là stale
    T1, T2 = 1788220800, 1788307200

    def test_stock_prices_scaled_from_thousand_vnd(self):
        payload = {
            "t": [self.T1, self.T2],
            "o": [25.0, 25.2],
            "h": [25.4, 25.6],
            "l": [24.8, 25.0],
            "c": [25.3, 25.5],
            "v": [1000, 2000],
        }
        resp = type("R", (), {"status_code": 200, "json": lambda self: payload})()
        with patch("tradingagents.dataflows.vn_ohlcv.requests.get", return_value=resp):
            with patch("tradingagents.dataflows.vn_ohlcv.validate_ohlcv", return_value=[]):
                series = fetch_vn_ohlcv("HPG", "2026-09-01", "2026-09-07")
        assert series.source == "dnse"
        assert series.closes == [25300, 25500]
        assert series.opens == [25000, 25200]

    def test_index_prices_not_scaled(self):
        payload = {"t": [self.T1], "o": [1280.0], "h": [1290.0], "l": [1275.0], "c": [1285.0], "v": [0]}
        resp = type("R", (), {"status_code": 200, "json": lambda self: payload})()
        with patch("tradingagents.dataflows.vn_ohlcv.requests.get", return_value=resp):
            with patch("tradingagents.dataflows.vn_ohlcv.validate_ohlcv", return_value=[]):
                series = fetch_vn_ohlcv("VNINDEX", "2026-09-01", "2026-09-07")
        assert series.source == "dnse"
        assert series.closes == [1285]

    def test_network_error_returns_unavailable(self):
        import requests as requests_mod

        with patch(
            "tradingagents.dataflows.vn_ohlcv.requests.get",
            side_effect=requests_mod.ConnectionError("boom"),
        ):
            with patch(
                "tradingagents.dataflows.vn_ohlcv._fetch_vnstock",
                return_value=OhlcvSeries(symbol="HPG"),
            ):
                with patch("tradingagents.dataflows.vn_vendor._fetch_tcbs_ohlcv", return_value=None):
                    series = fetch_vn_ohlcv("HPG", "2026-09-01", "2026-09-07")
        assert series.source == "unavailable"


class TestFailoverChain:
    def test_falls_to_vnstock_when_dnse_invalid(self):
        with patch(
            "tradingagents.dataflows.vn_ohlcv._fetch_dnse",
            return_value=_series(closes=[]),  # empty -> contract fail
        ), patch(
            "tradingagents.dataflows.vn_ohlcv._fetch_vnstock",
            return_value=_series(source="vnstock-vci"),
        ):
            series = fetch_vn_ohlcv("HPG", "2026-09-01", "2026-09-07")
        assert series.source == "vnstock-vci"
        assert len(series.closes) == 5

    def test_falls_to_tcbs_when_dnse_and_vnstock_fail(self):
        with patch(
            "tradingagents.dataflows.vn_ohlcv._fetch_dnse",
            return_value=OhlcvSeries(symbol="HPG"),
        ), patch(
            "tradingagents.dataflows.vn_ohlcv._fetch_vnstock",
            return_value=OhlcvSeries(symbol="HPG"),
        ):
            df = _series(source="tcbs").to_dataframe()
            with patch(
                "tradingagents.dataflows.vn_vendor._fetch_tcbs_ohlcv", return_value=df
            ):
                series = fetch_vn_ohlcv("HPG", "2026-09-01", "2026-09-07")
        assert series.source == "tcbs"

    def test_all_sources_fail_returns_unavailable(self):
        with patch(
            "tradingagents.dataflows.vn_ohlcv._fetch_dnse",
            return_value=OhlcvSeries(symbol="XXX"),
        ), patch(
            "tradingagents.dataflows.vn_ohlcv._fetch_vnstock",
            return_value=OhlcvSeries(symbol="XXX"),
        ), patch(
            "tradingagents.dataflows.vn_vendor._fetch_tcbs_ohlcv", return_value=None
        ):
            series = fetch_vn_ohlcv("XXX", "2026-09-01", "2026-09-07")
        assert series.source == "unavailable"

    def test_does_not_mix_sources(self):
        """Fallback phải trả nguyên series của nguồn thắng, không ghép bar."""
        vci = _series(source="vnstock-vci", closes=[10000.0, 10100.0, 10200.0, 10300.0, 10400.0])
        with patch(
            "tradingagents.dataflows.vn_ohlcv._fetch_dnse", return_value=_series(closes=[])
        ), patch("tradingagents.dataflows.vn_ohlcv._fetch_vnstock", return_value=vci):
            series = fetch_vn_ohlcv("HPG", "2026-09-01", "2026-09-07")
        assert all(c < 20000 for c in series.closes)
        assert series.source == "vnstock-vci"
