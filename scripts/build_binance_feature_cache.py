from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from datetime import datetime, time, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.infrastructure.exchange.binance.research_data import (
    DEFAULT_AGGTRADES_MAX_BYTES,
    DEFAULT_CACHE_ROOT,
    SUPPORTED_SOURCES,
    HistoricalFeatureLoader,
)
from src.infrastructure.exchange.binance.research_data.historical_feature_loader import validate_cache_pair


SOURCE_ALIASES = {
    "mark": "markPriceKlines",
    "index": "indexPriceKlines",
    "premium": "premiumIndexKlines",
    "funding": "fundingRate",
}


def _datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid ISO date/time: {value}") from exc
    if parsed.tzinfo is None and len(value) == 10:
        parsed = datetime.combine(parsed.date(), time.min, tzinfo=timezone.utc)
    elif parsed.tzinfo is None:
        raise argparse.ArgumentTypeError(
            "datetime values with a time must include a timezone offset"
        )
    return parsed.astimezone(timezone.utc)


def _sources(value: str) -> tuple[str, ...]:
    result = tuple(
        SOURCE_ALIASES.get(item, item)
        for item in (part.strip() for part in value.split(","))
        if item
    )
    unknown = [source for source in result if source not in SUPPORTED_SOURCES]
    if not result or unknown:
        expected = ",".join(SUPPORTED_SOURCES)
        raise argparse.ArgumentTypeError(f"sources must be a comma list drawn from {expected}")
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build compact Binance USD-M research features")
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--start", required=True, type=_datetime)
    parser.add_argument("--end", required=True, type=_datetime)
    parser.add_argument("--sources", required=True, type=_sources)
    parser.add_argument("--cache-root", type=Path, default=DEFAULT_CACHE_ROOT)
    parser.add_argument(
        "--aggtrades-max-bytes",
        type=_positive_int,
        default=DEFAULT_AGGTRADES_MAX_BYTES,
    )
    return parser


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be positive")
    return parsed


def main(
    argv: Sequence[str] | None = None,
    *,
    loader_factory: Callable[..., HistoricalFeatureLoader] = HistoricalFeatureLoader,
) -> int:
    args = build_parser().parse_args(argv)
    loader = loader_factory(
        cache_root=args.cache_root,
        aggtrades_max_bytes=args.aggtrades_max_bytes,
    )
    jsonl_path, manifest_path = loader.build_cache(
        symbol=args.symbol.upper(),
        start=args.start,
        end=args.end,
        sources=args.sources,
    )
    if not validate_cache_pair(jsonl_path, manifest_path):
        raise RuntimeError("Binance feature cache publication is incomplete or corrupt")
    print(jsonl_path)
    print(manifest_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
