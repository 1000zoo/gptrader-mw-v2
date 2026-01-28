from datetime import datetime

import pytest

pydantic = pytest.importorskip("pydantic")

from src.signal.vo.signal_log.default import DefaultSignalLogVo
from src.trade.vo.trade_fill.default import DefaultTradeFillVo
from src.ops.vo.system_state.default import DefaultSystemStateVo
from src.calibration.vo.confidence_calibration.default import DefaultConfidenceCalibrationVo
from src.research.vo.backtest_result.default import DefaultBacktestResultVo
from src.ops.vo.execution_anomaly.default import DefaultExecutionAnomalyVo


def test_signal_log_vo_fields():
    ts = datetime.utcnow()
    vo = DefaultSignalLogVo(symbol_id="BTCUSDT", c_interval="1h", base_ts=ts)
    assert vo.symbol_id == "BTCUSDT"
    assert vo.c_interval == "1h"
    assert vo.base_ts == ts


def test_supporting_vo_models_round_trip():
    trade_fill = DefaultTradeFillVo(symbol_id="ETHUSDT", status="OPEN")
    system_state = DefaultSystemStateVo(trading_enabled=True, updated_by="system")
    calibration = DefaultConfidenceCalibrationVo(c_interval="1h", bucket_from=0.1, bucket_to=0.2)
    backtest = DefaultBacktestResultVo(trades=10, winrate=0.6)
    anomaly = DefaultExecutionAnomalyVo(anomaly_type="SLIPPAGE", severity="HIGH")

    assert trade_fill.status == "OPEN"
    assert system_state.trading_enabled is True
    assert calibration.bucket_from == 0.1
    assert backtest.trades == 10
    assert anomaly.severity == "HIGH"
