from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import MappingProxyType
import zipfile

import pytest

from src.domain.regime import build_daily_regime_episodes
from src.infrastructure.exchange.binance.research_data.historical_feature_loader import (
    ArchiveRequest,
    ChecksumMismatchError,
    DownloadResult,
    archive_url,
)


UTC = timezone.utc
START = datetime(2024, 7, 1, tzinfo=UTC)
END = datetime(2024, 7, 6, tzinfo=UTC)


def _request(*, symbol: str = "BTCUSDT", url: str | None = None) -> ArchiveRequest:
    period = "2024-07"
    return ArchiveRequest(
        "klines",
        symbol,
        "monthly",
        period,
        url or archive_url("klines", symbol, period, "monthly"),
    )


class _Downloader:
    def __init__(self, request: ArchiveRequest, *, member: str | None = None) -> None:
        self.request = request
        self.member = member or request.filename.removesuffix(".zip") + ".csv"

    def download(self, url: str, destination: Path, **kwargs: object) -> DownloadResult:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(destination, "w") as archive:
            archive.writestr(
                self.member,
                "open_time,open,high,low,close,volume,close_time,quote_volume,count,"
                "taker_buy_volume,taker_buy_quote_volume,ignore\n0,1,1,1,1,1,0,1,1,0,0,0\n",
            )
        return DownloadResult("downloaded", destination, "a" * 64, destination.stat().st_size)


def _rows(
    start: datetime = START,
    end: datetime = END,
    *,
    mutate: dict[datetime, tuple[str, str, str, str, str]] | None = None,
):
    mutate = mutate or {}
    at = start
    index = 0
    while at < end:
        price = f"{100 + index / 100_000:.5f}"
        open_price, high, low, close, volume = mutate.get(
            at, (price, price, price, price, str(10 + index % 7))
        )
        yield [
            str(int(at.timestamp() * 1000)), open_price, high, low, close, volume,
            "0", "1000", "1", "0", "0", "0",
        ]
        at += timedelta(minutes=1)
        index += 1


def _load(tmp_path: Path, *, rows=None, request: ArchiveRequest | None = None, downloader=None,
          expected_anchor_count: int = 2):
    from src.infrastructure.exchange.binance.research_data.three_day_feature_history import (
        load_three_day_feature_history,
    )

    request = request or _request()
    return load_three_day_feature_history(
        symbol="BTCUSDT",
        start=START,
        end=END,
        raw_root=tmp_path,
        expected_anchor_count=expected_anchor_count,
        downloader=downloader or _Downloader(request),
        request_factory=lambda *args, **kwargs: (request,),
        row_reader=lambda path: rows if rows is not None else _rows(),
    )


def test_contract_freezes_exact_daily_episodes_for_both_approved_windows() -> None:
    from src.infrastructure.exchange.binance.research_data.three_day_feature_history import (
        ThreeDayFeatureHistoryContract,
    )

    windows = (
        (datetime(2024, 7, 1, tzinfo=UTC), datetime(2026, 7, 1, tzinfo=UTC), 727),
        (datetime(2021, 1, 1, tzinfo=UTC), datetime(2024, 7, 1, tzinfo=UTC), 1274),
    )
    for start, end, count in windows:
        episodes = build_daily_regime_episodes(start, end)
        contract = ThreeDayFeatureHistoryContract(start, end, episodes)
        assert len(contract.episodes) == count
        assert contract.episodes[0].feature_start_at == start
        assert contract.episodes[0].anchor_at == start + timedelta(days=3)
        assert contract.episodes[-1].anchor_at == end - timedelta(days=1)
        assert contract.episodes[-1].outcome_end_at == end


def test_contract_rejects_noncanonical_bounds_order_and_episode_drift() -> None:
    from src.infrastructure.exchange.binance.research_data.three_day_feature_history import (
        ThreeDayFeatureHistoryContract,
    )

    episodes = build_daily_regime_episodes(START, END)
    for start, end, supplied in (
        (START.replace(tzinfo=None), END, episodes),
        (START + timedelta(minutes=1), END, episodes),
        (END, START, episodes),
        (START, END, episodes[:-1]),
    ):
        with pytest.raises(ValueError):
            ThreeDayFeatureHistoryContract(start, end, supplied)


def test_loader_returns_exact_vectors_and_immutable_stable_provenance(tmp_path: Path) -> None:
    vectors, provenance = _load(tmp_path)

    assert tuple(vector.anchor_at for vector in vectors) == (
        START + timedelta(days=3), START + timedelta(days=4)
    )
    assert isinstance(vectors, tuple)
    assert isinstance(provenance, tuple)
    assert len(provenance) == 1
    assert isinstance(provenance[0], MappingProxyType)
    assert provenance[0] == {
        "period": "2024-07",
        "url": _request().url,
        "sha256": "a" * 64,
        "bytes": provenance[0]["bytes"],
        "member_identity": _request().filename,
    }
    assert tuple(provenance[0]) == ("period", "url", "sha256", "bytes", "member_identity")
    with pytest.raises(TypeError):
        provenance[0]["status"] = "cached"


@pytest.mark.parametrize("expected", [0, -1, True, 2.0, "2"])
def test_loader_rejects_invalid_expected_anchor_count(tmp_path: Path, expected: object) -> None:
    with pytest.raises(ValueError, match="expected_anchor_count"):
        _load(tmp_path, expected_anchor_count=expected)


def test_loader_rejects_incorrect_actual_count(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="exactly 3"):
        _load(tmp_path, expected_anchor_count=3)


def test_loader_propagates_checksum_failure(tmp_path: Path) -> None:
    class BadDownloader:
        def download(self, *args: object, **kwargs: object) -> DownloadResult:
            raise ChecksumMismatchError("fixture checksum mismatch")

    with pytest.raises(ChecksumMismatchError, match="checksum"):
        _load(tmp_path, downloader=BadDownloader())


@pytest.mark.parametrize("kind", ["gap", "duplicate", "reversed"])
def test_loader_rejects_any_break_in_exact_utc_continuity(tmp_path: Path, kind: str) -> None:
    rows = list(_rows())
    if kind == "gap":
        del rows[10]
    elif kind == "duplicate":
        rows.insert(11, rows[10])
    else:
        rows[10], rows[11] = rows[11], rows[10]
    with pytest.raises(ValueError, match="continuity"):
        _load(tmp_path, rows=rows)


@pytest.mark.parametrize(
    "archive_request",
    [
        _request(symbol="ETHUSDT"),
        _request(url="https://example.test/not-canonical.zip"),
    ],
)
def test_loader_rejects_wrong_request_symbol_or_url(tmp_path: Path, archive_request: ArchiveRequest) -> None:
    with pytest.raises(ValueError, match="request"):
        _load(tmp_path, request=archive_request)


def test_loader_rejects_noncanonical_request_period(tmp_path: Path) -> None:
    period = "2024-7"
    request = ArchiveRequest(
        "klines", "BTCUSDT", "monthly", period,
        archive_url("klines", "BTCUSDT", period, "monthly"),
    )
    with pytest.raises(ValueError, match="request"):
        _load(tmp_path, request=request)


def test_loader_rejects_wrong_archive_member(tmp_path: Path) -> None:
    request = _request()
    downloader = _Downloader(request, member="wrong.csv")
    with pytest.raises(ValueError, match="member"):
        _load(tmp_path, request=request, downloader=downloader)


def test_loader_excludes_out_of_window_rows_and_anchor_candle_from_prior_vector(tmp_path: Path) -> None:
    outside_before = list(_rows(START - timedelta(minutes=1), START))
    outside_after = list(_rows(END, END + timedelta(minutes=1)))
    baseline, _ = _load(tmp_path / "baseline", rows=(*outside_before, *_rows(), *outside_after))
    anchor = START + timedelta(days=3)
    changed_rows = (*outside_before, *_rows(mutate={anchor: ("500", "500", "500", "500", "10")}), *outside_after)
    changed, _ = _load(tmp_path / "changed", rows=changed_rows)

    assert changed[0] == baseline[0]
    assert changed[1] != baseline[1]


def test_loader_rejects_nonfinite_kline_data(tmp_path: Path) -> None:
    rows = _rows(mutate={START: ("NaN", "NaN", "NaN", "NaN", "10")})
    with pytest.raises(ValueError):
        _load(tmp_path, rows=rows)
