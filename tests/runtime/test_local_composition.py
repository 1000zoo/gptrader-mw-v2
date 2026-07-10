from decimal import Decimal

from src.infrastructure.exchange.binance.market_data import BinanceMarketDataAdapter
from src.infrastructure.exchange.binance.order_execution import BinanceOrderExecutionAdapter
from src.runtime import RuntimeMode, RuntimeSettings, create_local_app, create_local_runtime


def test_local_runtime_reports_health_details() -> None:
    runtime = create_local_runtime(RuntimeSettings(symbol="ETHUSDT"))

    details = runtime.health_details()

    assert details["mode"] == "local"
    assert details["symbol"] == "ETHUSDT"
    assert details["dependencies"][0] == {
        "name": "exchange",
        "status": "local",
        "detail": "external exchange disabled",
    }


def test_local_app_exposes_health_and_readiness_routes() -> None:
    app = create_local_app(RuntimeSettings(symbol="ETHUSDT"))
    health = next(route for route in app.routes if route.path == "/health")
    readiness = next(route for route in app.routes if route.path == "/readiness")
    status = next(route for route in app.routes if route.path == "/status")

    assert health.endpoint()["details"]["symbol"] == "ETHUSDT"
    assert readiness.endpoint()["details"]["ready_for"] == "local"
    assert status.endpoint()["data"]["trade_controls"] == "disabled"
    assert status.endpoint()["data"]["live_order_path"] == "disabled"


def test_local_runtime_can_run_strategy_backtest_cycle() -> None:
    runtime = create_local_runtime(RuntimeSettings(symbol="BTCUSDT"))

    result = runtime.run_strategy_backtest_cycle("cycle-local")

    assert result.succeeded_count == 6
    assert result.failed_count == 0
    assert {item.strategy_id for item in result.items} == {
        "latest-close-moving-average",
        "session-volume-profile",
        "chart-pattern",
        "tv-range-seed-s1-t1-p2-fixed",
        "live-compression-s2-sl0030-rr045-balanced",
        "live-scalp-multi-t1-r1-b4-tbr-sl0050-rr025-p2",
    }
    assert runtime.status_details()["strategy_backtest_cycle"]["succeeded_count"] == 6


def test_local_runtime_can_filter_backtest_strategies() -> None:
    runtime = create_local_runtime(
        RuntimeSettings(
            symbol="BTCUSDT",
            backtest_strategy_ids=("chart-pattern",),
        )
    )

    result = runtime.run_strategy_backtest_cycle("cycle-local")

    assert result.succeeded_count == 1
    assert result.failed_count == 0
    assert [item.strategy_id for item in result.items] == ["chart-pattern"]


def test_live_armed_runtime_uses_seed_combo_and_live_exchange_adapters() -> None:
    runtime = create_local_runtime(
        RuntimeSettings(
            mode=RuntimeMode.LIVE_ARMED,
            live_armed=True,
            trading_strategy_id="tv-range-seed-s1-t1-p2-fixed",
            take_profit_stop_loss="fixed",
            stop_loss_ratio=Decimal("0.09"),
            reward_risk_ratio=Decimal("0.15"),
            position_sizing="fixed",
            fixed_equity_ratio=Decimal("0.10"),
            fixed_leverage=Decimal("15"),
        )
    )

    details = runtime.status_details()

    assert details["trade_controls"] == "enabled"
    assert details["live_order_path"] == "enabled"
    assert details["active_strategy_id"] == "tv-range-seed-s1-t1-p2-fixed"
    assert details["take_profit_stop_loss"] == {
        "kind": "fixed",
        "stop_loss_ratio": "0.09",
        "reward_risk_ratio": "0.15",
    }
    assert details["position_sizing"] == {
        "kind": "fixed",
        "equity_ratio": "0.10",
        "leverage": "15",
    }
    assert isinstance(runtime._market_data, BinanceMarketDataAdapter)
    assert isinstance(runtime._order_execution, BinanceOrderExecutionAdapter)


def test_live_armed_runtime_uses_compression_s2_combo_settings() -> None:
    runtime = create_local_runtime(
        RuntimeSettings(
            mode=RuntimeMode.LIVE_ARMED,
            live_armed=True,
            trading_strategy_id="live-compression-s2-sl0030-rr045-balanced",
            candle_limit=1442,
            take_profit_stop_loss="fixed",
            stop_loss_ratio=Decimal("0.030"),
            reward_risk_ratio=Decimal("0.45"),
            position_sizing="confidence",
            min_equity_ratio=Decimal("0.02"),
            max_equity_ratio=Decimal("0.14"),
            min_leverage=Decimal("1"),
            max_leverage=Decimal("8"),
        )
    )

    details = runtime.status_details()

    assert details["active_strategy_id"] == "live-compression-s2-sl0030-rr045-balanced"
    assert details["take_profit_stop_loss"] == {
        "kind": "fixed",
        "stop_loss_ratio": "0.030",
        "reward_risk_ratio": "0.45",
    }
    assert details["position_sizing"] == {
        "kind": "confidence",
        "min_equity_ratio": "0.02",
        "max_equity_ratio": "0.14",
        "min_leverage": "1",
        "max_leverage": "8",
    }
