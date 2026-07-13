from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Mapping


class RuntimeMode(Enum):
    LOCAL = "local"
    DRY_RUN = "dry-run"
    TESTNET = "testnet"
    LIVE_ARMED = "live-armed"


def _value(env: Mapping[str, str], name: str, default: str) -> str:
    value = env.get(name, default)
    return value.strip() if isinstance(value, str) else default


@dataclass(frozen=True)
class RuntimeSettings:
    mode: RuntimeMode = RuntimeMode.LOCAL
    live_armed: bool = False
    symbol: str = "BTCUSDT"
    timeframe: str = "1m"
    candle_limit: int = 100
    client_order_id_prefix: str = "gptrader-local"
    generator_id: str = "local-generator"
    signal_id_prefix: str = "local-signal"
    database_url: str = "sqlite:///./gptrader-local.sqlite3"
    trading_strategy_id: str = "latest-close-moving-average"
    backtest_strategy_ids: tuple[str, ...] = ()
    disabled_backtest_strategy_ids: tuple[str, ...] = ()
    take_profit_stop_loss: str = "atr"
    stop_loss_ratio: Decimal = Decimal("0.003")
    reward_risk_ratio: Decimal = Decimal("2")
    position_sizing: str = "confidence"
    min_equity_ratio: Decimal = Decimal("0.01")
    max_equity_ratio: Decimal = Decimal("0.10")
    min_leverage: Decimal = Decimal("1")
    max_leverage: Decimal = Decimal("5")
    fixed_equity_ratio: Decimal = Decimal("0.01")
    fixed_leverage: Decimal = Decimal("1")

    def __post_init__(self) -> None:
        if self.mode is RuntimeMode.LIVE_ARMED and not self.live_armed:
            raise ValueError("live-armed mode requires GPTRADER_LIVE_ARMED=true")
        if not self.symbol.strip():
            raise ValueError("symbol is required")
        if not self.timeframe.strip():
            raise ValueError("timeframe is required")
        if self.candle_limit <= 0:
            raise ValueError("candle_limit must be positive")
        if not self.client_order_id_prefix.strip():
            raise ValueError("client_order_id_prefix is required")
        if not self.generator_id.strip():
            raise ValueError("generator_id is required")
        if not self.signal_id_prefix.strip():
            raise ValueError("signal_id_prefix is required")
        if not self.database_url.strip():
            raise ValueError("database_url is required")
        if not self.trading_strategy_id.strip():
            raise ValueError("trading_strategy_id is required")
        if self.take_profit_stop_loss not in {"atr", "fixed"}:
            raise ValueError("take_profit_stop_loss must be atr or fixed")
        if self.stop_loss_ratio <= Decimal("0"):
            raise ValueError("stop_loss_ratio must be positive")
        if self.reward_risk_ratio <= Decimal("0"):
            raise ValueError("reward_risk_ratio must be positive")
        if self.position_sizing not in {"confidence", "fixed"}:
            raise ValueError("position_sizing must be confidence or fixed")
        if self.min_equity_ratio <= Decimal("0"):
            raise ValueError("min_equity_ratio must be positive")
        if self.max_equity_ratio < self.min_equity_ratio:
            raise ValueError("max_equity_ratio must be greater than or equal to min_equity_ratio")
        if self.min_leverage <= Decimal("0"):
            raise ValueError("min_leverage must be positive")
        if self.max_leverage < self.min_leverage:
            raise ValueError("max_leverage must be greater than or equal to min_leverage")
        if self.max_leverage > Decimal("15"):
            raise ValueError("max_leverage cannot exceed 15")
        if self.fixed_equity_ratio <= Decimal("0"):
            raise ValueError("fixed_equity_ratio must be positive")
        if self.fixed_leverage <= Decimal("0"):
            raise ValueError("fixed_leverage must be positive")
        if self.fixed_leverage > Decimal("15"):
            raise ValueError("fixed_leverage cannot exceed 15")
        object.__setattr__(
            self,
            "backtest_strategy_ids",
            _csv_ids(self.backtest_strategy_ids),
        )
        object.__setattr__(
            self,
            "disabled_backtest_strategy_ids",
            _csv_ids(self.disabled_backtest_strategy_ids),
        )

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "RuntimeSettings":
        mode = RuntimeMode(_value(env, "GPTRADER_MODE", RuntimeMode.LOCAL.value))
        live_armed = _value(env, "GPTRADER_LIVE_ARMED", "false").lower() == "true"
        _validate_mode_environment(mode, env, live_armed=live_armed)
        return cls(
            mode=mode,
            live_armed=live_armed,
            symbol=_value(env, "GPTRADER_SYMBOL", "BTCUSDT"),
            timeframe=_value(env, "GPTRADER_TIMEFRAME", "1m"),
            candle_limit=int(_value(env, "GPTRADER_CANDLE_LIMIT", "100")),
            client_order_id_prefix=_value(
                env,
                "GPTRADER_CLIENT_ORDER_ID_PREFIX",
                "gptrader-local",
            ),
            generator_id=_value(env, "GPTRADER_GENERATOR_ID", "local-generator"),
            signal_id_prefix=_value(env, "GPTRADER_SIGNAL_ID_PREFIX", "local-signal"),
            database_url=_value(
                env,
                "GPTRADER_DB_URL",
                "sqlite:///./gptrader-local.sqlite3",
            ),
            trading_strategy_id=_value(
                env,
                "GPTRADER_TRADING_STRATEGY_ID",
                "latest-close-moving-average",
            ),
            backtest_strategy_ids=_csv_ids(
                _value(env, "GPTRADER_BACKTEST_STRATEGY_IDS", "")
            ),
            disabled_backtest_strategy_ids=_csv_ids(
                _value(env, "GPTRADER_DISABLED_BACKTEST_STRATEGY_IDS", "")
            ),
            take_profit_stop_loss=_value(
                env,
                "GPTRADER_TAKE_PROFIT_STOP_LOSS",
                "atr",
            ),
            stop_loss_ratio=Decimal(_value(env, "GPTRADER_STOP_LOSS_RATIO", "0.003")),
            reward_risk_ratio=Decimal(
                _value(env, "GPTRADER_REWARD_RISK_RATIO", "2")
            ),
            position_sizing=_value(env, "GPTRADER_POSITION_SIZING", "confidence"),
            min_equity_ratio=Decimal(
                _value(env, "GPTRADER_MIN_EQUITY_RATIO", "0.01")
            ),
            max_equity_ratio=Decimal(
                _value(env, "GPTRADER_MAX_EQUITY_RATIO", "0.10")
            ),
            min_leverage=Decimal(_value(env, "GPTRADER_MIN_LEVERAGE", "1")),
            max_leverage=Decimal(_value(env, "GPTRADER_MAX_LEVERAGE", "5")),
            fixed_equity_ratio=Decimal(
                _value(env, "GPTRADER_FIXED_EQUITY_RATIO", "0.01")
            ),
            fixed_leverage=Decimal(_value(env, "GPTRADER_FIXED_LEVERAGE", "1")),
        )


def _validate_mode_environment(
    mode: RuntimeMode,
    env: Mapping[str, str],
    *,
    live_armed: bool,
) -> None:
    if mode is RuntimeMode.TESTNET:
        _require_env(env, "BINANCE_TEST_API_KEY")
        _require_env(env, "BINANCE_TEST_API_SECRET")
    if mode is RuntimeMode.LIVE_ARMED and live_armed:
        _require_env(env, "BINANCE_API_KEY")
        _require_env(env, "BINANCE_API_SECRET")


def _require_env(env: Mapping[str, str], name: str) -> None:
    if not _value(env, name, ""):
        raise ValueError(f"{name} is required for selected runtime mode")


def _csv_ids(value: str | tuple[str, ...]) -> tuple[str, ...]:
    if isinstance(value, tuple):
        items = value
    else:
        items = tuple(value.split(","))
    normalized = tuple(item.strip() for item in items if item.strip())
    if len(set(normalized)) != len(normalized):
        raise ValueError("strategy ids must be unique")
    return normalized
