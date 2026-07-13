from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import time
import uuid
import zipfile
from contextlib import contextmanager
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import BinaryIO
from urllib.error import HTTPError
from urllib.request import urlopen

from src.domain.market import Symbol, Timeframe
from src.domain.market_feature import MarketFeatureSet, MarketFeatureValue
from src.infrastructure.exchange.binance.binance_config import BinanceConfig
from src.infrastructure.exchange.binance.binance_rest import request_json


UTC = timezone.utc
ONE_MINUTE = timedelta(minutes=1)
FUNDING_MAX_AGE = timedelta(hours=8)
METRICS_MAX_AGE = timedelta(minutes=5)
ARCHIVE_BASE_URL = "https://data.binance.vision"
DEFAULT_CACHE_ROOT = Path(".research-data/binance-usdm")
DEFAULT_AGGTRADES_MAX_BYTES = 1_000_000_000
DEFAULT_FUNDING_MAX_PAGES = 10_000
FEATURE_CACHE_SCHEMA_VERSION = "binance-usdm-market-features-v1"
SUPPORTED_SOURCES = (
    "klines",
    "aggTrades",
    "markPriceKlines",
    "indexPriceKlines",
    "premiumIndexKlines",
    "fundingRate",
    "metrics",
)

_KLINE_SOURCES = {
    "klines",
    "markPriceKlines",
    "indexPriceKlines",
    "premiumIndexKlines",
}
_PRICE_FEATURES = {
    "markPriceKlines": "mark_price",
    "indexPriceKlines": "index_price",
    "premiumIndexKlines": "premium_index",
}
_EXPECTED_HEADERS = {
    "klines": (
        "open_time", "open", "high", "low", "close", "volume", "close_time",
        "quote_volume", "count", "taker_buy_volume", "taker_buy_quote_volume", "ignore",
    ),
    "aggTrades": (
        "agg_trade_id", "price", "quantity", "first_trade_id", "last_trade_id",
        "transact_time", "is_buyer_maker",
    ),
    "fundingRate": ("calc_time", "funding_interval_hours", "last_funding_rate"),
    "metrics": (
        "create_time",
        "symbol",
        "sum_open_interest",
        "sum_open_interest_value",
        "count_toptrader_long_short_ratio",
        "sum_toptrader_long_short_ratio",
        "count_long_short_ratio",
        "sum_taker_long_short_vol_ratio",
    ),
}
for _price_source in _PRICE_FEATURES:
    _EXPECTED_HEADERS[_price_source] = _EXPECTED_HEADERS["klines"]


class ChecksumMismatchError(RuntimeError):
    pass


@dataclass(frozen=True)
class ArchiveRequest:
    source: str
    symbol: str
    granularity: str
    period: str
    url: str

    @property
    def filename(self) -> str:
        return self.url.rsplit("/", 1)[-1]


@dataclass(frozen=True)
class DownloadResult:
    status: str
    path: Path
    sha256: str | None = None
    bytes_received: int = 0


@dataclass(frozen=True)
class FeatureRow:
    minute_end: datetime
    available_at: datetime
    source: str
    features: Mapping[str, Decimal]

    def __post_init__(self) -> None:
        minute_end = _as_utc(self.minute_end)
        available_at = _as_utc(self.available_at)
        if self.source not in SUPPORTED_SOURCES:
            raise ValueError(f"unsupported Binance research source: {self.source}")
        features = dict(self.features)
        if any(not isinstance(value, Decimal) or not value.is_finite() for value in features.values()):
            raise ValueError("feature values must be finite Decimal instances")
        object.__setattr__(self, "minute_end", minute_end)
        object.__setattr__(self, "available_at", available_at)
        object.__setattr__(self, "features", features)


@dataclass(frozen=True)
class _FeatureWriteSummary:
    output_hash: str
    row_count: int
    minimum: datetime | None
    maximum: datetime | None
    available_rows: Mapping[str, int]


def archive_url(
    source: str,
    symbol: str,
    period: str,
    granularity: str,
    *,
    base_url: str = ARCHIVE_BASE_URL,
) -> str:
    _require_source(source)
    if granularity not in {"monthly", "daily"}:
        raise ValueError("archive granularity must be monthly or daily")
    if source == "fundingRate" and granularity != "monthly":
        raise ValueError("fundingRate archives are monthly only")
    if source == "metrics" and granularity != "daily":
        raise ValueError("metrics archives are daily only")
    symbol = _normalize_symbol(symbol)
    filename = (
        f"{symbol}-1m-{period}.zip"
        if source in _KLINE_SOURCES
        else f"{symbol}-{source}-{period}.zip"
    )
    interval = "/1m" if source in _KLINE_SOURCES else ""
    return (
        f"{base_url.rstrip('/')}/data/futures/um/{granularity}/{source}/"
        f"{symbol}{interval}/{filename}"
    )


def iter_archive_requests(
    source: str,
    symbol: str,
    start: datetime,
    end: datetime,
    *,
    now: datetime | None = None,
) -> Iterator[ArchiveRequest]:
    _require_source(source)
    start = _as_utc(start)
    end = _as_utc(end)
    now = _as_utc(now or datetime.now(UTC))
    if start >= end:
        raise ValueError("start must be before end")

    if source == "metrics":
        day = start.date()
        last_day = min(end.date(), now.date())
        while day < last_day:
            period = day.isoformat()
            yield ArchiveRequest(
                source,
                _normalize_symbol(symbol),
                "daily",
                period,
                archive_url(source, symbol, period, "daily"),
            )
            day += timedelta(days=1)
        return

    current_month = _month_start(now)
    month = _month_start(start)
    while month < end:
        next_month = _next_month(month)
        if month < current_month:
            period = month.strftime("%Y-%m")
            yield ArchiveRequest(
                source,
                _normalize_symbol(symbol),
                "monthly",
                period,
                archive_url(source, symbol, period, "monthly"),
            )
        elif source != "fundingRate":
            day = max(start.date(), month.date())
            last_day = min(end.date(), now.date())
            while day < last_day:
                period = day.isoformat()
                yield ArchiveRequest(
                    source,
                    _normalize_symbol(symbol),
                    "daily",
                    period,
                    archive_url(source, symbol, period, "daily"),
                )
                day += timedelta(days=1)
        month = next_month


class ArchiveDownloader:
    def __init__(
        self,
        *,
        opener: Callable[..., BinaryIO] = urlopen,
        timeout: float = 30.0,
        chunk_size: int = 1024 * 1024,
    ) -> None:
        self._opener = opener
        self._timeout = timeout
        self._chunk_size = chunk_size

    def download(
        self,
        url: str,
        destination: Path,
        *,
        source: str | None = None,
        max_bytes: int | None = None,
    ) -> DownloadResult:
        destination = Path(destination)
        if max_bytes is not None and max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        if destination.exists():
            existing_size = destination.stat().st_size
            if max_bytes is not None and existing_size > max_bytes:
                return DownloadResult(
                    "budget_skipped", destination, bytes_received=existing_size
                )
            expected = self._fetch_checksum(url + ".CHECKSUM", destination.name)
            existing_hash = _sha256_file(destination)
            if existing_hash.lower() == expected.lower():
                if source is not None:
                    validate_archive(
                        destination,
                        source=source,
                        expected_archive_filename=destination.name,
                    )
                return DownloadResult(
                    "cached", destination, existing_hash, existing_size
                )
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = _unique_temp_path(destination)
        digest = hashlib.sha256()
        try:
            try:
                with self._opener(url, timeout=self._timeout) as response:
                    content_length = _response_content_length(response)
                    if max_bytes is not None and (
                        content_length is not None and content_length > max_bytes
                    ):
                        return DownloadResult(
                            "budget_skipped",
                            destination,
                            bytes_received=content_length,
                        )
                    bytes_received = 0
                    output = temporary.open("wb")
                    try:
                        while chunk := response.read(self._chunk_size):
                            bytes_received += len(chunk)
                            if max_bytes is not None and bytes_received > max_bytes:
                                output.close()
                                temporary.unlink(missing_ok=True)
                                return DownloadResult(
                                    "budget_skipped",
                                    destination,
                                    bytes_received=bytes_received,
                                )
                            output.write(chunk)
                            digest.update(chunk)
                        output.flush()
                        os.fsync(output.fileno())
                    finally:
                        if not output.closed:
                            output.close()
            except HTTPError as exc:
                if exc.code == 404:
                    temporary.unlink(missing_ok=True)
                    return DownloadResult("unavailable", destination)
                raise

            expected = self._fetch_checksum(url + ".CHECKSUM", destination.name)
            actual = digest.hexdigest()
            if actual.lower() != expected.lower():
                raise ChecksumMismatchError(
                    f"SHA-256 mismatch for {destination.name}: expected {expected}, got {actual}"
                )
            if source is not None:
                validate_archive(
                    temporary,
                    source=source,
                    expected_archive_filename=destination.name,
                )
            os.replace(temporary, destination)
            return DownloadResult(
                "downloaded", destination, actual, bytes_received
            )
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise

    def _fetch_checksum(self, url: str, filename: str) -> str:
        try:
            with self._opener(url, timeout=self._timeout) as response:
                body = response.read(4096).decode("ascii")
        except HTTPError as exc:
            if exc.code == 404:
                raise RuntimeError(f"checksum unavailable for {filename}") from exc
            raise
        parts = body.strip().split()
        if len(parts) != 2 or len(parts[0]) != 64:
            raise ValueError(f"invalid checksum response for {filename}")
        try:
            int(parts[0], 16)
        except ValueError as exc:
            raise ValueError(f"invalid checksum response for {filename}") from exc
        if parts[1].lstrip("*") != filename:
            raise ValueError(f"checksum filename does not match {filename}")
        return parts[0]


def iter_zip_csv_rows(path: Path) -> Iterator[list[str]]:
    with zipfile.ZipFile(path) as archive:
        members = [item for item in archive.infolist() if not item.is_dir()]
        if len(members) != 1 or not members[0].filename.lower().endswith(".csv"):
            raise ValueError(f"archive must contain exactly one CSV file: {path}")
        with archive.open(members[0]) as raw, io.TextIOWrapper(raw, encoding="utf-8-sig", newline="") as text:
            rows = csv.reader(text)
            first = next(rows, None)
            if first is None:
                return
            if not _looks_like_header(first):
                yield first
            yield from rows


def validate_archive(
    path: Path,
    *,
    source: str,
    expected_archive_filename: str | None = None,
) -> None:
    _require_source(source)
    archive_filename = expected_archive_filename or Path(path).name
    expected_member = archive_filename.removesuffix(".zip") + ".csv"
    try:
        with zipfile.ZipFile(path) as archive:
            members = [item for item in archive.infolist() if not item.is_dir()]
            if len(members) != 1 or members[0].filename != expected_member:
                actual = [item.filename for item in members]
                raise ValueError(
                    f"expected CSV member {expected_member}, found {actual}"
                )
            with archive.open(members[0]) as raw, io.TextIOWrapper(
                raw, encoding="utf-8-sig", newline=""
            ) as text:
                rows = csv.reader(text)
                first = next(rows, None)
                if first is None:
                    raise ValueError(f"archive CSV is empty: {path}")
                if _looks_like_header(first):
                    expected_header = _EXPECTED_HEADERS[source]
                    actual_header = tuple(item.strip() for item in first)
                    if actual_header != expected_header:
                        raise ValueError(
                            f"unexpected {source} CSV header: {actual_header}"
                        )
                    first = next(rows, None)
                    if first is None:
                        raise ValueError(f"archive CSV has no data rows: {path}")
                if source == "aggTrades":
                    _consume(aggregate_aggtrades(_prepend(first, rows)))
                else:
                    _validate_first_data_row(first, source)
                    for row in rows:
                        _validate_first_data_row(row, source)
    except zipfile.BadZipFile as exc:
        raise ValueError(f"invalid ZIP archive: {path}") from exc


def _validate_first_data_row(row: Sequence[object], source: str) -> None:
    if source == "klines":
        parse_kline_feature_row(row)
    elif source == "aggTrades":
        next(aggregate_aggtrades([row]))
    elif source in _PRICE_FEATURES:
        parse_price_kline_row(row, source=source)
    elif source == "metrics":
        next(parse_metrics_rows([row]))
    else:
        next(parse_funding_rows([row]))


def parse_kline_feature_row(row: Sequence[object]) -> FeatureRow:
    if len(row) < 11:
        raise ValueError("Binance kline row must contain at least 11 fields")
    minute_end = _from_millis(_nonnegative_int(row[0], "kline open time")) + ONE_MINUTE
    prices = [_positive_decimal(row[index], "kline price") for index in range(1, 5)]
    volume = _nonnegative_decimal(row[5], "kline base volume")
    quote_volume = _nonnegative_decimal(row[7], "kline quote volume")
    trade_count = _nonnegative_int(row[8], "kline trade_count")
    taker_buy_base = _nonnegative_decimal(row[9], "taker buy base volume")
    taker_buy_quote = _nonnegative_decimal(row[10], "taker buy quote volume")
    if taker_buy_base > volume or taker_buy_quote > quote_volume:
        raise ValueError("taker buy volume cannot exceed total volume")
    taker_sell_base = volume - taker_buy_base
    taker_sell_quote = quote_volume - taker_buy_quote
    imbalance = (
        (taker_buy_base - taker_sell_base) / volume
        if volume != 0
        else Decimal(0)
    )
    if not Decimal(-1) <= imbalance <= Decimal(1):
        raise ValueError("taker imbalance must be between -1 and 1")
    return FeatureRow(
        minute_end=minute_end,
        available_at=minute_end,
        source="klines",
        features={
            "open": prices[0],
            "high": prices[1],
            "low": prices[2],
            "close": prices[3],
            "base_volume": volume,
            "quote_volume": quote_volume,
            "trade_count": Decimal(trade_count),
            "taker_buy_base_volume": taker_buy_base,
            "taker_sell_base_volume": taker_sell_base,
            "taker_buy_quote_volume": taker_buy_quote,
            "taker_sell_quote_volume": taker_sell_quote,
            "taker_imbalance": imbalance,
        },
    )


def parse_price_kline_row(row: Sequence[object], *, source: str) -> FeatureRow:
    if source not in _PRICE_FEATURES:
        raise ValueError(f"not a reference-price kline source: {source}")
    if len(row) < 5:
        raise ValueError("Binance price kline row must contain at least 5 fields")
    minute_end = _from_millis(_nonnegative_int(row[0], "kline open time")) + ONE_MINUTE
    close = (
        _finite_decimal(row[4], "premium index")
        if source == "premiumIndexKlines"
        else _positive_decimal(row[4], "reference price")
    )
    return FeatureRow(
        minute_end=minute_end,
        available_at=minute_end,
        source=source,
        features={_PRICE_FEATURES[source]: close},
    )


def aggregate_aggtrades(rows: Iterable[Sequence[object]]) -> Iterator[FeatureRow]:
    bucket: dict[str, object] | None = None
    previous_time: datetime | None = None
    previous_agg_id: int | None = None
    previous_last_id: int | None = None
    for row in rows:
        if len(row) < 7:
            raise ValueError("Binance aggTrade row must contain at least 7 fields")
        trade_time = _from_millis(_nonnegative_int(row[5], "aggTrade time"))
        agg_id = _nonnegative_int(row[0], "aggregate trade ID")
        first_id = _nonnegative_int(row[3], "first trade ID")
        last_id = _nonnegative_int(row[4], "last trade ID")
        if previous_time is not None and trade_time < previous_time:
            raise ValueError("aggTrade trade time is reversed")
        if previous_agg_id is not None and agg_id <= previous_agg_id:
            raise ValueError("aggTrade aggregate trade ID is not strictly increasing")
        if previous_last_id is not None and first_id <= previous_last_id:
            raise ValueError("aggTrade underlying trade ID ranges overlap or reverse")
        previous_time = trade_time
        previous_agg_id = agg_id
        previous_last_id = last_id
        minute_start = trade_time.replace(second=0, microsecond=0)
        if bucket is not None and minute_start != bucket["minute_start"]:
            if minute_start < bucket["minute_start"]:
                raise ValueError("aggTrades must be ordered by trade time")
            yield _aggtrade_bucket_row(bucket)
            bucket = None
        if bucket is None:
            bucket = {
                "minute_start": minute_start,
                "buy_base": Decimal(0),
                "sell_base": Decimal(0),
                "buy_quote": Decimal(0),
                "sell_quote": Decimal(0),
                "rows": 0,
                "actual_count": 0,
            }
        if last_id < first_id:
            raise ValueError(
                f"aggTrade has reversed trade ID range: {first_id}..{last_id}"
            )
        price = _positive_decimal(row[1], "aggTrade price")
        quantity = _nonnegative_decimal(row[2], "aggTrade quantity")
        quote = price * quantity
        is_buyer_maker = _parse_buyer_maker(row[6])
        side = "sell" if is_buyer_maker else "buy"
        bucket[f"{side}_base"] += quantity
        bucket[f"{side}_quote"] += quote
        bucket["rows"] += 1
        bucket["actual_count"] += last_id - first_id + 1
    if bucket is not None:
        yield _aggtrade_bucket_row(bucket)


def _aggtrade_bucket_row(bucket: Mapping[str, object]) -> FeatureRow:
    buy_base = _decimal(bucket["buy_base"])
    sell_base = _decimal(bucket["sell_base"])
    buy_quote = _decimal(bucket["buy_quote"])
    sell_quote = _decimal(bucket["sell_quote"])
    total_base = buy_base + sell_base
    total_quote = buy_quote + sell_quote
    actual_count = int(bucket["actual_count"])
    minute_end = bucket["minute_start"] + ONE_MINUTE
    return FeatureRow(
        minute_end=minute_end,
        available_at=minute_end,
        source="aggTrades",
        features={
            "aggressive_buy_base_volume": buy_base,
            "aggressive_sell_base_volume": sell_base,
            "aggressive_buy_quote_notional": buy_quote,
            "aggressive_sell_quote_notional": sell_quote,
            "aggregate_trade_count": Decimal(int(bucket["rows"])),
            "actual_trade_count": Decimal(actual_count),
            "cvd_delta": buy_base - sell_base,
            "aggtrade_vwap": total_quote / total_base if total_base else Decimal(0),
            "trade_intensity": Decimal(actual_count),
        },
    )


def parse_funding_rows(rows: Iterable[Mapping[str, object] | Sequence[object]]) -> Iterator[FeatureRow]:
    for row in rows:
        if isinstance(row, Mapping):
            timestamp = row.get("fundingTime", row.get("calc_time"))
            rate = row.get("fundingRate", row.get("last_funding_rate"))
        else:
            if len(row) < 3:
                raise ValueError("Binance funding row must contain at least 3 fields")
            timestamp, rate = row[0], row[2]
        if timestamp is None or rate is None:
            raise ValueError("funding row is missing calc_time or funding rate")
        calc_time = _from_millis(_nonnegative_int(timestamp, "funding calc_time"))
        funding_rate = _finite_decimal(rate, "funding rate")
        yield FeatureRow(
            minute_end=calc_time,
            available_at=calc_time,
            source="fundingRate",
            features={"funding_rate": funding_rate},
        )


def parse_metrics_rows(rows: Iterable[Sequence[object]]) -> Iterator[FeatureRow]:
    previous_time: datetime | None = None
    previous_symbol: str | None = None
    previous_values: dict[str, Decimal] | None = None
    for row in rows:
        if len(row) < 8:
            raise ValueError("Binance metrics row must contain at least 8 fields")
        try:
            measured_at = datetime.strptime(
                str(row[0]).strip(), "%Y-%m-%d %H:%M:%S"
            ).replace(tzinfo=UTC)
        except ValueError as exc:
            raise ValueError("invalid Binance metrics create_time") from exc
        symbol = _normalize_symbol(str(row[1]))
        if previous_time is not None and measured_at <= previous_time:
            raise ValueError("metrics create_time must be strictly increasing")
        if previous_symbol is not None and symbol != previous_symbol:
            raise ValueError("metrics archive contains multiple symbols")
        values: dict[str, Decimal] = {}
        open_interest = _nonnegative_decimal(row[2], "open interest")
        open_interest_value = _nonnegative_decimal(row[3], "open interest value")
        if open_interest > 0 and open_interest_value > 0:
            values["open_interest"] = open_interest
            values["open_interest_value"] = open_interest_value
        optional_ratios = (
            (4, "top_trader_account_long_short_ratio", "top trader account long short ratio"),
            (5, "top_trader_position_long_short_ratio", "top trader position long short ratio"),
            (6, "global_long_short_ratio", "global long short ratio"),
            (7, "taker_long_short_volume_ratio", "taker long short volume ratio"),
        )
        for index, name, label in optional_ratios:
            if str(row[index]).strip():
                values[name] = _positive_decimal(row[index], label)

        changes: dict[str, Decimal] = {}
        is_regular_interval = (
            previous_time is not None
            and measured_at - previous_time == timedelta(minutes=5)
        )
        change_specs = (
            (
                "top_trader_position_long_short_ratio",
                "top_trader_position_change_5m",
            ),
            ("global_long_short_ratio", "global_long_short_change_5m"),
            (
                "taker_long_short_volume_ratio",
                "taker_long_short_change_5m",
            ),
        )
        if "open_interest" in values:
            if (
                is_regular_interval
                and previous_values is not None
                and "open_interest" in previous_values
            ):
                changes["open_interest_change_ratio_5m"] = (
                    values["open_interest"] - previous_values["open_interest"]
                ) / previous_values["open_interest"]
        for value_name, change_name in change_specs:
            if value_name not in values:
                continue
            if (
                is_regular_interval
                and previous_values is not None
                and value_name in previous_values
            ):
                changes[change_name] = (
                    values[value_name] - previous_values[value_name]
                )
        yield FeatureRow(
            minute_end=measured_at,
            available_at=measured_at,
            source="metrics",
            features={**values, **changes},
        )
        previous_time = measured_at
        previous_symbol = symbol
        previous_values = values


def merge_feature_rows(
    base_rows: Iterable[FeatureRow],
    source_rows: Mapping[str, Iterable[FeatureRow]],
    *,
    requested_sources: Sequence[str],
    symbol: str,
) -> Iterator[MarketFeatureSet]:
    requested = _validate_sources(requested_sources)
    exact = {
        source: _rows_by_timestamp(rows, source)
        for source, rows in source_rows.items()
        if source not in {"fundingRate", "metrics"}
    }
    funding = sorted(
        _rows_by_timestamp(
            source_rows.get("fundingRate", ()), "fundingRate"
        ).values(),
        key=lambda row: row.available_at,
    )
    funding_index = 0
    current_funding: FeatureRow | None = None
    metrics = sorted(
        _rows_by_timestamp(source_rows.get("metrics", ()), "metrics").values(),
        key=lambda row: row.available_at,
    )
    metrics_index = 0
    current_metrics: FeatureRow | None = None
    domain_symbol = _domain_symbol(symbol)

    for base in base_rows:
        if base.source != "klines":
            raise ValueError("base feature rows must be klines")
        close = base.minute_end
        selected = [base]
        unavailable = []
        for source in requested:
            if source in {"klines", "fundingRate", "metrics"}:
                continue
            row = exact.get(source, {}).get(close)
            if row is None:
                unavailable.append(source)
            else:
                selected.append(row)

        if "fundingRate" in requested:
            while funding_index < len(funding) and funding[funding_index].available_at <= close:
                current_funding = funding[funding_index]
                funding_index += 1
            if current_funding is None or close - current_funding.available_at > FUNDING_MAX_AGE:
                unavailable.append("fundingRate")
            else:
                selected.append(current_funding)

        if "metrics" in requested:
            while (
                metrics_index < len(metrics)
                and metrics[metrics_index].available_at <= close
            ):
                current_metrics = metrics[metrics_index]
                metrics_index += 1
            if (
                current_metrics is None
                or close - current_metrics.available_at > METRICS_MAX_AGE
            ):
                unavailable.append("metrics")
            else:
                if current_metrics.available_at < close:
                    current_metrics = FeatureRow(
                        minute_end=current_metrics.minute_end,
                        available_at=current_metrics.available_at,
                        source=current_metrics.source,
                        features={
                            name: value
                            for name, value in current_metrics.features.items()
                            if not name.endswith("_change_5m")
                        },
                    )
                selected.append(current_metrics)

        values = []
        names = set()
        for row in selected:
            if row.available_at > close:
                raise ValueError(f"future {row.source} feature at {row.available_at.isoformat()}")
            for name, value in row.features.items():
                if name in names:
                    raise ValueError(f"duplicate feature conflict: {name}")
                names.add(name)
                values.append(
                    MarketFeatureValue(
                        name=name,
                        value=value,
                        source=row.source,
                        observed_at=row.minute_end,
                        available_at=row.available_at,
                    )
                )
        yield MarketFeatureSet(
            symbol=domain_symbol,
            timeframe=Timeframe(1, "m"),
            measured_at=close,
            values=tuple(values),
            unavailable_sources=tuple(unavailable),
        )


def write_feature_cache(
    rows: Iterable[MarketFeatureSet],
    *,
    cache_root: Path,
    symbol: str,
    start: datetime,
    end: datetime,
    requested_sources: Sequence[str],
    raw_hashes: Mapping[str, str],
    source_archive_statuses: Mapping[str, Mapping[str, Sequence[str]]] | None = None,
    input_hashes: Mapping[str, str] | None = None,
    provenance: Mapping[str, object] | None = None,
    aggtrades_max_bytes: int = DEFAULT_AGGTRADES_MAX_BYTES,
    schema_version: str = FEATURE_CACHE_SCHEMA_VERSION,
    lock_timeout_seconds: float = 5.0,
    lock_stale_seconds: float = 60.0,
) -> tuple[Path, Path]:
    symbol = _normalize_symbol(symbol)
    requested = _validate_sources(requested_sources)
    output_dir = Path(cache_root) / "features" / symbol / "1m"
    output_dir.mkdir(parents=True, exist_ok=True)
    identity = {
        "schema_version": schema_version,
        "symbol": symbol,
        "start": _iso(start),
        "end": _iso(end),
        "sources": [source for source in SUPPORTED_SOURCES if source in requested],
        "aggtrades_max_bytes": aggtrades_max_bytes,
    }
    identity_hash = hashlib.sha256(_canonical_json_bytes(identity)).hexdigest()
    stem = f"{_filename_time(start)}_{_filename_time(end)}_{identity_hash}"
    jsonl_path = output_dir / f"{stem}.jsonl"
    manifest_path = output_dir / f"{stem}.manifest.json"
    lock_path = publication_lock_path(jsonl_path)
    temporary = _unique_temp_path(jsonl_path)
    try:
        summary = _write_feature_rows(rows, temporary, requested)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise

    archive_statuses = source_archive_statuses or {}
    coverage = {
        source: {
            "available_rows": summary.available_rows[source],
            "unavailable_rows": summary.row_count - summary.available_rows[source],
            "budget_skipped_archives": list(
                archive_statuses.get(source, {}).get("budget_skipped", ())
            ),
        }
        for source in requested
    }
    combined_input_hashes = dict(raw_hashes)
    combined_input_hashes.update(input_hashes or {})
    publication_started = False
    try:
        with _publication_lock(
            lock_path,
            timeout_seconds=lock_timeout_seconds,
            stale_seconds=lock_stale_seconds,
        ):
            publication_started = True
            manifest_path.unlink(missing_ok=True)
            os.replace(temporary, jsonl_path)
            manifest = {
                "symbol": symbol,
                "cache_identity": identity,
                "cache_identity_hash": identity_hash,
                "timeframe": "1m",
                "requested_range": {"start": _iso(start), "end": _iso(end)},
                "actual_range": {
                    "min": _iso(summary.minimum) if summary.minimum else None,
                    "max": _iso(summary.maximum) if summary.maximum else None,
                },
                "row_count": summary.row_count,
                "source_coverage": coverage,
                "raw_hashes": dict(sorted(raw_hashes.items())),
                "input_hashes": dict(sorted(combined_input_hashes.items())),
                "provenance": dict(sorted((provenance or {}).items())),
                "output_hash": summary.output_hash,
            }
            _atomic_json(manifest_path, manifest)
    except BaseException:
        temporary.unlink(missing_ok=True)
        if publication_started:
            manifest_path.unlink(missing_ok=True)
        raise
    return jsonl_path, manifest_path


def _write_feature_rows(
    rows: Iterable[MarketFeatureSet],
    temporary: Path,
    requested: Sequence[str],
) -> _FeatureWriteSummary:
    digest = hashlib.sha256()
    available_rows = {source: 0 for source in requested}
    row_count = 0
    minimum = None
    maximum = None
    with temporary.open("wb") as output:
        for feature_set in rows:
            measured_at = _as_utc(feature_set.measured_at)
            minimum = measured_at if minimum is None else min(minimum, measured_at)
            maximum = measured_at if maximum is None else max(maximum, measured_at)
            unavailable = set(feature_set.unavailable_sources)
            for source in requested:
                if source not in unavailable:
                    available_rows[source] += 1
            line = (
                json.dumps(
                    _feature_set_payload(feature_set),
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            ).encode("utf-8")
            output.write(line)
            digest.update(line)
            row_count += 1
        output.flush()
        os.fsync(output.fileno())
    return _FeatureWriteSummary(
        output_hash=digest.hexdigest(),
        row_count=row_count,
        minimum=minimum,
        maximum=maximum,
        available_rows=available_rows,
    )


def validate_cache_pair(jsonl_path: Path, manifest_path: Path) -> bool:
    try:
        if not Path(jsonl_path).is_file() or not Path(manifest_path).is_file():
            return False
        manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
        if not isinstance(manifest, dict):
            return False
        output_hash = manifest.get("output_hash")
        if not isinstance(output_hash, str) or len(output_hash) != 64:
            return False
        int(output_hash, 16)
        return output_hash == _sha256_file(Path(jsonl_path))
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
        return False


def publication_lock_path(jsonl_path: Path) -> Path:
    return Path(jsonl_path).with_suffix(".lock")


@contextmanager
def _publication_lock(
    lock_path: Path,
    *,
    timeout_seconds: float,
    stale_seconds: float,
) -> Iterator[None]:
    if timeout_seconds < 0 or stale_seconds <= 0:
        raise ValueError("publication lock timing values are invalid")
    deadline = time.monotonic() + timeout_seconds
    token = uuid.uuid4().hex
    acquired = False
    while not acquired:
        try:
            descriptor = os.open(
                lock_path,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            )
            try:
                os.write(descriptor, token.encode("ascii"))
            finally:
                os.close(descriptor)
            acquired = True
        except FileExistsError:
            try:
                age = time.time() - lock_path.stat().st_mtime
                if age > stale_seconds:
                    lock_path.unlink(missing_ok=True)
                    continue
            except FileNotFoundError:
                continue
            if time.monotonic() >= deadline:
                raise TimeoutError(f"timed out waiting for publication lock: {lock_path}")
            time.sleep(min(0.01, max(0.0, deadline - time.monotonic())))
    try:
        yield
    finally:
        if acquired:
            try:
                if lock_path.read_text(encoding="ascii") == token:
                    lock_path.unlink(missing_ok=True)
            except (FileNotFoundError, OSError, UnicodeError):
                pass


def iter_chunk_rows(
    chunks: Iterable[object],
    builder: Callable[[object], Iterable[MarketFeatureSet]],
) -> Iterator[MarketFeatureSet]:
    for chunk in chunks:
        rows = iter(builder(chunk))
        try:
            yield from rows
        finally:
            close = getattr(rows, "close", None)
            if close is not None:
                close()


def _calendar_chunks(start: datetime, end: datetime) -> Iterator[tuple[datetime, datetime]]:
    cursor = start
    while cursor < end:
        boundary = _next_month(_month_start(cursor))
        chunk_end = min(end, boundary)
        yield cursor, chunk_end
        cursor = chunk_end


class HistoricalFeatureLoader:
    def __init__(
        self,
        cache_root: Path = DEFAULT_CACHE_ROOT,
        *,
        downloader: ArchiveDownloader | None = None,
        clock: Callable[[], datetime] | None = None,
        api_get: Callable[[str, Mapping[str, object]], object] | None = None,
        aggtrades_max_bytes: int = DEFAULT_AGGTRADES_MAX_BYTES,
        funding_max_pages: int = DEFAULT_FUNDING_MAX_PAGES,
    ) -> None:
        if aggtrades_max_bytes <= 0:
            raise ValueError("aggtrades_max_bytes must be positive")
        if funding_max_pages <= 0:
            raise ValueError("funding_max_pages must be positive")
        self.cache_root = Path(cache_root)
        self.downloader = downloader or ArchiveDownloader()
        self.clock = clock or (lambda: datetime.now(UTC))
        self.api_get = api_get or self._public_api_get
        self.aggtrades_max_bytes = aggtrades_max_bytes
        self.funding_max_pages = funding_max_pages

    def build_cache(
        self,
        *,
        symbol: str,
        start: datetime,
        end: datetime,
        sources: Sequence[str],
    ) -> tuple[Path, Path]:
        symbol = _normalize_symbol(symbol)
        start = _as_utc(start)
        end = _as_utc(end)
        requested = _validate_sources(sources)
        if "klines" not in requested:
            raise ValueError("klines is required as the base feature source")
        now = _as_utc(self.clock())
        raw_hashes: dict[str, str] = {}
        input_hashes: dict[str, str] = {}
        provenance: dict[str, object] = {}
        source_archive_statuses: dict[str, dict[str, list[str]]] = {
            source: {"budget_skipped": []} for source in requested
        }
        funding_requests: set[tuple[datetime, datetime]] = set()
        chunks = _calendar_chunks(start, end)

        def build_chunk(chunk: tuple[datetime, datetime]) -> Iterator[MarketFeatureSet]:
            return self._build_chunk_rows(
                symbol=symbol,
                start=chunk[0],
                end=chunk[1],
                now=now,
                requested=requested,
                raw_hashes=raw_hashes,
                input_hashes=input_hashes,
                provenance=provenance,
                source_archive_statuses=source_archive_statuses,
                funding_requests=funding_requests,
            )

        merged = iter_chunk_rows(chunks, build_chunk)
        return write_feature_cache(
            merged,
            cache_root=self.cache_root,
            symbol=symbol,
            start=start,
            end=end,
            requested_sources=requested,
            raw_hashes=raw_hashes,
            source_archive_statuses=source_archive_statuses,
            input_hashes=input_hashes,
            provenance=provenance,
            aggtrades_max_bytes=self.aggtrades_max_bytes,
        )

    def _build_chunk_rows(
        self,
        *,
        symbol: str,
        start: datetime,
        end: datetime,
        now: datetime,
        requested: tuple[str, ...],
        raw_hashes: dict[str, str],
        input_hashes: dict[str, str],
        provenance: dict[str, object],
        source_archive_statuses: dict[str, dict[str, list[str]]],
        funding_requests: set[tuple[datetime, datetime]],
    ) -> Iterator[MarketFeatureSet]:
        loaded: dict[str, list[FeatureRow]] = {source: [] for source in requested}
        for source in requested:
            archive_start = start
            if source == "fundingRate" and start < _month_start(now):
                archive_start -= FUNDING_MAX_AGE
            for request in iter_archive_requests(
                source, symbol, archive_start, end, now=now
            ):
                destination = self.cache_root / "raw" / source / symbol / request.filename
                result = self.downloader.download(
                    request.url,
                    destination,
                    source=source,
                    max_bytes=(
                        self.aggtrades_max_bytes if source == "aggTrades" else None
                    ),
                )
                if result.status == "budget_skipped":
                    source_archive_statuses[source]["budget_skipped"].append(
                        request.period
                    )
                    continue
                if result.status == "unavailable":
                    if source == "fundingRate":
                        period_start, period_end = _archive_request_bounds(request)
                        fallback_start = max(archive_start, period_start)
                        fallback_end = min(end, period_end)
                        loaded[source].extend(
                            self._load_funding_range_once(
                                symbol,
                                fallback_start,
                                fallback_end,
                                funding_requests=funding_requests,
                                input_hashes=input_hashes,
                                provenance=provenance,
                            )
                        )
                    continue
                if result.sha256:
                    key = str(destination.relative_to(self.cache_root)).replace("\\", "/")
                    raw_hashes[key] = result.sha256
                    input_hashes[key] = result.sha256
                    provenance[key] = {
                        "kind": "archive",
                        "source": source,
                        "period": request.period,
                        "url": request.url,
                    }
                loaded[source].extend(self._parse_archive(source, destination, start, end))

        if "fundingRate" in requested and end > _month_start(now):
            current_start = max(start, _month_start(now)) - FUNDING_MAX_AGE
            current_end = min(end, now)
            loaded["fundingRate"].extend(
                self._load_funding_range_once(
                    symbol,
                    current_start,
                    current_end,
                    funding_requests=funding_requests,
                    input_hashes=input_hashes,
                    provenance=provenance,
                )
            )

        base = _deduplicate_rows(loaded.pop("klines"), "klines")
        yield from merge_feature_rows(
            base,
            loaded,
            requested_sources=requested,
            symbol=symbol,
        )

    def _parse_archive(
        self,
        source: str,
        path: Path,
        start: datetime,
        end: datetime,
    ) -> Iterator[FeatureRow]:
        rows = iter_zip_csv_rows(path)
        if source == "aggTrades":
            parsed = aggregate_aggtrades(rows)
        elif source == "klines":
            parsed = (parse_kline_feature_row(row) for row in rows)
        elif source in _PRICE_FEATURES:
            parsed = (parse_price_kline_row(row, source=source) for row in rows)
        elif source == "metrics":
            parsed = parse_metrics_rows(rows)
        else:
            parsed = parse_funding_rows(rows)
        for row in parsed:
            if source == "fundingRate":
                if start - FUNDING_MAX_AGE <= row.available_at <= end:
                    yield row
            elif start < row.minute_end <= end:
                yield row

    def _load_funding_range_once(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
        *,
        funding_requests: set[tuple[datetime, datetime]],
        input_hashes: dict[str, str],
        provenance: dict[str, object],
    ) -> Iterator[FeatureRow]:
        request_range = (_as_utc(start), _as_utc(end))
        if request_range in funding_requests or start >= end:
            return
        funding_requests.add(request_range)
        cursor = start
        seen: dict[int, Decimal] = {}
        page_count = 0
        while cursor < end:
            if page_count >= self.funding_max_pages:
                raise ValueError("Binance fundingRate pagination exceeded page limit")
            page_count += 1
            params = {
                "symbol": symbol,
                "startTime": _to_millis(cursor),
                "endTime": _to_millis(end),
                "limit": 1000,
            }
            payload = self.api_get(
                "/fapi/v1/fundingRate",
                params,
            )
            if not isinstance(payload, list):
                raise ValueError("Binance fundingRate response must be a list")
            page, maximum_time = _validate_funding_page(
                payload,
                lower_bound=start,
                upper_bound=end,
                seen=seen,
            )
            canonical = _canonical_json_bytes(payload)
            key = (
                f"rest/fundingRate/{symbol}/"
                f"{params['startTime']}-{params['endTime']}.json"
            )
            rest_path = self.cache_root / "raw" / "fundingRate" / symbol / "rest" / Path(key).name
            _atomic_bytes(rest_path, canonical)
            input_hashes[key] = hashlib.sha256(canonical).hexdigest()
            provenance[key] = {
                "kind": "rest",
                "source": "fundingRate",
                "request": {
                    "path": "/fapi/v1/fundingRate",
                    "params": params,
                },
            }
            yield from page
            if len(payload) < 1000:
                break
            if maximum_time is None:
                raise ValueError("Binance fundingRate full page had no rows")
            next_cursor = _from_millis(maximum_time) + timedelta(milliseconds=1)
            if next_cursor <= cursor:
                raise ValueError("Binance fundingRate pagination did not advance")
            cursor = next_cursor

    @staticmethod
    def _public_api_get(path: str, params: Mapping[str, object]) -> object:
        return request_json(BinanceConfig.default(), "GET", path, params=params)


def _rows_by_timestamp(rows: Iterable[FeatureRow], source: str) -> dict[datetime, FeatureRow]:
    result = {}
    for row in rows:
        if row.source != source:
            raise ValueError(f"row source mismatch: expected {source}, got {row.source}")
        existing = result.get(row.minute_end)
        if existing is not None and existing != row:
            raise ValueError(f"duplicate {source} conflict at {row.minute_end.isoformat()}")
        result[row.minute_end] = row
    return result


def _deduplicate_rows(rows: Iterable[FeatureRow], source: str) -> list[FeatureRow]:
    return [row for _, row in sorted(_rows_by_timestamp(rows, source).items())]


def _feature_set_payload(row: MarketFeatureSet) -> dict[str, object]:
    return {
        "symbol": row.symbol.pair,
        "timeframe": row.timeframe.label,
        "measured_at": _iso(row.measured_at),
        "features": {
            value.name: {
                "value": str(value.value),
                "source": value.source,
                "observed_at": _iso(value.observed_at),
                "available_at": _iso(value.available_at),
            }
            for value in row.values
        },
        "unavailable_sources": list(row.unavailable_sources),
    }


def _atomic_json(path: Path, payload: Mapping[str, object]) -> None:
    temporary = _unique_temp_path(path)
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as output:
            json.dump(payload, output, indent=2, sort_keys=True)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _atomic_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = _unique_temp_path(path)
    try:
        with temporary.open("wb") as output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _canonical_json_bytes(payload: object) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")


def _unique_temp_path(path: Path) -> Path:
    return path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")


def _validate_funding_page(
    payload: Sequence[object],
    *,
    lower_bound: datetime,
    upper_bound: datetime,
    seen: dict[int, Decimal],
) -> tuple[list[FeatureRow], int | None]:
    lower_millis = _to_millis(lower_bound)
    upper_millis = _to_millis(upper_bound)
    previous: int | None = None
    result = []
    maximum: int | None = None
    for raw in payload:
        if not isinstance(raw, Mapping):
            raise ValueError("Binance fundingRate rows must be objects")
        timestamp = int(raw.get("fundingTime"))
        if not lower_millis <= timestamp <= upper_millis:
            raise ValueError("Binance fundingRate row is outside requested bounds")
        if previous is not None and timestamp <= previous:
            raise ValueError("Binance fundingRate page is not strictly ordered")
        previous = timestamp
        maximum = timestamp if maximum is None else max(maximum, timestamp)
        parsed = next(parse_funding_rows([raw]))
        rate = parsed.features["funding_rate"]
        existing = seen.get(timestamp)
        if existing is not None:
            if existing != rate:
                raise ValueError(f"duplicate fundingRate conflict at {timestamp}")
            continue
        seen[timestamp] = rate
        result.append(parsed)
    return result, maximum


def _response_content_length(response: object) -> int | None:
    headers = getattr(response, "headers", None)
    value = headers.get("Content-Length") if headers is not None else None
    if value is None and hasattr(response, "getheader"):
        value = response.getheader("Content-Length")
    if value is None:
        return None
    try:
        length = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid Content-Length: {value}") from exc
    if length < 0:
        raise ValueError(f"invalid Content-Length: {value}")
    return length


def _archive_request_bounds(request: ArchiveRequest) -> tuple[datetime, datetime]:
    if request.granularity == "monthly":
        start = datetime.strptime(request.period, "%Y-%m").replace(tzinfo=UTC)
        return start, _next_month(start)
    start = datetime.combine(
        datetime.strptime(request.period, "%Y-%m-%d").date(),
        datetime.min.time(),
        tzinfo=UTC,
    )
    return start, start + timedelta(days=1)


def _validate_sources(sources: Sequence[str]) -> tuple[str, ...]:
    normalized = tuple(sources)
    if not normalized:
        raise ValueError("at least one source is required")
    for source in normalized:
        _require_source(source)
    if len(set(normalized)) != len(normalized):
        raise ValueError("duplicate sources are not allowed")
    return tuple(source for source in SUPPORTED_SOURCES if source in normalized)


def _require_source(source: str) -> None:
    if source not in SUPPORTED_SOURCES:
        raise ValueError(
            f"unsupported source {source!r}; expected one of {', '.join(SUPPORTED_SOURCES)}"
        )


def _looks_like_header(row: Sequence[str]) -> bool:
    if not row:
        return False
    try:
        int(row[0])
    except ValueError:
        return True
    return False


def _decimal(value: object) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _finite_decimal(value: object, field_name: str) -> Decimal:
    try:
        result = _decimal(value)
    except Exception as exc:
        raise ValueError(f"{field_name} must be numeric") from exc
    if not result.is_finite():
        raise ValueError(f"{field_name} must be finite")
    return result


def _nonnegative_decimal(value: object, field_name: str) -> Decimal:
    result = _finite_decimal(value, field_name)
    if result < 0:
        raise ValueError(f"{field_name} must be nonnegative")
    return result


def _positive_decimal(value: object, field_name: str) -> Decimal:
    result = _finite_decimal(value, field_name)
    if result <= 0:
        raise ValueError(f"{field_name} must be positive")
    return result


def _nonnegative_int(value: object, field_name: str) -> int:
    try:
        token = str(value)
        if token.strip() != token or not token.isdigit():
            raise ValueError
        result = int(token)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be an integral nonnegative value") from exc
    return result


def _parse_buyer_maker(value: object) -> bool:
    token = str(value).strip().lower()
    if token == "true":
        return True
    if token == "false":
        return False
    raise ValueError(f"invalid buyer-maker token: {value!r}")


def _prepend(first: Sequence[object], rows: Iterable[Sequence[object]]) -> Iterator[Sequence[object]]:
    yield first
    yield from rows


def _consume(rows: Iterable[object]) -> None:
    for _ in rows:
        pass


def _from_millis(value: object) -> datetime:
    return datetime.fromtimestamp(int(value) / 1000, tz=UTC)


def _to_millis(value: datetime) -> int:
    return int(_as_utc(value).timestamp() * 1000)


def _as_utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime values must be timezone-aware")
    return value.astimezone(UTC)


def _month_start(value: datetime) -> datetime:
    value = _as_utc(value)
    return value.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _next_month(value: datetime) -> datetime:
    return (value.replace(day=28) + timedelta(days=4)).replace(day=1)


def _normalize_symbol(symbol: str) -> str:
    normalized = symbol.strip().upper()
    if not normalized or not normalized.isalnum():
        raise ValueError("symbol must be a non-empty alphanumeric pair")
    return normalized


def _domain_symbol(pair: str) -> Symbol:
    pair = _normalize_symbol(pair)
    for quote in ("USDT", "USDC", "BUSD", "FDUSD", "USD"):
        if pair.endswith(quote) and len(pair) > len(quote):
            return Symbol(pair[: -len(quote)], quote)
    raise ValueError(f"cannot infer quote asset from symbol {pair}")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _filename_time(value: datetime) -> str:
    return _as_utc(value).strftime("%Y%m%dT%H%M%SZ")


def _iso(value: datetime) -> str:
    return _as_utc(value).isoformat()
