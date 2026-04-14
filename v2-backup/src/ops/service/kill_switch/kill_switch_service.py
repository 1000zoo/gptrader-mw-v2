import os
from datetime import datetime, timezone

from loguru import logger

from src.ops.service.alert.alert_service import AlertService
from src.ops.service.execution_anomaly.execution_anomaly_service import ExecutionAnomalyService
from src.ops.service.system_state.system_state_service import SystemStateService
from src.ops.vo.system_state.default import DefaultSystemStateVo
from src.trade.service.trade_fill.trade_fill_service import TradeFillService


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.lower() == "true"


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


class KillSwitchService:
    def __init__(self):
        self.enabled = _env_bool("ENABLE_KILL_SWITCH", False)
        self.window_n = _env_int("KILL_EV_WINDOW_N", 30)
        self.ev_threshold = _env_float("KILL_EV_THRESHOLD", -0.01)
        self.mdd_threshold_pct = _env_float("KILL_MDD_THRESHOLD_PCT", 0.1)
        self.anomaly_rate_threshold = _env_float("KILL_ANOMALY_RATE", 0.2)

        self.trade_fill_service = TradeFillService()
        self.execution_anomaly_service = ExecutionAnomalyService()
        self.system_state_service = SystemStateService()
        self.alert_service = AlertService()

    @staticmethod
    def _compute_mdd(pnls: list[float]) -> float:
        equity = 0.0
        peak = 0.0
        max_drawdown = 0.0
        for pnl in pnls:
            equity += pnl
            if equity > peak:
                peak = equity
            drawdown = peak - equity
            if peak > 0:
                max_drawdown = max(max_drawdown, drawdown / peak)
        return max_drawdown

    async def evaluate_and_update(self) -> bool:
        if not self.enabled:
            return True

        latest_state = await self.system_state_service.find_latest_state()
        if latest_state and latest_state.trading_enabled is False:
            return False

        trades = await self.trade_fill_service.find_recent_closed_trades(self.window_n)
        if not trades:
            return True

        pnls = [float(t.pnl_usd or 0) for t in reversed(trades)]
        r_values = [float(t.r_multiple or 0) for t in trades if t.r_multiple is not None]
        ev = sum(r_values) / len(r_values) if r_values else 0.0
        mdd = self._compute_mdd(pnls)

        since_ts = trades[-1].exit_ts if trades[-1].exit_ts else datetime.now(timezone.utc)
        anomalies = await self.execution_anomaly_service.count_recent_anomalies(since_ts)
        anomaly_rate = anomalies / max(1, len(trades))

        reasons = []
        if ev < self.ev_threshold:
            reasons.append(f"ev_below_threshold={ev:.4f}")
        if mdd > self.mdd_threshold_pct:
            reasons.append(f"mdd_above_threshold={mdd:.4f}")
        if anomaly_rate > self.anomaly_rate_threshold:
            reasons.append(f"anomaly_rate={anomaly_rate:.4f}")

        if not reasons:
            return True

        reason_text = "; ".join(reasons)
        logger.bind(
            run_id=None,
            symbol=None,
            timeframe=None,
            action_id=None,
            job_id=None,
            order_id=None,
            signal_log_id=None,
        ).warning(f"kill_switch triggered: {reason_text}")

        await self.system_state_service.create_system_state(
            DefaultSystemStateVo(
                trading_enabled=False,
                reason=reason_text,
                since_ts=datetime.now(timezone.utc),
                updated_by="kill_switch",
            )
        )
        self.alert_service.send_slack_alert(f"Kill switch triggered: {reason_text}")
        return False
