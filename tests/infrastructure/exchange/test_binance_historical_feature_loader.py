from __future__ import annotations

import hashlib
import io
import json
import os
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal
from urllib.error import HTTPError

import pytest

from src.infrastructure.exchange.binance.research_data import historical_feature_loader as loader_module
from src.infrastructure.exchange.binance.research_data.historical_feature_loader import (
    ArchiveDownloader,
    ArchiveRequest,
    ChecksumMismatchError,
    DownloadResult,
    FeatureRow,
    HistoricalFeatureLoader,
    aggregate_aggtrades,
    archive_url,
    iter_archive_requests,
    merge_feature_rows,
    parse_funding_rows,
    parse_kline_feature_row,
    parse_price_kline_row,
    write_feature_cache,
)


UTC = timezone.utc


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(UTC)


class _Response(io.BytesIO):
    def __init__(self, body: bytes, *, headers=None):
        super().__init__(body)
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False


def test_archive_urls_use_binance_usdm_filename_patterns():
    assert archive_url("klines", "BTCUSDT", "2026-01", "monthly").endswith(
        "/monthly/klines/BTCUSDT/1m/BTCUSDT-1m-2026-01.zip"
    )
    assert archive_url("aggTrades", "BTCUSDT", "2026-01-02", "daily").endswith(
        "/daily/aggTrades/BTCUSDT/BTCUSDT-aggTrades-2026-01-02.zip"
    )
    assert archive_url(
        "markPriceKlines", "BTCUSDT", "2026-01", "monthly"
    ).endswith(
        "/monthly/markPriceKlines/BTCUSDT/1m/BTCUSDT-1m-2026-01.zip"
    )
    assert archive_url("fundingRate", "BTCUSDT", "2026-01", "monthly").endswith(
        "/monthly/fundingRate/BTCUSDT/BTCUSDT-fundingRate-2026-01.zip"
    )
    with pytest.raises(ValueError, match="monthly only"):
        archive_url("fundingRate", "BTCUSDT", "2026-01-02", "daily")


def test_archive_periods_are_end_exclusive_and_current_month_uses_daily_fallback():
    requests = list(
        iter_archive_requests(
            "klines",
            "BTCUSDT",
            _dt("2026-05-15T00:00:00+00:00"),
            _dt("2026-07-03T00:00:00+00:00"),
            now=_dt("2026-07-04T12:00:00+00:00"),
        )
    )

    assert [(item.granularity, item.period) for item in requests] == [
        ("monthly", "2026-05"),
        ("monthly", "2026-06"),
        ("daily", "2026-07-01"),
        ("daily", "2026-07-02"),
    ]


def test_funding_current_partial_period_is_not_planned_as_daily_archive():
    requests = list(
        iter_archive_requests(
            "fundingRate",
            "BTCUSDT",
            _dt("2026-06-01T00:00:00+00:00"),
            _dt("2026-07-03T00:00:00+00:00"),
            now=_dt("2026-07-04T12:00:00+00:00"),
        )
    )
    assert [(item.granularity, item.period) for item in requests] == [
        ("monthly", "2026-06")
    ]


def test_downloader_streams_checksum_verified_file_and_renames_atomically(tmp_path):
    payload = b"archive-payload"
    digest = hashlib.sha256(payload).hexdigest()
    calls = []

    def opener(url, timeout):
        calls.append(url)
        body = f"{digest}  sample.zip\n".encode() if url.endswith(".CHECKSUM") else payload
        return _Response(body)

    destination = tmp_path / "sample.zip"
    result = ArchiveDownloader(opener=opener, chunk_size=3).download(
        "https://data.test/sample.zip", destination
    )

    assert result.status == "downloaded"
    assert result.sha256 == digest
    assert destination.read_bytes() == payload
    assert not destination.with_suffix(".zip.tmp").exists()
    assert calls == [
        "https://data.test/sample.zip",
        "https://data.test/sample.zip.CHECKSUM",
    ]


def test_downloader_checksum_failure_preserves_existing_destination(tmp_path):
    destination = tmp_path / "sample.zip"
    destination.write_bytes(b"old")

    def opener(url, timeout):
        if url.endswith(".CHECKSUM"):
            return _Response(("0" * 64 + "  sample.zip\n").encode())
        return _Response(b"new")

    with pytest.raises(ChecksumMismatchError):
        ArchiveDownloader(opener=opener).download("https://data.test/sample.zip", destination)

    assert destination.read_bytes() == b"old"
    assert not destination.with_suffix(".zip.tmp").exists()


def test_downloader_returns_explicit_unavailable_for_404(tmp_path):
    def opener(url, timeout):
        raise HTTPError(url, 404, "missing", {}, None)

    result = ArchiveDownloader(opener=opener).download(
        "https://data.test/missing.zip", tmp_path / "missing.zip"
    )
    assert result.status == "unavailable"


@pytest.mark.parametrize(
    "checksum_body",
    [
        ("a" * 64 + "\n").encode(),
        ("z" * 64 + "  sample.zip\n").encode(),
        ("a" * 64 + "  other.zip\n").encode(),
    ],
)
def test_checksum_requires_valid_hash_and_exact_archive_filename(
    tmp_path, checksum_body
):
    payload = b"payload"

    def opener(url, timeout):
        return _Response(checksum_body if url.endswith(".CHECKSUM") else payload)

    with pytest.raises(ValueError, match="checksum"):
        ArchiveDownloader(opener=opener).download(
            "https://data.test/sample.zip", tmp_path / "sample.zip"
        )


@pytest.mark.parametrize(
    ("headers", "chunk_size"),
    [({"Content-Length": "11"}, 20), ({}, 3)],
)
def test_downloader_fails_closed_when_archive_exceeds_byte_budget(
    tmp_path, headers, chunk_size
):
    payload = b"01234567890"

    def opener(url, timeout):
        if url.endswith(".CHECKSUM"):
            raise AssertionError("over-budget archives must not reach checksum promotion")
        return _Response(payload, headers=headers)

    destination = tmp_path / "large.zip"
    result = ArchiveDownloader(opener=opener, chunk_size=chunk_size).download(
        "https://data.test/large.zip", destination, max_bytes=10
    )

    assert result.status == "budget_skipped"
    assert result.bytes_received <= len(payload)
    assert not destination.exists()
    assert not destination.with_suffix(".zip.tmp").exists()


@pytest.mark.parametrize(
    ("member", "body", "message"),
    [
        ("wrong-member.csv", "bad,header\nnot,a,kline\n", "expected CSV member"),
        (
            "BTCUSDT-1m-2026-01.csv",
            "wrong,header\n1767225600000,1,1,1,1,1,1,1,1,1,1,0\n",
            "unexpected klines CSV header",
        ),
        (
            "BTCUSDT-1m-2026-01.csv",
            "1767225600000,1,1\n",
            "must contain at least 11 fields",
        ),
    ],
)
def test_checksum_valid_malformed_archive_is_rejected_before_atomic_rename(
    tmp_path, member, body, message
):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr(member, body)
    payload = output.getvalue()
    digest = hashlib.sha256(payload).hexdigest()

    def opener(url, timeout):
        if url.endswith(".CHECKSUM"):
            return _Response(f"{digest}  BTCUSDT-1m-2026-01.zip\n".encode())
        return _Response(payload)

    destination = tmp_path / "BTCUSDT-1m-2026-01.zip"
    with pytest.raises(ValueError, match=message):
        ArchiveDownloader(opener=opener).download(
            "https://data.test/BTCUSDT-1m-2026-01.zip",
            destination,
            source="klines",
        )

    assert not destination.exists()
    assert not destination.with_suffix(".zip.tmp").exists()


def test_checksum_valid_archive_with_malformed_later_row_is_never_promoted(tmp_path):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr(
            "BTCUSDT-1m-2026-01.csv",
            (
                "1767225600000,100,110,90,105,10,1767225659999,1000,12,7,700,0\n"
                "1767225660000,malformed,later,row\n"
            ),
        )
    payload = output.getvalue()
    digest = hashlib.sha256(payload).hexdigest()

    def opener(url, timeout):
        if url.endswith(".CHECKSUM"):
            return _Response(f"{digest}  BTCUSDT-1m-2026-01.zip\n".encode())
        return _Response(payload)

    destination = tmp_path / "BTCUSDT-1m-2026-01.zip"
    with pytest.raises(ValueError, match="must contain at least 11 fields"):
        ArchiveDownloader(opener=opener).download(
            "https://data.test/BTCUSDT-1m-2026-01.zip",
            destination,
            source="klines",
        )

    assert not destination.exists()
    assert not destination.with_suffix(".zip.tmp").exists()


def test_kline_parser_exposes_taker_flow_trade_count_and_safe_imbalance():
    row = parse_kline_feature_row(
        [
            "1767225600000", "100", "110", "90", "105", "10", "1767225659999",
            "1000", "12", "7", "700", "0",
        ]
    )

    assert row.minute_end == _dt("2026-01-01T00:01:00+00:00")
    assert row.available_at == row.minute_end
    assert row.features["trade_count"] == Decimal("12")
    assert row.features["taker_buy_base_volume"] == Decimal("7")
    assert row.features["taker_sell_base_volume"] == Decimal("3")
    assert row.features["taker_buy_quote_volume"] == Decimal("700")
    assert row.features["taker_sell_quote_volume"] == Decimal("300")
    assert row.features["taker_imbalance"] == Decimal("0.4")

    zero = parse_kline_feature_row(
        ["1767225600000", "1", "1", "1", "1", "0", "0", "0", "0", "0", "0", "0"]
    )
    assert zero.features["taker_imbalance"] == Decimal("0")


@pytest.mark.parametrize(
    ("index", "value"),
    [
        (1, "0"),
        (2, "-1"),
        (5, "-1"),
        (7, "-1"),
        (8, "1.5"),
        (8, "-1"),
        (9, "11"),
        (10, "1001"),
    ],
)
def test_kline_parser_rejects_invalid_numeric_domains(index, value):
    row = [
        "1767225600000", "100", "110", "90", "105", "10",
        "1767225659999", "1000", "12", "7", "700", "0",
    ]
    row[index] = value
    with pytest.raises(ValueError):
        parse_kline_feature_row(row)


def test_aggtrades_stream_by_minute_and_map_buyer_maker_to_aggressive_sell():
    trades = iter(
        [
            ["10", "100", "2", "1000", "1001", "1767225600001", "true"],
            ["11", "110", "3", "1002", "1004", "1767225659999", "false"],
            ["12", "120", "1", "1005", "1005", "1767225660001", "false"],
        ]
    )
    rows = aggregate_aggtrades(trades)
    first = next(rows)

    assert first.minute_end == _dt("2026-01-01T00:01:00+00:00")
    assert first.available_at == first.minute_end
    assert first.features == {
        "aggressive_buy_base_volume": Decimal("3"),
        "aggressive_sell_base_volume": Decimal("2"),
        "aggressive_buy_quote_notional": Decimal("330"),
        "aggressive_sell_quote_notional": Decimal("200"),
        "aggregate_trade_count": Decimal("2"),
        "actual_trade_count": Decimal("5"),
        "cvd_delta": Decimal("1"),
        "aggtrade_vwap": Decimal("106"),
        "trade_intensity": Decimal("5"),
    }
    assert next(rows).minute_end == _dt("2026-01-01T00:02:00+00:00")


def test_aggtrade_actual_count_sums_each_aggregate_range_without_spanning_gaps():
    row = next(
        aggregate_aggtrades(
            [
                ["10", "100", "1", "1", "1", "1767225600001", "false"],
                ["11", "100", "1", "10", "10", "1767225600002", "false"],
            ]
        )
    )
    assert row.features["actual_trade_count"] == Decimal("2")


def test_aggtrade_rejects_reversed_first_and_last_trade_ids():
    with pytest.raises(ValueError, match="reversed trade ID range"):
        next(
            aggregate_aggtrades(
                [["10", "100", "1", "11", "10", "1767225600001", "false"]]
            )
        )


@pytest.mark.parametrize("token", ["yes", "1", "", "buyer"])
def test_aggtrade_buyer_maker_token_accepts_only_true_or_false(token):
    with pytest.raises(ValueError, match="buyer-maker"):
        next(
            aggregate_aggtrades(
                [["10", "100", "1", "10", "10", "1767225600001", token]]
            )
        )


@pytest.mark.parametrize(
    ("index", "value"),
    [
        (0, "-1"),
        (0, "1.5"),
        (1, "0"),
        (2, "-1"),
        (3, "-1"),
        (4, "-1"),
    ],
)
def test_aggtrade_parser_rejects_invalid_numeric_domains(index, value):
    row = ["10", "100", "1", "10", "10", "1767225600001", "false"]
    row[index] = value
    with pytest.raises(ValueError):
        next(aggregate_aggtrades([row]))


@pytest.mark.parametrize(
    ("second_row", "message"),
    [
        (
            "11,100,1,11,11,1767225600000,false",
            "trade time",
        ),
        (
            "9,100,1,9,9,1767225600002,false",
            "aggregate trade ID",
        ),
        (
            "11,100,1,9,9,1767225600002,false",
            "underlying trade ID",
        ),
    ],
)
def test_archive_validation_rejects_cross_row_aggtrade_order_corruption(
    tmp_path, second_row, message
):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr(
            "BTCUSDT-aggTrades-2026-01.csv",
            "10,100,1,10,10,1767225600001,false\n" + second_row + "\n",
        )
    payload = output.getvalue()
    digest = hashlib.sha256(payload).hexdigest()

    def opener(url, timeout):
        if url.endswith(".CHECKSUM"):
            return _Response(
                f"{digest}  BTCUSDT-aggTrades-2026-01.zip\n".encode()
            )
        return _Response(payload)

    destination = tmp_path / "BTCUSDT-aggTrades-2026-01.zip"
    with pytest.raises(ValueError, match=message):
        ArchiveDownloader(opener=opener).download(
            "https://data.test/BTCUSDT-aggTrades-2026-01.zip",
            destination,
            source="aggTrades",
        )

    assert not destination.exists()
    assert not destination.with_suffix(".zip.tmp").exists()


@pytest.mark.parametrize(
    ("source", "feature"),
    [
        ("markPriceKlines", "mark_price"),
        ("indexPriceKlines", "index_price"),
        ("premiumIndexKlines", "premium_index"),
    ],
)
def test_reference_price_klines_publish_close_at_minute_end(source, feature):
    row = parse_price_kline_row(
        ["1767225600000", "1", "2", "0.5", "1.25"], source=source
    )
    assert row.features == {feature: Decimal("1.25")}
    assert row.available_at == _dt("2026-01-01T00:01:00+00:00")


@pytest.mark.parametrize("close", ["0", "-0.00025"])
def test_premium_index_kline_accepts_zero_and_negative_finite_close(close):
    row = parse_price_kline_row(
        ["1767225600000", "1", "2", "0.5", close],
        source="premiumIndexKlines",
    )
    assert row.features["premium_index"] == Decimal(close)


@pytest.mark.parametrize("source", ["markPriceKlines", "indexPriceKlines"])
@pytest.mark.parametrize("close", ["0", "-1"])
def test_mark_and_index_klines_reject_nonpositive_close(source, close):
    with pytest.raises(ValueError, match="positive"):
        parse_price_kline_row(
            ["1767225600000", "1", "2", "0.5", close],
            source=source,
        )


def test_funding_asof_alignment_rejects_future_and_stale_values():
    rows = list(
        parse_funding_rows(
            [
                {"fundingTime": 1767225600000, "fundingRate": "0.0001"},
                {"fundingTime": 1767254400000, "fundingRate": "0.0002"},
            ]
        )
    )
    candle_close = _dt("2026-01-01T04:00:00+00:00")
    merged = list(
        merge_feature_rows(
            [_base_row(candle_close)],
            {"fundingRate": rows},
            requested_sources=("klines", "fundingRate"),
            symbol="BTCUSDT",
        )
    )[0]
    assert merged.require("funding_rate").value == Decimal("0.0001")
    assert merged.require("funding_rate").available_at <= candle_close

    stale_close = _dt("2026-01-01T08:00:00.001+00:00")
    stale = list(
        merge_feature_rows(
            [_base_row(stale_close)],
            {"fundingRate": rows[:1]},
            requested_sources=("klines", "fundingRate"),
            symbol="BTCUSDT",
        )
    )[0]
    assert "fundingRate" in stale.unavailable_sources


def test_funding_archive_value_at_final_close_is_included(tmp_path):
    archive_path = tmp_path / "BTCUSDT-fundingRate-2026-01.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr(
            "BTCUSDT-fundingRate-2026-01.csv",
            "1767225660000,8,0.0001\n",
        )
    loader = HistoricalFeatureLoader(tmp_path)

    rows = list(
        loader._parse_archive(
            "fundingRate",
            archive_path,
            _dt("2026-01-01T00:00:00+00:00"),
            _dt("2026-01-01T00:01:00+00:00"),
        )
    )

    assert len(rows) == 1
    assert rows[0].available_at == _dt("2026-01-01T00:01:00+00:00")


def test_current_partial_funding_uses_injected_public_endpoint(tmp_path):
    calls = []

    class UnavailableDownloader:
        def download(self, url, destination, **kwargs):
            return DownloadResult("unavailable", destination)

    def api_get(path, params):
        calls.append((path, params))
        return [{"fundingTime": 1782864000000, "fundingRate": "0.0001"}]

    loader = HistoricalFeatureLoader(
        tmp_path,
        downloader=UnavailableDownloader(),
        clock=lambda: _dt("2026-07-02T12:00:00+00:00"),
        api_get=api_get,
    )
    loader.build_cache(
        symbol="BTCUSDT",
        start=_dt("2026-07-01T00:00:00+00:00"),
        end=_dt("2026-07-02T00:00:00+00:00"),
        sources=("klines", "fundingRate"),
    )

    assert calls[0][0] == "/fapi/v1/fundingRate"
    assert calls[0][1] == {
        "symbol": "BTCUSDT",
        "startTime": 1782835200000,
        "endTime": 1782950400000,
        "limit": 1000,
    }


def test_missing_historical_funding_archive_uses_rest_with_lookback_and_provenance(
    tmp_path,
):
    calls = []

    class UnavailableDownloader:
        def download(self, url, destination, **kwargs):
            return DownloadResult("unavailable", destination)

    payload = [{"fundingTime": 1781049600000, "fundingRate": "0.0001"}]

    def api_get(path, params):
        calls.append((path, dict(params)))
        return payload

    loader = HistoricalFeatureLoader(
        tmp_path,
        downloader=UnavailableDownloader(),
        clock=lambda: _dt("2026-07-02T12:00:00+00:00"),
        api_get=api_get,
    )
    _, manifest_path = loader.build_cache(
        symbol="BTCUSDT",
        start=_dt("2026-06-10T00:00:00+00:00"),
        end=_dt("2026-06-11T00:00:00+00:00"),
        sources=("klines", "fundingRate"),
    )

    assert calls == [
        (
            "/fapi/v1/fundingRate",
            {
                "symbol": "BTCUSDT",
                "startTime": 1781020800000,
                "endTime": 1781136000000,
                "limit": 1000,
            },
        )
    ]
    canonical = b'[{"fundingRate":"0.0001","fundingTime":1781049600000}]'
    rest_files = list((tmp_path / "raw" / "fundingRate" / "BTCUSDT" / "rest").glob("*.json"))
    assert len(rest_files) == 1
    assert rest_files[0].read_bytes() == canonical
    manifest = json.loads(manifest_path.read_text())
    rest_key = next(key for key in manifest["input_hashes"] if key.startswith("rest/"))
    assert manifest["input_hashes"][rest_key] == hashlib.sha256(canonical).hexdigest()
    assert manifest["provenance"][rest_key]["request"]["path"] == "/fapi/v1/fundingRate"


def test_duplicate_missing_funding_archive_requests_issue_one_rest_call(
    tmp_path, monkeypatch
):
    calls = []
    request = ArchiveRequest(
        source="fundingRate",
        symbol="BTCUSDT",
        granularity="monthly",
        period="2026-06",
        url="https://data.test/BTCUSDT-fundingRate-2026-06.zip",
    )

    def duplicate_requests(source, symbol, start, end, *, now):
        return iter((request, request)) if source == "fundingRate" else iter(())

    class UnavailableDownloader:
        def download(self, url, destination, **kwargs):
            return DownloadResult("unavailable", destination)

    monkeypatch.setattr(loader_module, "iter_archive_requests", duplicate_requests)
    loader = HistoricalFeatureLoader(
        tmp_path,
        downloader=UnavailableDownloader(),
        clock=lambda: _dt("2026-07-02T12:00:00+00:00"),
        api_get=lambda path, params: calls.append((path, params)) or [],
    )
    loader.build_cache(
        symbol="BTCUSDT",
        start=_dt("2026-06-10T00:00:00+00:00"),
        end=_dt("2026-06-11T00:00:00+00:00"),
        sources=("klines", "fundingRate"),
    )

    assert len(calls) == 1


def test_rest_funding_paginates_persists_and_hashes_every_page(tmp_path):
    calls = []
    first_cursor = 1782835200000
    first_page = [
        {"fundingTime": first_cursor + index, "fundingRate": "0.0001"}
        for index in range(1000)
    ]
    second_page = [
        {"fundingTime": first_cursor + 1000, "fundingRate": "0.0002"}
    ]
    pages = iter((first_page, second_page))

    class UnavailableDownloader:
        def download(self, url, destination, **kwargs):
            return DownloadResult("unavailable", destination)

    def api_get(path, params):
        calls.append((path, dict(params)))
        return next(pages)

    loader = HistoricalFeatureLoader(
        tmp_path,
        downloader=UnavailableDownloader(),
        clock=lambda: _dt("2026-07-02T12:00:00+00:00"),
        api_get=api_get,
    )
    _, manifest_path = loader.build_cache(
        symbol="BTCUSDT",
        start=_dt("2026-07-01T00:00:00+00:00"),
        end=_dt("2026-07-02T00:00:00+00:00"),
        sources=("klines", "fundingRate"),
    )

    assert len(calls) == 2
    assert calls[0][1]["startTime"] == first_cursor
    assert calls[1][1]["startTime"] == first_cursor + 1000
    rest_dir = tmp_path / "raw" / "fundingRate" / "BTCUSDT" / "rest"
    rest_files = sorted(rest_dir.glob("*.json"))
    assert len(rest_files) == 2
    persisted_rows = [row for path in rest_files for row in json.loads(path.read_text())]
    assert len(persisted_rows) == 1001
    assert len({row["fundingTime"] for row in persisted_rows}) == 1001

    manifest = json.loads(manifest_path.read_text())
    rest_hashes = {
        key: value
        for key, value in manifest["input_hashes"].items()
        if key.startswith("rest/")
    }
    rest_provenance = {
        key: value
        for key, value in manifest["provenance"].items()
        if key.startswith("rest/")
    }
    assert len(rest_hashes) == 2
    assert len(rest_provenance) == 2
    assert set(rest_hashes.values()) == {
        hashlib.sha256(path.read_bytes()).hexdigest() for path in rest_files
    }


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (
            [
                {"fundingTime": 1782835200002, "fundingRate": "0.0001"},
                {"fundingTime": 1782835200001, "fundingRate": "0.0001"},
            ],
            "strictly ordered",
        ),
        (
            [{"fundingTime": 1782835199999, "fundingRate": "0.0001"}],
            "outside requested bounds",
        ),
    ],
)
def test_rest_funding_rejects_unsorted_or_out_of_bounds_pages(
    tmp_path, payload, message
):
    loader = _current_funding_loader(tmp_path, lambda path, params: payload)
    with pytest.raises(ValueError, match=message):
        loader.build_cache(
            symbol="BTCUSDT",
            start=_dt("2026-07-01T00:00:00+00:00"),
            end=_dt("2026-07-02T00:00:00+00:00"),
            sources=("klines", "fundingRate"),
        )


def test_rest_funding_repeated_full_page_fails_when_cursor_cannot_advance(tmp_path):
    first_cursor = 1782835200000
    page = [
        {"fundingTime": first_cursor + index, "fundingRate": "0.0001"}
        for index in range(1000)
    ]
    loader = _current_funding_loader(tmp_path, lambda path, params: page)

    with pytest.raises(ValueError, match="did not advance"):
        loader.build_cache(
            symbol="BTCUSDT",
            start=_dt("2026-07-01T00:00:00+00:00"),
            end=_dt("2026-07-02T00:00:00+00:00"),
            sources=("klines", "fundingRate"),
        )


def test_rest_funding_pagination_has_defensive_page_cap(tmp_path):
    first_cursor = 1782835200000
    page = [
        {"fundingTime": first_cursor + index, "fundingRate": "0.0001"}
        for index in range(1000)
    ]
    loader = _current_funding_loader(
        tmp_path,
        lambda path, params: page,
        funding_max_pages=1,
    )

    with pytest.raises(ValueError, match="page limit"):
        loader.build_cache(
            symbol="BTCUSDT",
            start=_dt("2026-07-01T00:00:00+00:00"),
            end=_dt("2026-07-02T00:00:00+00:00"),
            sources=("klines", "fundingRate"),
        )


def test_loader_passes_aggtrade_budget_and_records_budget_skips(tmp_path):
    calls = []

    class BudgetDownloader:
        def download(self, url, destination, **kwargs):
            calls.append((url, kwargs))
            status = "budget_skipped" if "aggTrades" in url else "unavailable"
            return DownloadResult(status, destination, bytes_received=101)

    loader = HistoricalFeatureLoader(
        tmp_path,
        downloader=BudgetDownloader(),
        aggtrades_max_bytes=100,
        clock=lambda: _dt("2026-07-02T12:00:00+00:00"),
    )
    _, manifest_path = loader.build_cache(
        symbol="BTCUSDT",
        start=_dt("2026-06-01T00:00:00+00:00"),
        end=_dt("2026-06-02T00:00:00+00:00"),
        sources=("klines", "aggTrades"),
    )

    agg_call = next(item for item in calls if "aggTrades" in item[0])
    assert agg_call[1]["max_bytes"] == 100
    manifest = json.loads(manifest_path.read_text())
    assert manifest["source_coverage"]["aggTrades"]["budget_skipped_archives"] == [
        "2026-06"
    ]


def test_merge_keeps_missing_sources_unavailable_and_rejects_future_features():
    close = _dt("2026-01-01T00:01:00+00:00")
    merged = list(
        merge_feature_rows(
            [_base_row(close)],
            {},
            requested_sources=("klines", "aggTrades", "markPriceKlines"),
            symbol="BTCUSDT",
        )
    )[0]
    assert set(merged.unavailable_sources) == {"aggTrades", "markPriceKlines"}
    assert merged.get("aggressive_buy_base_volume") is None

    future = FeatureRow(
        minute_end=close,
        available_at=_dt("2026-01-01T00:01:00.001+00:00"),
        source="markPriceKlines",
        features={"mark_price": Decimal("100")},
    )
    with pytest.raises(ValueError, match="future"):
        list(
            merge_feature_rows(
                [_base_row(close)],
                {"markPriceKlines": [future]},
                requested_sources=("klines", "markPriceKlines"),
                symbol="BTCUSDT",
            )
        )


def test_merge_rejects_conflicting_rows_for_same_source_and_minute():
    close = _dt("2026-01-01T00:01:00+00:00")
    first = FeatureRow(close, close, "markPriceKlines", {"mark_price": Decimal("100")})
    conflict = FeatureRow(close, close, "markPriceKlines", {"mark_price": Decimal("101")})

    with pytest.raises(ValueError, match="duplicate markPriceKlines conflict"):
        list(
            merge_feature_rows(
                [_base_row(close)],
                {"markPriceKlines": [first, conflict]},
                requested_sources=("klines", "markPriceKlines"),
                symbol="BTCUSDT",
            )
        )


def test_funding_duplicate_calc_times_allow_identical_and_reject_conflicts():
    close = _dt("2026-01-01T00:01:00+00:00")
    identical = list(
        parse_funding_rows(
            [
                {"fundingTime": 1767225600000, "fundingRate": "0.0001"},
                {"fundingTime": 1767225600000, "fundingRate": "0.0001"},
            ]
        )
    )
    merged = list(
        merge_feature_rows(
            [_base_row(close)],
            {"fundingRate": identical},
            requested_sources=("klines", "fundingRate"),
            symbol="BTCUSDT",
        )
    )
    assert merged[0].require("funding_rate").value == Decimal("0.0001")

    conflicting = list(
        parse_funding_rows(
            [
                {"fundingTime": 1767225600000, "fundingRate": "0.0001"},
                {"fundingTime": 1767225600000, "fundingRate": "0.0002"},
            ]
        )
    )
    with pytest.raises(ValueError, match="duplicate fundingRate conflict"):
        list(
            merge_feature_rows(
                [_base_row(close)],
                {"fundingRate": conflicting},
                requested_sources=("klines", "fundingRate"),
                symbol="BTCUSDT",
            )
        )


@pytest.mark.parametrize("rate", ["NaN", "Infinity", "-Infinity"])
def test_funding_parser_rejects_nonfinite_rates(rate):
    with pytest.raises(ValueError, match="finite"):
        list(
            parse_funding_rows(
                [{"fundingTime": 1767225600000, "fundingRate": rate}]
            )
        )


def test_cache_manifest_contains_coverage_raw_and_output_hashes(tmp_path):
    rows = [_base_feature_set(_dt("2026-01-01T00:01:00+00:00"))]
    jsonl_path, manifest_path = write_feature_cache(
        rows,
        cache_root=tmp_path,
        symbol="BTCUSDT",
        start=_dt("2026-01-01T00:00:00+00:00"),
        end=_dt("2026-01-01T00:02:00+00:00"),
        requested_sources=("klines", "aggTrades"),
        raw_hashes={"raw/klines.zip": "abc123"},
        source_archive_statuses={"aggTrades": {"budget_skipped": ["2026-01"]}},
    )

    manifest = json.loads(manifest_path.read_text())
    assert jsonl_path.parent == tmp_path / "features" / "BTCUSDT" / "1m"
    assert manifest["symbol"] == "BTCUSDT"
    assert manifest["requested_range"]["end"] == "2026-01-01T00:02:00+00:00"
    assert manifest["actual_range"]["min"] == "2026-01-01T00:01:00+00:00"
    assert manifest["row_count"] == 1
    assert manifest["source_coverage"] == {
        "aggTrades": {
            "available_rows": 0,
            "budget_skipped_archives": ["2026-01"],
            "unavailable_rows": 1,
        },
        "klines": {
            "available_rows": 1,
            "budget_skipped_archives": [],
            "unavailable_rows": 0,
        },
    }
    assert manifest["raw_hashes"] == {"raw/klines.zip": "abc123"}
    assert manifest["output_hash"] == hashlib.sha256(jsonl_path.read_bytes()).hexdigest()


def test_cache_identity_separates_source_budget_and_schema_variants(tmp_path):
    common = {
        "cache_root": tmp_path,
        "symbol": "BTCUSDT",
        "start": _dt("2026-01-01T00:00:00+00:00"),
        "end": _dt("2026-01-01T00:02:00+00:00"),
        "raw_hashes": {},
    }
    first = write_feature_cache(
        [_base_feature_set(_dt("2026-01-01T00:01:00+00:00"))],
        requested_sources=("aggTrades", "klines"),
        aggtrades_max_bytes=100,
        schema_version="v1",
        **common,
    )
    reordered = write_feature_cache(
        [_base_feature_set(_dt("2026-01-01T00:01:00+00:00"))],
        requested_sources=("klines", "aggTrades"),
        aggtrades_max_bytes=100,
        schema_version="v1",
        **common,
    )
    other_budget = write_feature_cache(
        [_base_feature_set(_dt("2026-01-01T00:01:00+00:00"))],
        requested_sources=("klines", "aggTrades"),
        aggtrades_max_bytes=101,
        schema_version="v1",
        **common,
    )
    other_schema = write_feature_cache(
        [_base_feature_set(_dt("2026-01-01T00:01:00+00:00"))],
        requested_sources=("klines", "aggTrades"),
        aggtrades_max_bytes=100,
        schema_version="v2",
        **common,
    )

    assert first == reordered
    assert first[0] != other_budget[0]
    assert first[0] != other_schema[0]
    manifest = json.loads(first[1].read_text())
    assert manifest["cache_identity"]["sources"] == ["klines", "aggTrades"]
    assert manifest["cache_identity_hash"] in first[0].name


def test_failed_prepublication_rebuild_preserves_prior_pair_and_cleans_temps(tmp_path):
    kwargs = _cache_write_kwargs(tmp_path)
    jsonl_path, manifest_path = write_feature_cache(
        [_base_feature_set(_dt("2026-01-01T00:01:00+00:00"))],
        **kwargs,
    )
    assert loader_module.validate_cache_pair(jsonl_path, manifest_path)

    def failing_rows():
        yield _base_feature_set(_dt("2026-01-01T00:01:00+00:00"))
        raise RuntimeError("injected write failure")

    with pytest.raises(RuntimeError, match="injected write failure"):
        write_feature_cache(failing_rows(), **kwargs)

    assert loader_module.validate_cache_pair(jsonl_path, manifest_path)
    assert not list(jsonl_path.parent.glob("*.tmp"))


def test_concurrent_cache_writers_use_unique_temps_and_publish_valid_pair(tmp_path):
    barrier = threading.Barrier(2)
    kwargs = _cache_write_kwargs(tmp_path)

    def build():
        def rows():
            barrier.wait(timeout=5)
            yield _base_feature_set(_dt("2026-01-01T00:01:00+00:00"))

        return write_feature_cache(rows(), **kwargs)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: build(), range(2)))

    assert results[0] == results[1]
    assert loader_module.validate_cache_pair(*results[0])
    assert not list(results[0][0].parent.glob("*.tmp"))


def test_identity_lock_prevents_mixed_publication_from_different_writers(tmp_path):
    barrier = threading.Barrier(2)
    kwargs = _cache_write_kwargs(tmp_path)

    def build(label, price):
        def rows():
            barrier.wait(timeout=5)
            yield _feature_set_with_price(price)

        return write_feature_cache(
            rows(),
            provenance={"writer": {"id": label}},
            **kwargs,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(build, "A", Decimal("101")),
            executor.submit(build, "B", Decimal("202")),
        ]
        results = [future.result(timeout=10) for future in futures]

    assert results[0] == results[1]
    jsonl_path, manifest_path = results[0]
    payload = json.loads(jsonl_path.read_text().strip())
    manifest = json.loads(manifest_path.read_text())
    final_state = (
        manifest["provenance"]["writer"]["id"],
        payload["features"]["close"]["value"],
    )
    assert final_state in {("A", "101"), ("B", "202")}
    assert loader_module.validate_cache_pair(jsonl_path, manifest_path)
    assert not list(jsonl_path.parent.glob("*.lock"))


def test_publication_lock_recovers_stale_file_and_times_out_on_active_file(tmp_path):
    kwargs = _cache_write_kwargs(tmp_path)
    jsonl_path, manifest_path = write_feature_cache(
        [_feature_set_with_price(Decimal("100"))], **kwargs
    )
    lock_path = loader_module.publication_lock_path(jsonl_path)
    lock_path.write_text("stale")
    old = time.time() - 120
    os.utime(lock_path, (old, old))

    write_feature_cache(
        [_feature_set_with_price(Decimal("101"))],
        lock_timeout_seconds=0.1,
        lock_stale_seconds=60,
        **kwargs,
    )
    assert not lock_path.exists()
    assert loader_module.validate_cache_pair(jsonl_path, manifest_path)

    lock_path.write_text("active")
    with pytest.raises(TimeoutError, match="publication lock"):
        write_feature_cache(
            [_feature_set_with_price(Decimal("102"))],
            lock_timeout_seconds=0.01,
            lock_stale_seconds=60,
            **kwargs,
        )
    assert lock_path.exists()
    lock_path.unlink()


def test_streaming_digest_completes_before_short_publication_lock(
    tmp_path, monkeypatch
):
    events = []
    original_write = loader_module._write_feature_rows
    original_lock = loader_module._publication_lock

    def slow_write(rows, temporary, requested):
        events.append("write-start")
        assert not list(temporary.parent.glob("*.lock"))
        time.sleep(0.03)
        summary = original_write(rows, temporary, requested)
        events.append("digest-complete")
        return summary

    @contextmanager
    def observed_lock(lock_path, **kwargs):
        events.append("lock-acquire")
        assert events[-2] == "digest-complete"
        with original_lock(lock_path, **kwargs):
            yield
        events.append("lock-release")

    monkeypatch.setattr(loader_module, "_write_feature_rows", slow_write)
    monkeypatch.setattr(loader_module, "_publication_lock", observed_lock)
    monkeypatch.setattr(
        loader_module,
        "_sha256_file",
        lambda path: (_ for _ in ()).throw(
            AssertionError("JSONL must not be re-read for hashing")
        ),
    )

    jsonl_path, manifest_path = write_feature_cache(
        [_feature_set_with_price(Decimal("123"))],
        lock_timeout_seconds=1,
        lock_stale_seconds=0.01,
        **_cache_write_kwargs(tmp_path),
    )

    assert events == [
        "write-start",
        "digest-complete",
        "lock-acquire",
        "lock-release",
    ]
    manifest = json.loads(manifest_path.read_text())
    assert manifest["output_hash"] == hashlib.sha256(jsonl_path.read_bytes()).hexdigest()
    assert not list(jsonl_path.parent.glob("*.lock"))


@pytest.mark.parametrize(
    "manifest_bytes",
    [
        b"[]",
        b"{}",
        b'{"output_hash":123}',
        b'{"output_hash":"short"}',
        b"{not-json",
        b"\xff\xfe",
    ],
)
def test_validate_cache_pair_returns_false_for_malformed_manifests(
    tmp_path, manifest_bytes
):
    jsonl = tmp_path / "features.jsonl"
    manifest = tmp_path / "manifest.json"
    jsonl.write_bytes(b"row\n")
    manifest.write_bytes(manifest_bytes)
    assert loader_module.validate_cache_pair(jsonl, manifest) is False


def test_validate_cache_pair_returns_false_for_missing_files_and_hash_io_errors(
    tmp_path, monkeypatch
):
    jsonl = tmp_path / "features.jsonl"
    manifest = tmp_path / "manifest.json"
    assert loader_module.validate_cache_pair(jsonl, manifest) is False
    jsonl.write_bytes(b"row\n")
    manifest.write_text(json.dumps({"output_hash": hashlib.sha256(b"row\n").hexdigest()}))
    monkeypatch.setattr(
        loader_module,
        "_sha256_file",
        lambda path: (_ for _ in ()).throw(OSError("injected race")),
    )
    assert loader_module.validate_cache_pair(jsonl, manifest) is False


def test_chunk_stream_releases_previous_builder_before_starting_next():
    active = 0
    maximum_active = 0
    events = []

    def builder(chunk):
        def rows():
            nonlocal active, maximum_active
            active += 1
            maximum_active = max(maximum_active, active)
            events.append(("start", chunk))
            try:
                yield chunk
            finally:
                active -= 1
                events.append(("release", chunk))

        return rows()

    result = list(loader_module.iter_chunk_rows(("jan", "feb", "mar"), builder))

    assert result == ["jan", "feb", "mar"]
    assert maximum_active == 1
    assert events == [
        ("start", "jan"), ("release", "jan"),
        ("start", "feb"), ("release", "feb"),
        ("start", "mar"), ("release", "mar"),
    ]


def _current_funding_loader(tmp_path, api_get, **kwargs):
    class UnavailableDownloader:
        def download(self, url, destination, **download_kwargs):
            return DownloadResult("unavailable", destination)

    return HistoricalFeatureLoader(
        tmp_path,
        downloader=UnavailableDownloader(),
        clock=lambda: _dt("2026-07-02T12:00:00+00:00"),
        api_get=api_get,
        **kwargs,
    )


def _cache_write_kwargs(tmp_path):
    return {
        "cache_root": tmp_path,
        "symbol": "BTCUSDT",
        "start": _dt("2026-01-01T00:00:00+00:00"),
        "end": _dt("2026-01-01T00:02:00+00:00"),
        "requested_sources": ("klines", "aggTrades"),
        "raw_hashes": {},
        "aggtrades_max_bytes": 100,
    }


def _base_row(close: datetime) -> FeatureRow:
    return FeatureRow(
        minute_end=close,
        available_at=close,
        source="klines",
        features={"close": Decimal("100")},
    )


def _base_feature_set(close: datetime):
    return next(
        merge_feature_rows(
            [_base_row(close)],
            {},
            requested_sources=("klines", "aggTrades"),
            symbol="BTCUSDT",
        )
    )


def _feature_set_with_price(price: Decimal):
    close = _dt("2026-01-01T00:01:00+00:00")
    return next(
        merge_feature_rows(
            [
                FeatureRow(
                    minute_end=close,
                    available_at=close,
                    source="klines",
                    features={"close": price},
                )
            ],
            {},
            requested_sources=("klines", "aggTrades"),
            symbol="BTCUSDT",
        )
    )
