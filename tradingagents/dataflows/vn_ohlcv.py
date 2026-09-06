"""OHLCV cho thị trường Việt Nam theo chuỗi dự phòng đa nguồn.

Nguồn được thử theo thứ tự, nguồn nào trả dữ liệu hợp lệ đầu tiên thì thắng:
  1. DNSE Entrade chart-api (công khai, không cần key)
  2. vnstock/VCI (thư viện vnstock, tuỳ chọn - bỏ qua nếu chưa cài)
  3. TCBS (raw fetch của vn_vendor, tầng cuối cùng)

Một series chỉ được chấp nhận khi qua hết contract `validate_ohlcv`; nếu
không, tầng kế tiếp được thử. Không bao giờ ghép bar từ hai nguồn khác
nhau trong cùng một series vì chuẩn điều chỉnh giá cổ tức khác nhau giữa
các nguồn sẽ tạo gap giả cho MA/RSI.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone

import requests

from .vn_vendor import _strip_vn_suffix

logger = logging.getLogger(__name__)

DNSE_OHLC_BASE = "https://services.entrade.com.vn/chart-api/v2/ohlcs"
# DNSE trả giá cổ phiếu theo nghìn VND, giá index là điểm gốc.
DNSE_PRICE_SCALE = 1000
REQUEST_TIMEOUT = 10
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "Chrome/120.0.0.0 Safari/537.36"
)

INDEX_SYMBOLS = {"VNINDEX", "VN30", "HNXINDEX", "HNX30", "UPCOMINDEX", "UPINDEX"}


def is_vn_index(symbol: str) -> bool:
    return symbol.upper().replace("-", "").replace("^", "") in INDEX_SYMBOLS


@dataclass
class OhlcvSeries:
    symbol: str
    opens: list[float] = field(default_factory=list)
    highs: list[float] = field(default_factory=list)
    lows: list[float] = field(default_factory=list)
    closes: list[float] = field(default_factory=list)
    volumes: list[float] = field(default_factory=list)
    dates: list[str] = field(default_factory=list)
    source: str = "unavailable"

    def to_dataframe(self) -> "pd.DataFrame":
        import pandas as pd

        df = pd.DataFrame(
            {
                "Open": self.opens,
                "High": self.highs,
                "Low": self.lows,
                "Close": self.closes,
                "Volume": self.volumes,
            },
            index=pd.to_datetime(self.dates),
        )
        df.index.name = "Date"
        return df


def validate_ohlcv(
    series: OhlcvSeries,
    *,
    min_bars: int = 5,
    max_stale_days: int = 10,
) -> list[str]:
    """Trả về danh sách lỗi contract; rỗng nghĩa là series dùng được."""
    errors: list[str] = []
    n = len(series.closes)
    if n == 0:
        return ["empty"]
    if n < min_bars:
        errors.append(f"too few bars: {n} < {min_bars}")
    for name, values in (
        ("open", series.opens),
        ("high", series.highs),
        ("low", series.lows),
        ("close", series.closes),
    ):
        if len(values) != n:
            errors.append(f"{name} length mismatch")
            continue
        for v in values:
            if not math.isfinite(v) or v <= 0:
                errors.append(f"invalid {name} value: {v!r}")
                break
    if len(series.highs) == n and len(series.lows) == n:
        for h, l in zip(series.highs, series.lows):
            if h < l:
                errors.append("high < low")
                break
    if series.dates:
        try:
            last = datetime.strptime(series.dates[-1], "%Y-%m-%d")
            stale = (datetime.now(timezone.utc) - last.replace(tzinfo=timezone.utc)).days
            if stale > max_stale_days:
                errors.append(f"stale: last bar {series.dates[-1]} ({stale} days ago)")
        except ValueError:
            errors.append(f"unparseable date: {series.dates[-1]!r}")
    return errors


def _dnse_symbol(symbol: str) -> str:
    s = symbol.upper()
    return "VNINDEX" if s in ("^VNINDEX", "VN-INDEX") else s


def _fetch_dnse(symbol: str, start_date: str, end_date: str) -> OhlcvSeries:
    sym = _strip_vn_suffix(symbol)
    endpoint = f"{DNSE_OHLC_BASE}/{'index' if is_vn_index(sym) else 'stock'}"
    params = {
        "from": int(datetime.strptime(start_date, "%Y-%m-%d").timestamp()),
        "to": int(datetime.strptime(end_date, "%Y-%m-%d").timestamp()) + 86399,
        "symbol": _dnse_symbol(sym),
        "resolution": "1D",
    }
    try:
        res = requests.get(endpoint, params=params, timeout=REQUEST_TIMEOUT,
                           headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
        data = res.json() if res.status_code == 200 else {}
    except (requests.RequestException, ValueError) as e:
        logger.warning("DNSE fetch %s lỗi: %s", sym, e)
        return OhlcvSeries(symbol=sym)

    t, h, l, c, v = (data.get(k) or [] for k in ("t", "h", "l", "c", "v"))
    if not t:
        return OhlcvSeries(symbol=sym)

    scale = 1 if is_vn_index(sym) else DNSE_PRICE_SCALE
    bars = []
    for i in range(len(t)):
        try:
            close = float(c[i])
            high = float(h[i]) if i < len(h) and h[i] else close
            low = float(l[i]) if i < len(l) and l[i] else close
            open_ = float(data["o"][i]) if data.get("o") and i < len(data["o"]) and data["o"][i] else close
            vol = float(v[i]) if i < len(v) and v[i] else 0.0
            ts = int(t[i])
        except (IndexError, TypeError, ValueError):
            continue
        if not close > 0:
            continue
        bars.append((ts, open_ * scale, high * scale, low * scale, close * scale, vol))
    bars.sort(key=lambda b: b[0])
    return OhlcvSeries(
        symbol=sym,
        opens=[b[1] for b in bars],
        highs=[b[2] for b in bars],
        lows=[b[3] for b in bars],
        closes=[b[4] for b in bars],
        volumes=[b[5] for b in bars],
        dates=[datetime.fromtimestamp(b[0], tz=timezone.utc).strftime("%Y-%m-%d") for b in bars],
        source="dnse",
    )


def _fetch_vnstock(symbol: str, start_date: str, end_date: str) -> OhlcvSeries:
    sym = _strip_vn_suffix(symbol)
    try:
        from vnstock.explorer.vci import Quote
    except ImportError:
        logger.info("vnstock chưa cài, bỏ qua tầng VCI cho %s", sym)
        return OhlcvSeries(symbol=sym)
    try:
        df = Quote(symbol=sym, show_log=False).history(
            start=start_date, end=end_date, interval="1D"
        )
        if df is None or df.empty:
            return OhlcvSeries(symbol=sym)
        cols = {str(c).strip().lower(): c for c in df.columns}

        def pick(*names):
            return next((cols[n] for n in names if n in cols), None)

        dc, oc, hc, lc, cc, vc = (
            pick("time", "date", "trading_date"), pick("open"), pick("high"),
            pick("low"), pick("close"), pick("volume", "match_volume"),
        )
        if any(x is None for x in (dc, hc, lc, cc)):
            return OhlcvSeries(symbol=sym)
        opens, highs, lows, closes, volumes, dates = [], [], [], [], [], []
        for _, r in df.iterrows():
            try:
                opens.append(float(r[oc]) if oc is not None else float(r[cc]))
                highs.append(float(r[hc]))
                lows.append(float(r[lc]))
                closes.append(float(r[cc]))
                volumes.append(float(r[vc]) if vc is not None else 0.0)
                dates.append(str(r[dc])[:10])
            except (TypeError, ValueError, KeyError):
                continue
        rows = sorted(zip(dates, opens, highs, lows, closes, volumes))
        # VCI trả giá theo nghìn VND cho cổ phiếu nhưng là điểm gốc cho index;
        # nhận diện qua median để không nhầm cổ 2k với index (# VN price scale).
        if rows and not is_vn_index(sym):
            median = sorted(r[4] for r in rows)[len(rows) // 2]
            scale = 1 if median >= 1000 else DNSE_PRICE_SCALE
            if scale > 1:
                rows = [(d, o * scale, h * scale, l * scale, c * scale, v)
                        for d, o, h, l, c, v in rows]
        return OhlcvSeries(
            symbol=sym,
            opens=[r[1] for r in rows], highs=[r[2] for r in rows],
            lows=[r[3] for r in rows], closes=[r[4] for r in rows],
            volumes=[r[5] for r in rows], dates=[r[0] for r in rows],
            source="vnstock-vci",
        )
    except Exception as e:
        logger.warning("vnstock/VCI fetch %s lỗi: %s", sym, e)
        return OhlcvSeries(symbol=sym)


def fetch_vn_ohlcv(symbol: str, start_date: str, end_date: str) -> OhlcvSeries:
    """Chuỗi dự phòng DNSE → vnstock/VCI → TCBS. `source` của series trả về
    cho biết nguồn thắng; 'unavailable' nghĩa là tất cả đều thất bại."""
    for fetch in (_fetch_dnse, _fetch_vnstock):
        series = fetch(symbol, start_date, end_date)
        errors = validate_ohlcv(series)
        if series.source != "unavailable" and not errors:
            return series
        logger.warning("%s unusable cho %s (%s), thử nguồn kế tiếp",
                       series.source, symbol, errors or "empty")
    from .vn_vendor import _fetch_tcbs_ohlcv

    df = _fetch_tcbs_ohlcv(symbol, start_date, end_date)
    if df is None or df.empty:
        return OhlcvSeries(symbol=symbol)
    series = OhlcvSeries(
        symbol=symbol,
        opens=df["Open"].tolist(), highs=df["High"].tolist(),
        lows=df["Low"].tolist(), closes=df["Close"].tolist(),
        volumes=df["Volume"].tolist(),
        dates=[d.strftime("%Y-%m-%d") for d in df.index],
        source="tcbs",
    )
    errors = validate_ohlcv(series)
    if errors:
        logger.warning("tcbs unusable cho %s (%s)", symbol, errors)
        return OhlcvSeries(symbol=symbol)
    return series
