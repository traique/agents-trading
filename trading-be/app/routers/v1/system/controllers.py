"""System diagnostics endpoints (lấy cảm hứng từ ``augur doctor``).

- ``/system/data-health``: sức khỏe chuỗi nguồn dữ liệu VN (DNSE/VCI/TCBS)
  từ provider-health stats + thống kê vòng tự học từ rolling_ic.json.
- ``/system/data-health/probe``: chủ động probe từng nguồn một ngay lúc đó
  (không đụng cache), cho nút "Kiểm tra ngay" trên UI.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends

from app.dependencies.auth import get_current_user
from app.routers.v1.auth.models.relational import User

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/data-health", summary="Data source health + learning stats")
async def get_data_health(current_user: User = Depends(get_current_user)):
    from tradingagents.dataflows.provider_health import get_provider_health
    from tradingagents.consensus import load_rolling_ic
    from tradingagents.default_config import DEFAULT_CONFIG

    return {
        "sources": get_provider_health(DEFAULT_CONFIG.get("data_cache_dir")),
        "learning": load_rolling_ic(DEFAULT_CONFIG.get("data_cache_dir")),
        "generated_at": datetime.now().isoformat(),
    }


@router.post("/data-health/probe", summary="Probe every VN data source now")
async def probe_data_sources(current_user: User = Depends(get_current_user)):
    """Chủ động probe cả ba nguồn.

    Các hàm fetch dùng ``requests`` (sync, timeout=10s/nguồn) nên phải chạy
    trong thread qua ``asyncio.to_thread`` — gọi trực tiếp trong async def
    sẽ block toàn bộ event loop tới ~30s khi nguồn chết.
    """
    import asyncio

    from tradingagents.dataflows.provider_health import record_provider_probe
    from tradingagents.dataflows.vn_ohlcv import (
        _fetch_dnse,
        _fetch_vnstock,
        validate_ohlcv,
    )
    from tradingagents.dataflows.vn_vendor import _fetch_tcbs_ohlcv

    end = datetime.now()
    start = end - timedelta(days=30)
    start_s, end_s = start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")
    symbol = "VCB"  # thanh khoản cao, mọi nguồn đều có

    results = {}

    async def probe_source(name: str, fetch) -> None:
        try:
            series = await asyncio.to_thread(fetch, symbol, start_s, end_s)
            errors = validate_ohlcv(series)
            ok = series.source != "unavailable" and not errors
            record_provider_probe(name, ok, detail="; ".join(errors or []), symbol=symbol)
            results[name] = {
                "ok": ok,
                "bars": len(series.closes),
                "last_bar": series.dates[-1] if series.dates else None,
                "errors": errors or [],
            }
        except Exception as e:
            record_provider_probe(name, False, detail=str(e), symbol=symbol)
            results[name] = {"ok": False, "error": str(e)[:200]}

    await asyncio.gather(
        probe_source("dnse", _fetch_dnse),
        probe_source("vnstock-vci", _fetch_vnstock),
    )

    try:
        df = await asyncio.to_thread(_fetch_tcbs_ohlcv, symbol, start_s, end_s)
        ok = df is not None and not df.empty
        record_provider_probe("tcbs", ok, detail="" if ok else "empty", symbol=symbol)
        results["tcbs"] = {
            "ok": ok,
            "bars": len(df) if ok else 0,
            "last_bar": df.index[-1].strftime("%Y-%m-%d") if ok else None,
        }
    except Exception as e:
        record_provider_probe("tcbs", False, detail=str(e), symbol=symbol)
        results["tcbs"] = {"ok": False, "error": str(e)[:200]}

    return {"symbol": symbol, "results": results, "probed_at": datetime.now().isoformat()}
