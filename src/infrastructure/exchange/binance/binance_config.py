import os
from dataclasses import dataclass


BINANCE_USDM_FUTURES_BASE_URL = "https://fapi.binance.com"
BINANCE_USDM_FUTURES_TESTNET_BASE_URL = "https://testnet.binancefuture.com"


@dataclass(frozen=True)
class BinanceConfig:
    api_key: str | None = None
    api_secret: str | None = None
    base_url: str = BINANCE_USDM_FUTURES_BASE_URL
    timeout: float = 10.0
    recv_window: int = 5000

    @classmethod
    def default(cls) -> "BinanceConfig":
        return cls()

    @classmethod
    def from_env(cls) -> "BinanceConfig":
        base_url = os.getenv("BINANCE_BASE_URL")
        if base_url is None and _env_flag_enabled("BINANCE_TESTNET"):
            base_url = BINANCE_USDM_FUTURES_TESTNET_BASE_URL
        return cls(
            api_key=os.getenv("BINANCE_API_KEY"),
            api_secret=os.getenv("BINANCE_API_SECRET"),
            base_url=base_url or cls.base_url,
            timeout=float(os.getenv("BINANCE_TIMEOUT", str(cls.timeout))),
            recv_window=int(os.getenv("BINANCE_RECV_WINDOW", str(cls.recv_window))),
        )


def _env_flag_enabled(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}
