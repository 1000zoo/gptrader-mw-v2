import os
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel
from loguru import logger

from src.common.db.connection import SessionLocal
from src.ops.service.system_state.system_state_service import SystemStateService
from src.trade.service.trade_fill.trade_fill_service import TradeFillService
from src.calibration.calibration_service import CalibrationService

router = APIRouter(prefix="/ops")


class OpsStateResponse(BaseModel):
    trading_enabled: bool
    reason: Optional[str] = None
    since_ts: Optional[datetime] = None
    updated_by: Optional[str] = None


class OpsStateRequest(BaseModel):
    reason: Optional[str] = None


@router.get("/state", response_model=OpsStateResponse)
async def get_state():
    svc = SystemStateService()
    state = await svc.find_latest_state()
    if not state:
        return OpsStateResponse(trading_enabled=True)
    return OpsStateResponse(
        trading_enabled=bool(state.trading_enabled),
        reason=state.reason,
        since_ts=state.since_ts,
        updated_by=state.updated_by,
    )


def _validate_ops_token(token: Optional[str]) -> None:
    expected = os.getenv("OPS_TOKEN")
    if not expected or not token or token != expected:
        raise HTTPException(status_code=403, detail="Forbidden")


@router.post("/state/enable", response_model=OpsStateResponse)
async def enable_state(
    payload: OpsStateRequest, x_ops_token: Optional[str] = Header(default=None)
):
    _validate_ops_token(x_ops_token)
    svc = SystemStateService()
    await svc.enable_trading(reason=payload.reason, updated_by="manual")
    logger.bind(
        run_id=None,
        symbol=None,
        timeframe=None,
        action_id=None,
        job_id=None,
        order_id=None,
        signal_log_id=None,
    ).info("manual enable state")
    return OpsStateResponse(trading_enabled=True, reason=payload.reason, updated_by="manual")


@router.post("/state/disable", response_model=OpsStateResponse)
async def disable_state(
    payload: OpsStateRequest, x_ops_token: Optional[str] = Header(default=None)
):
    _validate_ops_token(x_ops_token)
    svc = SystemStateService()
    await svc.disable_trading(reason=payload.reason, updated_by="manual")
    logger.bind(
        run_id=None,
        symbol=None,
        timeframe=None,
        action_id=None,
        job_id=None,
        order_id=None,
        signal_log_id=None,
    ).info("manual disable state")
    return OpsStateResponse(trading_enabled=False, reason=payload.reason, updated_by="manual")


@router.get("/health")
async def health_check():
    db_ok = False
    async with SessionLocal() as session:
        result = await session.execute("SELECT 1")
        db_ok = result.scalar_one_or_none() == 1
    return {
        "status": "ok" if db_ok else "degraded",
        "db": db_ok,
        "openai": "skipped",
        "binance": "skipped",
    }


@router.get("/performance")
async def performance(c_interval: str = "1h", symbol_id: Optional[str] = None):
    trade_service = TradeFillService()
    calibration_service = CalibrationService()
    trades = await trade_service.find_recent_closed_trades(30)
    pnl_usd = sum(float(t.pnl_usd or 0) for t in trades)
    wins = sum(1 for t in trades if (t.pnl_usd or 0) > 0)
    winrate = wins / len(trades) if trades else 0.0
    avg_r = sum(float(t.r_multiple or 0) for t in trades) / len(trades) if trades else 0.0
    gross_profit = sum(float(t.pnl_usd or 0) for t in trades if (t.pnl_usd or 0) > 0)
    gross_loss = abs(sum(float(t.pnl_usd or 0) for t in trades if (t.pnl_usd or 0) < 0))
    pf = gross_profit / gross_loss if gross_loss > 0 else 0.0
    calibration = await calibration_service.compute_bucket_stats(c_interval, symbol_id)
    return {
        "window": len(trades),
        "pnl_usd": pnl_usd,
        "winrate": winrate,
        "avg_r": avg_r,
        "pf": pf,
        "calibration": [
            {
                "bucket_from": stat.bucket_from,
                "bucket_to": stat.bucket_to,
                "trades": stat.trades,
                "winrate": stat.winrate,
                "ev": stat.ev,
                "avg_r": stat.avg_r,
                "pf": stat.pf,
            }
            for stat in calibration
        ],
    }
