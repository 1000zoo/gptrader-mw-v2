from bisect import bisect_right
from collections.abc import Iterable, Mapping
from datetime import datetime, timedelta

from src.domain.market import Symbol, Timeframe
from src.domain.market_feature import MarketFeatureSet, MarketFeatureValue
from src.domain.market_feature.market_feature_value import as_utc, require_aware_datetime


class InMemoryMarketFeatureProvider:
    def __init__(
        self,
        feature_sets: Iterable[MarketFeatureSet] = (),
        *,
        max_staleness: timedelta | None = None,
        max_staleness_by_source: Mapping[str, timedelta] | None = None,
        unavailable_sources: Iterable[str] = (),
    ) -> None:
        self._max_staleness = _validate_staleness(max_staleness, "max_staleness")
        self._max_staleness_by_source = {
            MarketFeatureValue.normalize_source(source): _validate_staleness(
                staleness,
                f"max_staleness_by_source[{source!r}]",
            )
            for source, staleness in (max_staleness_by_source or {}).items()
        }
        self._unavailable_sources = _normalize_sources(unavailable_sources)

        rows_by_key: dict[
            tuple[Symbol, Timeframe],
            list[tuple[datetime, MarketFeatureSet]],
        ] = {}
        seen: set[tuple[Symbol, Timeframe, datetime]] = set()
        for feature_set in feature_sets:
            if not isinstance(feature_set, MarketFeatureSet):
                raise TypeError("feature_sets must contain only MarketFeatureSet instances")
            conflicting_sources = sorted(
                {value.source for value in feature_set.values}.intersection(
                    self._unavailable_sources
                )
            )
            if conflicting_sources:
                sources = ", ".join(conflicting_sources)
                raise ValueError(
                    f"configured unavailable source {sources} conflicts with row value"
                )
            measured_at = as_utc(feature_set.measured_at)
            identity = (feature_set.symbol, feature_set.timeframe, measured_at)
            if identity in seen:
                raise ValueError("duplicate market feature timestamp")
            seen.add(identity)
            rows_by_key.setdefault(identity[:2], []).append((measured_at, feature_set))

        self._rows_by_key: dict[
            tuple[Symbol, Timeframe],
            tuple[tuple[datetime, ...], tuple[MarketFeatureSet, ...]],
        ] = {}
        for key, rows in rows_by_key.items():
            rows.sort(key=lambda row: row[0])
            self._rows_by_key[key] = (
                tuple(row[0] for row in rows),
                tuple(row[1] for row in rows),
            )

    def load_features(
        self,
        symbol: Symbol,
        timeframe: Timeframe,
        as_of: datetime,
    ) -> MarketFeatureSet:
        require_aware_datetime(as_of, "as_of")
        as_of_utc = as_utc(as_of)
        indexed_rows = self._rows_by_key.get((symbol, timeframe))
        if indexed_rows is None:
            return self._empty(symbol, timeframe, as_of)

        timestamps, feature_sets = indexed_rows
        row_index = bisect_right(timestamps, as_of_utc) - 1
        if row_index < 0:
            return self._empty(symbol, timeframe, as_of)

        feature_set = feature_sets[row_index]
        if (
            self._max_staleness is not None
            and as_of_utc - timestamps[row_index] > self._max_staleness
        ):
            return self._empty(
                symbol,
                timeframe,
                as_of,
                additional_unavailable_sources=_merge_sources(
                    feature_set.unavailable_sources,
                    (value.source for value in feature_set.values),
                ),
            )

        values = []
        stale_sources = []
        for value in feature_set.values:
            source_max_staleness = self._max_staleness_by_source.get(value.source)
            if (
                source_max_staleness is not None
                and as_of_utc - as_utc(value.available_at) > source_max_staleness
            ):
                if value.source not in stale_sources:
                    stale_sources.append(value.source)
                continue
            values.append(value)

        available_sources = {value.source for value in values}
        unavailable_sources = _merge_sources(
            self._unavailable_sources,
            feature_set.unavailable_sources,
            (source for source in stale_sources if source not in available_sources),
        )
        return MarketFeatureSet(
            symbol=symbol,
            timeframe=timeframe,
            measured_at=as_of,
            values=tuple(values),
            unavailable_sources=unavailable_sources,
        )

    def _empty(
        self,
        symbol: Symbol,
        timeframe: Timeframe,
        as_of: datetime,
        additional_unavailable_sources: Iterable[str] = (),
    ) -> MarketFeatureSet:
        return MarketFeatureSet(
            symbol=symbol,
            timeframe=timeframe,
            measured_at=as_of,
            values=(),
            unavailable_sources=_merge_sources(
                self._unavailable_sources,
                additional_unavailable_sources,
            ),
        )


def _validate_staleness(
    value: timedelta | None,
    field_name: str,
) -> timedelta | None:
    if value is None:
        return None
    if not isinstance(value, timedelta):
        raise TypeError(f"{field_name} must be a timedelta")
    if value < timedelta(0):
        raise ValueError(f"{field_name} must not be negative")
    return value


def _normalize_sources(sources: Iterable[str]) -> tuple[str, ...]:
    if isinstance(sources, str):
        raise TypeError("unavailable_sources must be an iterable of str")
    normalized = tuple(MarketFeatureValue.normalize_source(source) for source in sources)
    if len(normalized) != len(set(normalized)):
        raise ValueError("duplicate unavailable source")
    return normalized


def _merge_sources(*source_groups: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(source for group in source_groups for source in group))
