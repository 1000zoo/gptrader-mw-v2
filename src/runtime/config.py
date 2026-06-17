from dataclasses import dataclass
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
