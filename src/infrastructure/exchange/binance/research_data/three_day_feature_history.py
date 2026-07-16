from __future__ import annotations

from collections import deque
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import math
from pathlib import Path
from types import MappingProxyType

from src.application.services.three_day_chart_feature_extractor import (
    extract_three_day_chart_feature_vector,
)
from src.domain.market import Candle, Symbol, Timeframe
from src.domain.regime import (
    DailyRegimeEpisode,
    ThreeDayChartFeatureVector,
    build_daily_regime_episodes,
)
from src.infrastructure.exchange.binance.research_data.historical_feature_loader import (
    ArchiveDownloader,
    archive_url,
    iter_archive_requests,
    iter_zip_csv_rows,
    parse_kline_feature_row,
    validate_archive,
)


MINUTES_PER_THREE_DAYS = 3 * 24 * 60


@dataclass(frozen=True)
class ThreeDayFeatureHistoryContract:
    start_at: datetime
    end_at: datetime
    episodes: tuple[DailyRegimeEpisode, ...]

    def __post_init__(self) -> None:
        expected = build_daily_regime_episodes(self.start_at, self.end_at)
        episodes = tuple(self.episodes)
        if episodes != expected:
            raise ValueError("episodes must exactly match the canonical daily regime episodes")
        object.__setattr__(self, "episodes", episodes)


def _symbol(value: str) -> Symbol:
    if value != value.strip().upper() or not value.endswith("USDT") or len(value) <= 4:
        raise ValueError("symbol must be a canonical uppercase USDT pair")
    return Symbol(value[:-4], "USDT")


def _is_canonical_period(value: object, granularity: object) -> bool:
    if not isinstance(value, str):
        return False
    format_string = {"monthly": "%Y-%m", "daily": "%Y-%m-%d"}.get(granularity)
    if format_string is None:
        return False
    try:
        parsed = datetime.strptime(value, format_string)
    except ValueError:
        return False
    return parsed.strftime(format_string) == value


def candle_from_kline_row(row: Sequence[object], *, symbol: str) -> Candle:
    parsed = parse_kline_feature_row(row)
    opened_at = parsed.minute_end - timedelta(minutes=1)
    values = parsed.features
    candle = Candle(
        symbol=_symbol(symbol),
        timeframe=Timeframe(1, "m"),
        opened_at=opened_at,
        closed_at=parsed.minute_end,
        open_price=values["open"],
        high_price=values["high"],
        low_price=values["low"],
        close_price=values["close"],
        volume=values["base_volume"],
    )
    if any(
        not math.isfinite(float(value))
        for value in (
            candle.open_price,
            candle.high_price,
            candle.low_price,
            candle.close_price,
            candle.volume,
        )
    ):
        raise ValueError("OHLCV values must be finite")
    return candle


def candles_from_kline_rows(
    rows: Iterable[Sequence[object]],
    *,
    symbol: str,
    start: datetime,
    end: datetime,
) -> tuple[Candle, ...]:
    _symbol(symbol)
    result: list[Candle] = []
    expected = start
    for row in rows:
        candle = candle_from_kline_row(row, symbol=symbol)
        if not start <= candle.opened_at < end:
            raise ValueError("kline candle is outside requested bounds")
        if candle.opened_at != expected:
            raise ValueError("kline minute continuity gap, duplicate, or reversal")
        result.append(candle)
        expected = candle.closed_at
    if expected != end:
        raise ValueError("kline continuity does not cover exact requested bounds")
    return tuple(result)


def load_three_day_feature_history(
    *,
    symbol: str,
    start: datetime,
    end: datetime,
    raw_root: Path,
    expected_anchor_count: int,
    downloader: ArchiveDownloader | None = None,
    request_factory: Callable[..., Iterable[object]] = iter_archive_requests,
    row_reader: Callable[[Path], Iterable[Sequence[object]]] = iter_zip_csv_rows,
) -> tuple[
    tuple[ThreeDayChartFeatureVector, ...],
    tuple[Mapping[str, object], ...],
]:
    _symbol(symbol)
    if (
        not isinstance(expected_anchor_count, int)
        or isinstance(expected_anchor_count, bool)
        or expected_anchor_count <= 0
    ):
        raise ValueError("expected_anchor_count must be a positive integer")
    contract = ThreeDayFeatureHistoryContract(
        start,
        end,
        build_daily_regime_episodes(start, end),
    )
    downloader = downloader or ArchiveDownloader()
    requests = tuple(
        request_factory("klines", symbol, start, end, now=end + timedelta(days=32))
    )
    if not requests:
        raise ValueError("no Binance kline archive requests cover interval")
    expected_requests = tuple(
        iter_archive_requests("klines", symbol, start, end, now=end + timedelta(days=32))
    )
    if requests != expected_requests:
        raise ValueError("archive requests must exactly match canonical ordered coverage")

    provenance: list[Mapping[str, object]] = []
    window: deque[Candle] = deque(maxlen=MINUTES_PER_THREE_DAYS)
    vectors: list[ThreeDayChartFeatureVector] = []
    expected_minute = start
    anchors = {episode.anchor_at for episode in contract.episodes}
    for request in requests:
        try:
            canonical_url = archive_url(
                "klines", symbol, request.period, request.granularity
            )
            valid_request = (
                request.source == "klines"
                and request.symbol == symbol
                and _is_canonical_period(request.period, request.granularity)
                and request.url == canonical_url
            )
        except (AttributeError, TypeError, ValueError):
            valid_request = False
        if not valid_request:
            raise ValueError("archive request must use the canonical kline symbol and URL")

        destination = Path(raw_root) / symbol / request.filename
        result = downloader.download(request.url, destination, source="klines")
        if result.status not in {"cached", "downloaded"}:
            raise ValueError(f"required archive unavailable: {request.period} ({result.status})")
        if (
            not isinstance(result.sha256, str)
            or len(result.sha256) != 64
            or result.sha256 != result.sha256.lower()
            or any(character not in "0123456789abcdef" for character in result.sha256)
        ):
            raise ValueError("archive sha256 must be canonical lowercase hexadecimal")
        if (
            not isinstance(result.expected_sha256, str)
            or len(result.expected_sha256) != 64
            or result.expected_sha256 != result.expected_sha256.lower()
            or any(character not in "0123456789abcdef" for character in result.expected_sha256)
            or result.expected_sha256 != result.sha256
        ):
            raise ValueError("archive expected checksum must exactly match content sha256")
        if (
            not isinstance(result.bytes_received, int)
            or isinstance(result.bytes_received, bool)
            or result.bytes_received <= 0
        ):
            raise ValueError("archive bytes must be a positive integer")
        member_identity = result.member_identity
        if member_identity is None:
            # Backward-compatible custom downloaders may not carry validation
            # metadata. Validate once here; the standard downloader already did.
            member_identity = validate_archive(
                result.path,
                source="klines",
                expected_archive_filename=request.filename,
            )
        provenance.append(
            MappingProxyType(
                {
                    "period": request.period,
                    "url": request.url,
                    "sha256": result.sha256,
                    "expected_sha256": result.expected_sha256,
                    "checksum_verified": True,
                    "bytes": result.bytes_received,
                    "member_identity": member_identity,
                    "source": "klines",
                    "symbol": symbol,
                    "timeframe": "1m",
                    "granularity": request.granularity,
                    "requested_start_at": start.isoformat().replace("+00:00", "Z"),
                    "requested_end_at": end.isoformat().replace("+00:00", "Z"),
                }
            )
        )

        for row in row_reader(result.path):
            candle = candle_from_kline_row(row, symbol=symbol)
            if candle.opened_at < start or candle.opened_at >= end:
                continue
            if candle.opened_at != expected_minute:
                raise ValueError("minute continuity gap, duplicate, or reversal")
            window.append(candle)
            expected_minute = candle.closed_at
            if expected_minute in anchors:
                if len(window) != MINUTES_PER_THREE_DAYS:
                    raise ValueError("anchor lacks complete preceding 4320-minute window")
                vectors.append(
                    extract_three_day_chart_feature_vector(tuple(window), expected_minute)
                )

    if expected_minute != end:
        raise ValueError("archive candles do not cover exact requested bounds")
    if len(vectors) != expected_anchor_count:
        raise ValueError(
            f"three-day feature history requires exactly {expected_anchor_count} vectors"
        )
    expected_anchors = tuple(episode.anchor_at for episode in contract.episodes)
    if tuple(vector.anchor_at for vector in vectors) != expected_anchors:
        raise ValueError("feature vector anchors must exactly match daily episodes")
    if any(vector.symbol != symbol for vector in vectors):
        raise ValueError("feature vector symbol mismatch")
    if any(
        vector.window_start_at != episode.feature_start_at
        for vector, episode in zip(vectors, contract.episodes)
    ):
        raise ValueError("feature vectors must contain only pre-anchor candles")
    return tuple(vectors), tuple(provenance)


__all__ = [
    "ThreeDayFeatureHistoryContract",
    "candle_from_kline_row",
    "candles_from_kline_rows",
    "load_three_day_feature_history",
]
