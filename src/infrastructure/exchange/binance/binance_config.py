import os
from dataclasses import dataclass


BINANCE_USDM_FUTURES_BASE_URL = "https://fapi.binance.com"
BINANCE_USDM_FUTURES_TESTNET_BASE_URL = "https://demo-fapi.binance.com"


@dataclass(frozen=True)
class BinanceConfig:
    api_key: str | None = None
    api_secret: str | None = None
    base_url: str = BINANCE_USDM_FUTURES_BASE_URL
    timeout: float = 10.0
    recv_window: int = 5000
    retry_attempts: int = 1
    retry_delay: float = 0.0

    @classmethod
    def default(cls) -> "BinanceConfig":
        return cls()

    @classmethod
    def from_env(cls) -> "BinanceConfig":
        testnet_enabled = _env_flag_enabled("BINANCE_TESTNET")
        if testnet_enabled:
            base_url = (
                os.getenv("BINANCE_TEST_BASE_URL")
                or BINANCE_USDM_FUTURES_TESTNET_BASE_URL
            )
        else:
            base_url = os.getenv("BINANCE_BASE_URL") or cls.base_url
        api_key = (
            os.getenv("BINANCE_TEST_API_KEY")
            if testnet_enabled
            else os.getenv("BINANCE_API_KEY")
        )
        api_secret = (
            os.getenv("BINANCE_TEST_API_SECRET")
            if testnet_enabled
            else os.getenv("BINANCE_API_SECRET")
        )
        return cls(
            api_key=api_key,
            api_secret=api_secret,
            base_url=base_url,
            timeout=float(os.getenv("BINANCE_TIMEOUT", str(cls.timeout))),
            recv_window=int(os.getenv("BINANCE_RECV_WINDOW", str(cls.recv_window))),
            retry_attempts=int(
                os.getenv("BINANCE_RETRY_ATTEMPTS", str(cls.retry_attempts))
            ),
            retry_delay=float(os.getenv("BINANCE_RETRY_DELAY", str(cls.retry_delay))),
        )


def _env_flag_enabled(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}
