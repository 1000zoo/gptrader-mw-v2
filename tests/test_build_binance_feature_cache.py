import hashlib
import json
import os
import subprocess
import sys
import zipfile
import argparse

import pytest
from datetime import datetime, timezone
from pathlib import Path

from scripts import build_binance_feature_cache
from src.infrastructure.exchange.binance.research_data.historical_feature_loader import (
    DownloadResult,
    HistoricalFeatureLoader,
)


def test_direct_script_help_bootstraps_repository_root_without_pythonpath(tmp_path):
    root = Path(__file__).resolve().parents[1]
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)

    result = subprocess.run(
        [
            sys.executable,
            str(root / "scripts" / "build_binance_feature_cache.py"),
            "--help",
        ],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "--aggtrades-max-bytes" in result.stdout


class _FakeLoader:
    calls = []
    init_calls = []

    def __init__(self, cache_root, **kwargs):
        self.cache_root = Path(cache_root)
        self.options = kwargs
        self.init_calls.append((self.cache_root, dict(kwargs)))

    def build_cache(self, *, symbol, start, end, sources):
        self.calls.append((symbol, start, end, tuple(sources), self.cache_root))
        jsonl = self.cache_root / "features.jsonl"
        manifest = self.cache_root / "manifest.json"
        jsonl.parent.mkdir(parents=True, exist_ok=True)
        jsonl.write_bytes(b"")
        manifest.write_text(
            json.dumps({"output_hash": hashlib.sha256(b"").hexdigest()})
        )
        return jsonl, manifest


def test_cli_accepts_source_comma_list_and_injected_loader(tmp_path, capsys):
    exit_code = build_binance_feature_cache.main(
        [
            "--symbol", "btcusdt",
            "--start", "2026-01-01",
            "--end", "2026-01-02",
            "--sources", "klines,aggTrades,mark,index,premium,funding",
            "--aggtrades-max-bytes", "12345",
            "--cache-root", str(tmp_path),
        ],
        loader_factory=_FakeLoader,
    )

    assert exit_code == 0
    symbol, start, end, sources, root = _FakeLoader.calls[-1]
    assert symbol == "BTCUSDT"
    assert start == datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert end == datetime(2026, 1, 2, tzinfo=timezone.utc)
    assert sources == (
        "klines",
        "aggTrades",
        "markPriceKlines",
        "indexPriceKlines",
        "premiumIndexKlines",
        "fundingRate",
    )
    assert root == tmp_path
    assert _FakeLoader.init_calls[-1] == (
        tmp_path,
        {"aggtrades_max_bytes": 12345},
    )
    assert "manifest.json" in capsys.readouterr().out


def test_cli_accepts_canonical_long_source_names(tmp_path):
    build_binance_feature_cache.main(
        [
            "--symbol", "BTCUSDT",
            "--start", "2026-01-01",
            "--end", "2026-01-02",
            "--sources", "markPriceKlines,indexPriceKlines,premiumIndexKlines,fundingRate,klines",
            "--cache-root", str(tmp_path),
        ],
        loader_factory=_FakeLoader,
    )
    assert _FakeLoader.calls[-1][3] == (
        "markPriceKlines",
        "indexPriceKlines",
        "premiumIndexKlines",
        "fundingRate",
        "klines",
    )


def test_cli_datetime_accepts_date_only_and_normalizes_aware_values_to_utc():
    assert build_binance_feature_cache._datetime("2026-01-02") == datetime(
        2026, 1, 2, tzinfo=timezone.utc
    )
    assert build_binance_feature_cache._datetime(
        "2026-01-02T09:30:00+09:00"
    ) == datetime(2026, 1, 2, 0, 30, tzinfo=timezone.utc)


def test_cli_datetime_rejects_naive_datetime_with_time():
    with pytest.raises(argparse.ArgumentTypeError, match="timezone"):
        build_binance_feature_cache._datetime("2026-01-02T09:30:00")


def test_cli_smoke_builds_compact_cache_with_fake_downloader(tmp_path):
    class FakeDownloader:
        def download(self, url, destination, **kwargs):
            destination.parent.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(destination, "w") as archive:
                archive.writestr(
                    "BTCUSDT-1m-2026-01.csv",
                    "1767225600000,100,110,90,105,10,1767225659999,1000,12,7,700,0\n",
                )
            return DownloadResult(
                "downloaded",
                destination,
                hashlib.sha256(destination.read_bytes()).hexdigest(),
            )

    def factory(cache_root, **kwargs):
        return HistoricalFeatureLoader(
            cache_root,
            downloader=FakeDownloader(),
            clock=lambda: datetime(2026, 7, 1, tzinfo=timezone.utc),
            **kwargs,
        )

    result = build_binance_feature_cache.main(
        [
            "--symbol", "BTCUSDT",
            "--start", "2026-01-01",
            "--end", "2026-01-02",
            "--sources", "klines",
            "--cache-root", str(tmp_path),
        ],
        loader_factory=factory,
    )

    assert result == 0
    manifests = list((tmp_path / "features" / "BTCUSDT" / "1m").glob("*.manifest.json"))
    assert len(manifests) == 1
    manifest = json.loads(manifests[0].read_text())
    assert manifest["row_count"] == 1
    assert manifest["source_coverage"]["klines"]["available_rows"] == 1
    assert list((tmp_path / "raw" / "klines" / "BTCUSDT").glob("*.zip"))
