from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
import hashlib
from io import BytesIO
import subprocess
import sys

import pytest

from scripts.chart_regime_strategy_mapping import (
    BTCUSDT_FIRST_FOLD,
    PRODUCTION_WALK_FORWARD_GRID,
    WalkForwardDependencies,
    WalkForwardGrid,
    WalkForwardInputs,
    parse_walk_forward_args,
    run_chart_regime_walk_forward,
    run_mapping_episodes,
    run_scheduler_driven_regime_backtest,
    write_walk_forward_reports,
)
from scripts.chart_regime_strategy_mapping import _canonical_hash
from scripts.chart_regime_strategy_mapping import _gmm_bic, _gmm_parameter_count
from scripts.chart_regime_strategy_mapping import _chronological_block_stability
from scripts.chart_regime_strategy_mapping import _manual_router_candidate
from scripts.chart_regime_strategy_mapping import _mapping_feature_coverage
from scripts.chart_regime_strategy_mapping import _project_centroids_to_primary_coordinates
from scripts.chart_regime_strategy_mapping import _run_mapping_coverage_filtered_evidence
from scripts.scheduler_driven_scalping_backtest import (
    FEE_RATE,
    SchedulerBacktestCandidate,
    StrategyCandidateSpec,
    feature_provider_config_hash,
)
from src.domain.market import Candle, MarketSnapshot, Symbol, Timeframe


def test_mapping_module_exposes_scheduler_driven_regime_replay() -> None:
    from scripts.scheduler_driven_scalping_backtest import (
        run_scheduler_driven_regime_backtest as canonical_replay,
    )

    assert run_scheduler_driven_regime_backtest is canonical_replay


def test_chart_regime_cli_help_runs_as_a_direct_script() -> None:
    root = Path(__file__).resolve().parents[1]
    completed = subprocess.run(
        [sys.executable, str(root / "scripts" / "chart_regime_strategy_mapping.py"), "--help"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    assert "Leakage-safe BTCUSDT regime walk-forward" in completed.stdout


def test_gmm_bic_counts_diag_and_tied_parameters_exactly() -> None:
    # weights + means + covariance parameters
    assert _gmm_parameter_count(3, 4, "diag") == 2 + 12 + 12
    assert _gmm_parameter_count(3, 4, "tied") == 2 + 12 + 10
    assert _gmm_bic(-100.0, 50, 24) == pytest.approx(200 + 24 * __import__("math").log(50))


def test_manual_router_is_a_distinct_public_factory_candidate() -> None:
    from scripts.scheduler_driven_scalping_backtest import default_candidate

    manual = _manual_router_candidate()
    assert manual.candidate_id == "range-first-p2-tp0060-sl0045-e0035-l3-guard-a"
    assert [spec.kind for spec in manual.strategies] == ["regime_router"]
    assert manual != default_candidate()


def test_mapping_feature_coverage_rejects_partial_point_in_time_episode() -> None:
    from src.domain.market_feature import MarketFeatureSet, MarketFeatureValue

    start = datetime(2026, 1, 5, tzinfo=timezone.utc)
    episode = tuple(build_weekly_episodes(start, start + timedelta(days=7)))
    candidate = SchedulerBacktestCandidate(
        candidate_id="flow",
        strategies=(StrategyCandidateSpec("flow_breakout", {}),),
        take_profit_ratio=Decimal("0.01"), stop_loss_ratio=Decimal("0.01"),
        equity_ratio=Decimal("0.1"), leverage=Decimal("2"), candle_limit=1,
    )

    class PartialProvider:
        def load_features(self, symbol, timeframe, as_of):
            values = () if as_of >= start + timedelta(days=3) else tuple(
                MarketFeatureValue(name, Decimal("1"), source, as_of, as_of)
                for name, source in (
                    ("taker_imbalance", "aggTrades"),
                    ("cvd_delta", "aggTrades"),
                    ("trade_intensity", "aggTrades"),
                )
            )
            return MarketFeatureSet(symbol, timeframe, as_of, values)

    valid, report = _mapping_feature_coverage(
        _minute_market(start, 1, warmup_minutes=0), episode, (candidate,), PartialProvider()
    )
    assert valid["flow"] == set()
    assert report["flow"]["eligible_episode_count"] == 0
    assert report["flow"]["episodes"][0]["available_minutes"] < 10080
    assert "missing point-in-time alternatives" in report["flow"]["episodes"][0]["rejection_reason"]


def test_premium_strategy_accepts_either_premium_or_complete_basis_alternative() -> None:
    from src.domain.market_feature import MarketFeatureSet, MarketFeatureValue

    start = datetime(2026, 1, 5, tzinfo=timezone.utc)
    episodes = tuple(build_weekly_episodes(start, start + timedelta(days=7)))
    market = _minute_market(start, 1, warmup_minutes=0)
    candidate = SchedulerBacktestCandidate(
        candidate_id="premium",
        strategies=(StrategyCandidateSpec("premium_funding", {}),),
        take_profit_ratio=Decimal("0.01"), stop_loss_ratio=Decimal("0.01"),
        equity_ratio=Decimal("0.1"), leverage=Decimal("2"), candle_limit=1,
    )

    class Provider:
        def __init__(self, extra):
            self.extra = extra

        def load_features(self, symbol, timeframe, as_of):
            fields = {
                "taker_imbalance": "aggTrades",
                "cvd_delta": "aggTrades",
                **self.extra,
            }
            return MarketFeatureSet(
                symbol, timeframe, as_of,
                tuple(MarketFeatureValue(name, Decimal("1"), source, as_of, as_of) for name, source in fields.items()),
            )

    premium_valid, _ = _mapping_feature_coverage(
        market, episodes, (candidate,), Provider({"premium_index": "premiumIndexKlines"})
    )
    basis_valid, _ = _mapping_feature_coverage(
        market, episodes, (candidate,), Provider({"mark_price": "markPriceKlines", "index_price": "indexPriceKlines"})
    )
    incomplete, report = _mapping_feature_coverage(
        market, episodes, (candidate,), Provider({"mark_price": "markPriceKlines"})
    )
    assert premium_valid["premium"] == {start}
    assert basis_valid["premium"] == {start}
    assert incomplete["premium"] == set()
    assert "premium_index" in report["premium"]["episodes"][0]["rejection_reason"]
    assert "index_price" in report["premium"]["episodes"][0]["rejection_reason"]


def test_coverage_invalid_candidates_are_never_backtested(monkeypatch) -> None:
    import scripts.chart_regime_strategy_mapping as module

    start = datetime(2026, 1, 5, tzinfo=timezone.utc)
    episodes = tuple(build_weekly_episodes(start, start + timedelta(days=14)))
    valid_candidate, invalid_candidate = _candidate("valid"), _candidate("invalid")
    calls = []

    def capture(_market, *, candidates, episodes, **_kwargs):
        calls.append(([item.candidate_id for item in candidates], episodes[0].start_at))
        return []

    monkeypatch.setattr(module, "run_mapping_episodes", capture)
    rows = _run_mapping_coverage_filtered_evidence(
        _minute_market(start, 2, warmup_minutes=0),
        episodes=episodes,
        assignments={episode.anchor_at: "cluster" for episode in episodes},
        candidates=(valid_candidate, invalid_candidate),
        valid_episodes={"valid": {episodes[0].start_at}, "invalid": set()},
        market_feature_provider=None,
    )
    assert rows == []
    assert calls == [(["valid"], episodes[0].start_at)]


def _fixture_walk_forward_dependencies(test_return: str = "0.01"):
    def prepare(context):
        return {"provenance": {"archives": [{"sha256": "a" * 64}]}}

    def features(context, prepared):
        return {"schema": "btc-chart-regime-ohclv-v1", "vectors": [1, 2, 3]}

    def models(context, features):
        return {
            "selected": {"kmeans": {"artifact_hash": "b" * 64}, "gmm": {"artifact_hash": "c" * 64}},
            "candidates": [{"config_id": "bad", "eligible": False, "rejection_reasons": ["unstable"]}],
        }

    def mappings(context, prepared, features, models):
        return {
            "selected": {"kmeans": {"artifact_hash": "d" * 64}, "gmm": {"artifact_hash": "e" * 64}},
            "mapping_metrics": {"weekly_episode_count": 8},
        }

    def validation(context, prepared, features, models, mappings):
        return {"score": "0.02", "selected_family": "kmeans"}

    def test(context, prepared, features, models, mappings, validation):
        return {
            name: {"status": "cash" if name == "cash" else "ok", "continuous_metrics": {"return_ratio": test_return}}
            for name in ("cash", "adopted_fixed", "train_selected_fixed", "manual_regime_router", "kmeans_dynamic", "gmm_dynamic")
        }

    return WalkForwardDependencies(prepare, features, models, mappings, validation, test)


def test_walk_forward_freezes_artifacts_before_test_and_has_required_baselines() -> None:
    events = []
    payload = run_chart_regime_walk_forward(
        BTCUSDT_FIRST_FOLD,
        candidates=(_candidate("candidate-a"),),
        dependencies=_fixture_walk_forward_dependencies(),
        progress=events.append,
    )
    assert events.index("mapping_frozen") < events.index("first_test_classification")
    assert "test_result" not in events[:events.index("mapping_frozen")]
    assert set(payload["comparisons"]) == {
        "cash", "adopted_fixed", "train_selected_fixed", "manual_regime_router",
        "kmeans_dynamic", "gmm_dynamic",
    }
    assert payload["leakage_audit"]["frozen_before_test"] is True
    assert all(
        access["stage"] == "test_result"
        for access in payload["data_access_audit"]
        if access["interval"] == "test"
    )


def test_walk_forward_report_records_grid_provenance_and_rejections() -> None:
    payload = run_chart_regime_walk_forward(
        BTCUSDT_FIRST_FOLD,
        candidates=(_candidate("candidate-a"),),
        dependencies=_fixture_walk_forward_dependencies(),
    )
    assert payload["feature_schema_version"] == "btc-chart-regime-ohclv-v1"
    assert payload["candidate_universe_hash"]
    assert payload["candidate_definition_hash"]
    assert payload["data_provenance"]
    assert payload["rejected_model_configurations"][0]["config_id"] == "bad"
    assert payload["configuration_grid"]["cluster_counts"] == [3, 4, 5, 6, 7, 8]


def test_frozen_selection_hashes_do_not_depend_on_test_outcome() -> None:
    first = run_chart_regime_walk_forward(
        BTCUSDT_FIRST_FOLD, candidates=(_candidate("a"),),
        dependencies=_fixture_walk_forward_dependencies("0.1"),
    )
    changed = run_chart_regime_walk_forward(
        BTCUSDT_FIRST_FOLD, candidates=(_candidate("a"),),
        dependencies=_fixture_walk_forward_dependencies("-0.9"),
    )
    assert first["frozen_artifact_hashes"] == changed["frozen_artifact_hashes"]
    assert first["comparisons"] != changed["comparisons"]


def test_test_interval_is_not_passed_to_any_scoring_stage() -> None:
    dependencies = _fixture_walk_forward_dependencies()
    seen = []

    def wrap(function, *, test_stage=False):
        def call(context, *args):
            seen.append((test_stage, set(context)))
            return function(context, *args)
        return call

    guarded = WalkForwardDependencies(
        wrap(dependencies.prepare_data),
        wrap(dependencies.build_cluster_features),
        wrap(dependencies.evaluate_models),
        wrap(dependencies.build_mappings),
        wrap(dependencies.validate),
        wrap(dependencies.replay_test, test_stage=True),
    )
    run_chart_regime_walk_forward(
        BTCUSDT_FIRST_FOLD, candidates=(_candidate("a"),), dependencies=guarded
    )
    assert all("test" not in keys for is_test, keys in seen if not is_test)
    assert "test" in seen[-1][1]


def test_walk_forward_candidate_duplicates_dedupe_but_conflicts_fail_before_data() -> None:
    calls = []
    dependencies = _fixture_walk_forward_dependencies()

    def prepare(context):
        calls.append("data")
        return dependencies.prepare_data(context)

    guarded = replace(dependencies, prepare_data=prepare)
    candidate = _candidate("same")
    payload = run_chart_regime_walk_forward(
        BTCUSDT_FIRST_FOLD,
        candidates=(candidate, candidate),
        dependencies=guarded,
    )
    assert payload["candidate_ids"] == ["same"]
    assert calls == ["data"]

    calls.clear()
    with pytest.raises(ValueError, match="conflicting candidate definition"):
        run_chart_regime_walk_forward(
            BTCUSDT_FIRST_FOLD,
            candidates=(candidate, _candidate("same", equity_ratio="0.2")),
            dependencies=guarded,
        )
    assert calls == []


def test_walk_forward_fold_grid_and_cli_contract(tmp_path: Path) -> None:
    assert BTCUSDT_FIRST_FOLD.mapping_fit.start_at - BTCUSDT_FIRST_FOLD.cluster_fit.end_at == timedelta(days=7)
    assert BTCUSDT_FIRST_FOLD.validation.start_at - BTCUSDT_FIRST_FOLD.mapping_fit.end_at == timedelta(days=7)
    assert BTCUSDT_FIRST_FOLD.test.start_at - BTCUSDT_FIRST_FOLD.validation.end_at == timedelta(days=7)
    assert PRODUCTION_WALK_FORWARD_GRID.gmm_covariance_types == ("diag", "tied")
    assert PRODUCTION_WALK_FORWARD_GRID.gmm_probability_mins
    args = parse_walk_forward_args(["--symbol", "BTCUSDT", "--candidate-group", "all", "--output-json", str(tmp_path / "x.json"), "--output-markdown", str(tmp_path / "x.md")])
    assert args.output_model.name == "x-model.json"
    assert args.output_mapping.name == "x-mapping.json"


def test_atomic_walk_forward_reports_preserve_previous_files_on_render_failure(tmp_path: Path) -> None:
    json_path, md_path = tmp_path / "report.json", tmp_path / "report.md"
    write_walk_forward_reports({"comparisons": {}, "symbol": "BTCUSDT"}, json_path, md_path)
    before = (json_path.read_bytes(), md_path.read_bytes())
    with pytest.raises(ValueError):
        write_walk_forward_reports({"bad": float("nan")}, json_path, md_path)
    assert (json_path.read_bytes(), md_path.read_bytes()) == before


def test_cached_archive_is_verified_against_remote_checksum(monkeypatch, tmp_path: Path) -> None:
    import scripts.chart_regime_strategy_mapping as module

    archive = tmp_path / "BTCUSDT-1m-2026-01.zip"
    archive.write_bytes(b"verified archive")
    expected = hashlib.sha256(archive.read_bytes()).hexdigest()
    monkeypatch.setattr(module, "urlopen", lambda *args, **kwargs: BytesIO(f"{expected}  {archive.name}\n".encode("ascii")))
    actual, remote, source = module._ensure_archive(archive, "https://example.test/archive.zip")
    assert (actual, remote) == (expected, expected)
    assert source.endswith(".CHECKSUM")

    monkeypatch.setattr(module, "urlopen", lambda *args, **kwargs: BytesIO(("0" * 64 + "  bad.zip\n").encode("ascii")))
    with pytest.raises(ValueError, match="checksum mismatch"):
        module._ensure_archive(archive, "https://example.test/archive.zip")


def _regime_vectors(anchors):
    names = tuple(spec.name for spec in CHART_FEATURE_REGISTRY_V1)
    vectors = []
    for index, anchor in enumerate(anchors):
        cluster = index % 3
        values = {
            name: float(cluster * 25 + __import__("math").sin((index + 1) * (column + 1) * 0.37) + column * 0.071)
            for column, name in enumerate(names)
        }
        vectors.append(ChartFeatureVector("BTCUSDT", anchor, anchor - timedelta(days=7), CHART_FEATURE_SCHEMA_VERSION, values))
    return tuple(vectors)


def test_chronological_stability_refits_disjoint_time_blocks() -> None:
    from src.domain.regime.model import RegimeModelConfig
    from src.infrastructure.regime.sklearn_regime_model import SklearnRegimeModel

    anchors = [datetime(2021, 1, 1, tzinfo=timezone.utc) + timedelta(hours=4 * index) for index in range(90)]
    vectors = _regime_vectors(anchors)
    mapping = _regime_vectors([
        datetime(2025, 7, 7, tzinfo=timezone.utc) + timedelta(days=7 * index)
        for index in range(26)
    ])
    real = SklearnRegimeModel()
    primary = real.fit(RegimeModelConfig("kmeans", 3, 20260714), vectors)

    class RecordingEngine:
        def __init__(self):
            self.blocks = []

        def fit(self, config, block):
            self.blocks.append((block[0].anchor_at, block[-1].anchor_at, len(block)))
            return real.fit(config, block)

        def assign(self, artifact, values):
            return real.assign(artifact, values)

    engine = RecordingEngine()
    distance, drift, profiles = _chronological_block_stability(engine, primary, vectors, mapping)
    assert engine.blocks[0][1] < engine.blocks[1][0]
    assert [item[2] for item in engine.blocks] == [45, 45]
    assert distance >= 0 and 0 <= drift <= 1
    assert len(profiles) == 2


def test_block_centroids_are_projected_into_primary_standardized_coordinates() -> None:
    import numpy as np
    from dataclasses import replace
    from src.domain.regime.model import RegimeModelConfig
    from src.infrastructure.regime.sklearn_regime_model import SklearnRegimeModel

    anchors = [datetime(2021, 1, 1, tzinfo=timezone.utc) + timedelta(hours=4 * index) for index in range(90)]
    artifact = SklearnRegimeModel().fit(RegimeModelConfig("kmeans", 3), _regime_vectors(anchors))
    assert np.allclose(_project_centroids_to_primary_coordinates(artifact, artifact), artifact.means)

    shifted = replace(
        artifact,
        medians=tuple(value + 5 for value in artifact.medians),
        scales=tuple(value * 2 for value in artifact.scales),
    )
    raw = np.asarray(shifted.means) * np.asarray(shifted.scales) + np.asarray(shifted.medians)
    expected = (
        np.clip(raw, artifact.lower_bounds, artifact.upper_bounds) - np.asarray(artifact.medians)
    ) / np.asarray(artifact.scales)
    actual = _project_centroids_to_primary_coordinates(shifted, artifact)
    assert np.allclose(actual, expected)
    assert not np.allclose(actual, shifted.means)


def test_default_model_mapping_and_replay_stages_execute_end_to_end(monkeypatch, tmp_path: Path) -> None:
    import scripts.chart_regime_strategy_mapping as module

    cluster_anchors = [BTCUSDT_FIRST_FOLD.cluster_fit.start_at + timedelta(hours=4 * index) for index in range(90)]
    mapping_anchors = [episode.anchor_at for episode in build_weekly_episodes(BTCUSDT_FIRST_FOLD.mapping_fit.start_at, BTCUSDT_FIRST_FOLD.mapping_fit.end_at)]
    validation_anchors = [BTCUSDT_FIRST_FOLD.validation.start_at + timedelta(hours=4 * index) for index in range(12)]
    candidate = _candidate("candidate-a")

    def evidence(_market, *, episodes, assignments, candidates, **_kwargs):
        rows = []
        for episode in episodes:
            for item in candidates:
                rows.append({
                    "cluster_fingerprint": assignments[episode.anchor_at],
                    "candidate_id": item.candidate_id,
                    "episode_start_at": episode.start_at.isoformat(),
                    "episode_end_at": episode.end_at.isoformat(),
                    "initial_equity": "10000", "final_equity": "10000", "net_pnl": "0", "return_ratio": "0",
                    "trade_count": 0, "trades": [], "candidate_hash": "a" * 64,
                    "market_context_hash": "b" * 64, "data_hash": _canonical_hash({"episode": episode.start_at.isoformat()}),
                    "feature_cache_hash": None, "feature_provenance": {}, "feature_config_hash": None,
                })
        return rows

    monkeypatch.setattr(module, "run_mapping_episodes", evidence)
    fixed_calls = []

    def fixed_replay(*args, **kwargs):
        fixed_calls.append(kwargs)
        return {
            "return_ratio": "0", "max_drawdown_ratio": "0", "trade_count": 1,
            "trades": [{"net_pnl": "1", "owner_strategy_profile_id": kwargs["candidate"].candidate_id}],
        }

    monkeypatch.setattr(module, "run_scheduler_driven_backtest", fixed_replay)
    replay_calls = []

    def replay(*args, **kwargs):
        mapping = kwargs["mapping_artifact"]
        policy = mapping.selection_confidence_thresholds
        replay_calls.append((kwargs["start_at"], mapping_artifact_hash(mapping)))
        score = (
            Decimal(str(policy.gmm_probability_min + policy.gmm_margin_min))
            if policy.model_type == "gmm" else Decimal("0")
        )
        return {"return_ratio": str(score), "max_drawdown_ratio": "0", "trade_count": 0, "turnover": "0"}

    from src.infrastructure.regime.json_regime_artifact_repository import mapping_artifact_hash
    monkeypatch.setattr(module, "run_scheduler_driven_regime_backtest", replay)
    market = _minute_market(BTCUSDT_FIRST_FOLD.mapping_fit.start_at, 1)
    inputs = WalkForwardInputs(
        market=market,
        cluster_fit_vectors=_regime_vectors(cluster_anchors),
        mapping_vectors=_regime_vectors(mapping_anchors),
        validation_vectors=_regime_vectors(validation_anchors),
        data_provenance={"fixture": "default-stage-e2e"},
    )
    grid = WalkForwardGrid(
        cluster_counts=(3,), model_types=("kmeans", "gmm"),
        gmm_covariance_types=("diag",), seeds=(20260714, 20260715, 20260716),
        bootstrap_resamples=(10, 11), confidence_levels=(0.90, 0.95),
    )
    payload = run_chart_regime_walk_forward(
        BTCUSDT_FIRST_FOLD,
        candidates=(candidate,),
        inputs=inputs,
        fixture_grid=grid,
        output_json=tmp_path / "result.json",
        output_markdown=tmp_path / "result.md",
        output_model=tmp_path / "result-model.json",
        output_mapping=tmp_path / "result-mapping.json",
    )
    assert set(payload["selected_models"]) == {"kmeans", "gmm"}
    assert any(
        len(item.get("evidence", {}).get("chronological_block_refits", ())) == 2
        for item in payload["model_candidates"] if item.get("eligible")
    )
    assert set(payload["mapping_artifacts"]) == {"kmeans", "gmm"}
    assert payload["mapping_metrics"]["evidence_rows"] == 26
    assert len(payload["validation"]["candidates"]) == 48
    assert payload["comparisons"]["kmeans_dynamic"]["status"] == "ok"
    assert payload["validation"]["selected_config_id"].endswith("gmm:p0.75:m0.2")
    selected_hash = next(
        row["mapping_artifact_hash"] for row in payload["validation"]["candidates"]
        if row["config_id"] == payload["validation"]["selected_config_id"]
    )
    assert (BTCUSDT_FIRST_FOLD.test.start_at, selected_hash) in replay_calls
    assert payload["pipeline_events"][-1] == "reports_written"
    assert payload["mapping_artifacts"]["gmm"]["candidate_assessments"]
    assert "cash_contribution" in payload["continuous_diagnostics"]["gmm_dynamic"]
    assert all(call["include_trade_details"] is True for call in fixed_calls)
    assert payload["continuous_diagnostics"]["adopted_fixed"]["concentration"]["top_5_positive_trade_pnl_share"] == "1"
    assert all((tmp_path / name).is_file() for name in (
        "result.json", "result.md", "result-model.json", "result-mapping.json"
    ))
from src.domain.regime import build_weekly_episodes
from src.domain.regime import CHART_FEATURE_REGISTRY_V1, CHART_FEATURE_SCHEMA_VERSION, ChartFeatureVector


def _minute_market(
    start: datetime,
    weeks: int = 2,
    price: Decimal = Decimal("100"),
    symbol: Symbol | None = None,
    warmup_minutes: int = 300,
) -> MarketSnapshot:
    symbol = symbol or Symbol("BTC", "USDT")
    timeframe = Timeframe(1, "m")
    return MarketSnapshot(tuple(
        Candle(
            symbol=symbol,
            timeframe=timeframe,
            opened_at=start + timedelta(minutes=index),
            closed_at=start + timedelta(minutes=index + 1),
            open_price=price,
            high_price=price,
            low_price=price,
            close_price=price,
            volume=Decimal("10"),
        )
        for index in range(-warmup_minutes, weeks * 7 * 24 * 60)
    ))


def _evidence_result(kwargs, **overrides):
    initial = kwargs["initial_equity"]
    result = {
        "candidate_id": kwargs["candidate"].candidate_id,
        "initial_equity": str(initial),
        "final_equity": str(initial),
        "trade_count": 0,
        "trades_per_day": "0",
        "gross_pnl": "0",
        "net_pnl": "0",
        "fee_paid": "0",
        "return_ratio": "0",
        "daily_return_ratio": "0",
        "max_drawdown_ratio": "0",
        "net_win_rate": "0",
        "average_net_trade_roe": "0",
        "average_net_trade_expectancy_ratio": "0",
        "trades": [],
        "feature_cache_hash": None,
        "feature_provenance": {},
        "feature_config_hash": None,
    }
    result.update(overrides)
    return result


def _accounted_trade(
    kwargs,
    *,
    entry_at: datetime,
    exit_at: datetime,
    entry_price: Decimal = Decimal("100"),
    exit_price: Decimal = Decimal("101"),
    quantity: Decimal = Decimal("1"),
    direction: str = "long",
):
    gross = (
        (exit_price - entry_price) * quantity
        if direction == "long"
        else (entry_price - exit_price) * quantity
    )
    fee = (entry_price * quantity + exit_price * quantity) * FEE_RATE
    margin = entry_price * quantity / kwargs["candidate"].leverage
    return {
        "entry_at": entry_at.isoformat(),
        "exit_at": exit_at.isoformat(),
        "entry_price": str(entry_price),
        "exit_price": str(exit_price),
        "direction": direction,
        "quantity": str(quantity),
        "margin": str(margin),
        "gross_pnl": str(gross),
        "net_pnl": str(gross - fee),
        "fee_paid": str(fee),
        "exit_reason": "take_profit",
        "holding_bars": int((exit_at - entry_at).total_seconds() // 60),
    }


def _result_for_trades(kwargs, trades, **overrides):
    initial = kwargs["initial_equity"]
    gross = sum((Decimal(item["gross_pnl"]) for item in trades), Decimal("0"))
    net = sum((Decimal(item["net_pnl"]) for item in trades), Decimal("0"))
    fees = sum((Decimal(item["fee_paid"]) for item in trades), Decimal("0"))
    equity = initial
    peak = initial
    max_drawdown = Decimal("0")
    for trade in trades:
        equity += Decimal(trade["net_pnl"])
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, (peak - equity) / peak)
    count = len(trades)
    wins = sum(Decimal(item["net_pnl"]) > 0 for item in trades)
    result = _evidence_result(
        kwargs,
        trade_count=count,
        trades=trades,
        trades_per_day=str(Decimal(count) / Decimal(7)),
        gross_pnl=str(gross),
        net_pnl=str(net),
        fee_paid=str(fees),
        final_equity=str(initial + net),
        return_ratio=str(net / initial),
        daily_return_ratio=str((net / initial) / Decimal(7)),
        net_win_rate=str(Decimal(wins) / Decimal(count) if count else Decimal("0")),
        average_net_trade_roe=str(
            sum(
                (Decimal(item["net_pnl"]) / Decimal(item["margin"]) for item in trades),
                Decimal("0"),
            ) / Decimal(count)
            if count else Decimal("0")
        ),
        average_net_trade_expectancy_ratio=str(
            (net / Decimal(count)) / initial if count else Decimal("0")
        ),
        max_drawdown_ratio=str(max_drawdown),
    )
    result.update(overrides)
    return result


def _candidate(candidate_id: str, *, equity_ratio: str = "0.1") -> SchedulerBacktestCandidate:
    return SchedulerBacktestCandidate(
        candidate_id=candidate_id,
        strategies=(StrategyCandidateSpec("unused", {"threshold": Decimal("2")}),),
        take_profit_ratio=Decimal("0.01"),
        stop_loss_ratio=Decimal("0.02"),
        equity_ratio=Decimal(equity_ratio),
        leverage=Decimal("3"),
        candle_limit=1,
    )


def test_mapping_runs_flat_nonoverlapping_weekly_evidence(monkeypatch) -> None:
    import scripts.chart_regime_strategy_mapping as module

    start = datetime(2026, 1, 5, tzinfo=timezone.utc)
    market = _minute_market(start)
    episodes = tuple(build_weekly_episodes(start, start + timedelta(days=14)))
    assignments = {episodes[0].anchor_at: "cluster-b", episodes[1].anchor_at: "cluster-a"}
    candidates = (_candidate("candidate-b"), _candidate("candidate-a"))
    calls = []

    def fake_backtest(snapshot, **kwargs):
        calls.append((snapshot, kwargs))
        return _evidence_result(kwargs)

    monkeypatch.setattr(module, "run_scheduler_driven_backtest", fake_backtest)
    rows = run_mapping_episodes(
        market,
        episodes=episodes,
        assignments=assignments,
        candidates=candidates,
        initial_equity=Decimal("4321"),
    )

    assert [(row["episode_start_at"], row["candidate_id"]) for row in rows] == [
        ("2026-01-05T00:00:00+00:00", "candidate-a"),
        ("2026-01-05T00:00:00+00:00", "candidate-b"),
        ("2026-01-12T00:00:00+00:00", "candidate-a"),
        ("2026-01-12T00:00:00+00:00", "candidate-b"),
    ]
    assert all(kwargs["initial_equity"] == Decimal("4321") for _, kwargs in calls)
    assert all(kwargs["force_close_at_end"] is True for _, kwargs in calls)
    assert all(kwargs["include_trade_details"] is True for _, kwargs in calls)
    assert [(snapshot.opened_at, snapshot.closed_at) for snapshot, _ in calls] == [
        (episodes[0].start_at - timedelta(minutes=1), episodes[0].end_at),
        (episodes[0].start_at - timedelta(minutes=1), episodes[0].end_at),
        (episodes[1].start_at - timedelta(minutes=1), episodes[1].end_at),
        (episodes[1].start_at - timedelta(minutes=1), episodes[1].end_at),
    ]
    assert all(row["initial_equity"] == "4321" and row["final_equity"] == "4321" for row in rows)


def test_mapping_hashes_are_canonical_and_bind_data_and_candidate(monkeypatch) -> None:
    import scripts.chart_regime_strategy_mapping as module

    monkeypatch.setattr(
        module,
        "run_scheduler_driven_backtest",
        lambda snapshot, **kwargs: _evidence_result(kwargs),
    )
    start = datetime(2026, 1, 5, tzinfo=timezone.utc)
    episode = tuple(build_weekly_episodes(start, start + timedelta(days=7)))
    assignments = {start: "cluster-a"}

    first = run_mapping_episodes(_minute_market(start, 1), episodes=episode, assignments=assignments, candidates=(_candidate("a"),))
    same = run_mapping_episodes(_minute_market(start, 1, Decimal("100.0")), episodes=episode, assignments=assignments, candidates=(_candidate("a", equity_ratio="0.10"),), initial_equity=Decimal("1E4"))
    repriced = run_mapping_episodes(_minute_market(start, 1, Decimal("101")), episodes=episode, assignments=assignments, candidates=(_candidate("a"),))
    reconfigured = run_mapping_episodes(_minute_market(start, 1), episodes=episode, assignments=assignments, candidates=(_candidate("a", equity_ratio="0.2"),))

    assert first[0]["data_hash"] == same[0]["data_hash"]
    assert first[0]["candidate_hash"] == same[0]["candidate_hash"]
    assert first[0]["data_hash"] != repriced[0]["data_hash"]
    assert first[0]["candidate_hash"] != reconfigured[0]["candidate_hash"]


@pytest.mark.parametrize("case", ("gap", "assignment", "duplicate_candidate", "non_utc", "missing_data"))
def test_mapping_fails_closed_on_invalid_evidence_inputs(case) -> None:
    start = datetime(2026, 1, 5, tzinfo=timezone.utc)
    episodes = tuple(build_weekly_episodes(start, start + timedelta(days=14)))
    assignments = {episode.anchor_at: "cluster" for episode in episodes}
    candidates = (_candidate("a"),)
    market = _minute_market(start)

    if case == "gap":
        broken = list(episodes)
        broken[1] = type(broken[1])(
            anchor_at=broken[1].anchor_at + timedelta(days=7),
            feature_start_at=broken[1].feature_start_at + timedelta(days=7),
            start_at=broken[1].start_at + timedelta(days=7),
            end_at=broken[1].end_at + timedelta(days=7),
        )
        episodes = tuple(broken)
    elif case == "assignment":
        assignments = {episodes[0].anchor_at: "cluster"}
    elif case == "duplicate_candidate":
        candidates = (_candidate("a"), _candidate("a"))
    elif case == "non_utc":
        bad = episodes[0]
        naive = bad.start_at.replace(tzinfo=None)
        episodes = (type(bad)(naive, naive - timedelta(days=7), naive, naive + timedelta(days=7)),)
        assignments = {naive: "cluster"}
    elif case == "missing_data":
        market = _minute_market(start, 1)

    with pytest.raises(ValueError):
        run_mapping_episodes(market, episodes=episodes, assignments=assignments, candidates=candidates)


def test_mapping_requires_explicit_deferred_group_opt_in() -> None:
    start = datetime(2026, 1, 5, tzinfo=timezone.utc)
    episodes = tuple(build_weekly_episodes(start, start + timedelta(days=7)))

    with pytest.raises(ValueError, match="deferred"):
        run_mapping_episodes(
            _minute_market(start, 1),
            episodes=episodes,
            assignments={start: "cluster"},
            candidate_groups=("microstructure",),
        )


def test_mapping_resolves_explicit_candidate_from_opted_in_factory(monkeypatch) -> None:
    import scripts.chart_regime_strategy_mapping as module

    monkeypatch.setattr(
        module,
        "run_scheduler_driven_backtest",
        lambda snapshot, **kwargs: _evidence_result(kwargs),
    )
    start = datetime(2026, 1, 5, tzinfo=timezone.utc)
    episodes = tuple(build_weekly_episodes(start, start + timedelta(days=7)))

    rows = run_mapping_episodes(
        _minute_market(start, 1),
        episodes=episodes,
        assignments={start: "cluster"},
        candidate_groups=("microstructure",),
        candidate_ids=("micro-mtf-balanced-tight",),
        include_deferred_groups=("microstructure",),
    )

    assert [row["candidate_id"] for row in rows] == ["micro-mtf-balanced-tight"]

    with pytest.raises(ValueError, match="unknown candidate_id"):
        run_mapping_episodes(
            _minute_market(start, 1),
            episodes=episodes,
            assignments={start: "cluster"},
            candidate_groups=("microstructure",),
            candidate_ids=("does-not-exist",),
            include_deferred_groups=("microstructure",),
        )


@pytest.mark.parametrize(
    ("override", "message"),
    (
        ({"net_pnl": None}, "net_pnl"),
        ({"candidate_id": "wrong"}, "candidate_id"),
        ({"trade_count": True}, "trade_count"),
        ({"fee_paid": "NaN"}, "fee_paid"),
        ({"trades": [{}]}, "trade"),
    ),
)
def test_mapping_rejects_partial_or_malformed_backtest_evidence(
    monkeypatch, override, message
) -> None:
    import scripts.chart_regime_strategy_mapping as module

    start = datetime(2026, 1, 5, tzinfo=timezone.utc)
    episodes = tuple(build_weekly_episodes(start, start + timedelta(days=7)))
    monkeypatch.setattr(
        module,
        "run_scheduler_driven_backtest",
        lambda snapshot, **kwargs: _evidence_result(kwargs, **override),
    )

    with pytest.raises(ValueError, match=message):
        run_mapping_episodes(
            _minute_market(start, 1),
            episodes=episodes,
            assignments={start: "cluster"},
            candidates=(_candidate("a"),),
        )


def test_mapping_rejects_missing_backtest_evidence_field(monkeypatch) -> None:
    import scripts.chart_regime_strategy_mapping as module

    def missing_field(snapshot, **kwargs):
        result = _evidence_result(kwargs)
        del result["net_pnl"]
        return result

    monkeypatch.setattr(module, "run_scheduler_driven_backtest", missing_field)
    start = datetime(2026, 1, 5, tzinfo=timezone.utc)
    episodes = tuple(build_weekly_episodes(start, start + timedelta(days=7)))

    with pytest.raises(ValueError, match="missing required fields: net_pnl"):
        run_mapping_episodes(
            _minute_market(start, 1),
            episodes=episodes,
            assignments={start: "cluster"},
            candidates=(_candidate("a"),),
        )


def test_mapping_data_hash_binds_feature_cache_identity(monkeypatch) -> None:
    import scripts.chart_regime_strategy_mapping as module

    class Provider:
        def __init__(self, cache_hash, config_hash):
            self.feature_cache_hash = cache_hash
            self.feature_provenance = {"provider": "fixture", "config": config_hash}
            self.feature_config_hash = config_hash

    def fake_backtest(snapshot, **kwargs):
        provider = kwargs["market_feature_provider"]
        return _evidence_result(
            kwargs,
            feature_cache_hash=provider.feature_cache_hash,
            feature_provenance=provider.feature_provenance,
            feature_config_hash=feature_provider_config_hash(provider),
        )

    monkeypatch.setattr(module, "run_scheduler_driven_backtest", fake_backtest)
    start = datetime(2026, 1, 5, tzinfo=timezone.utc)
    episodes = tuple(build_weekly_episodes(start, start + timedelta(days=7)))
    kwargs = {
        "episodes": episodes,
        "assignments": {start: "cluster"},
        "candidates": (_candidate("a"),),
    }
    first = run_mapping_episodes(
        _minute_market(start, 1),
        **kwargs,
        market_feature_provider=Provider("cache-a", "config-a"),
    )
    changed = run_mapping_episodes(
        _minute_market(start, 1),
        **kwargs,
        market_feature_provider=Provider("cache-b", "config-b"),
    )

    assert first[0]["feature_cache_hash"] == "cache-a"
    assert len(first[0]["feature_config_hash"]) == 64
    assert first[0]["data_hash"] != changed[0]["data_hash"]


def test_mapping_rejects_symbol_mismatch_and_non_minute_market(monkeypatch) -> None:
    import scripts.chart_regime_strategy_mapping as module

    monkeypatch.setattr(
        module,
        "run_scheduler_driven_backtest",
        lambda snapshot, **kwargs: _evidence_result(kwargs),
    )
    start = datetime(2026, 1, 5, tzinfo=timezone.utc)
    episodes = tuple(build_weekly_episodes(start, start + timedelta(days=7)))
    kwargs = {
        "episodes": episodes,
        "assignments": {start: "cluster"},
        "candidates": (_candidate("a"),),
    }

    with pytest.raises(ValueError, match="symbol"):
        run_mapping_episodes(
            _minute_market(start, 1),
            **kwargs,
            symbol=Symbol("ETH", "USDT"),
        )

    daily = MarketSnapshot(tuple(
        Candle(
            symbol=Symbol("BTC", "USDT"),
            timeframe=Timeframe(1, "d"),
            opened_at=start + timedelta(days=index),
            closed_at=start + timedelta(days=index + 1),
            open_price=Decimal("100"),
            high_price=Decimal("100"),
            low_price=Decimal("100"),
            close_price=Decimal("100"),
            volume=Decimal("1"),
        )
        for index in range(7)
    ))
    with pytest.raises(ValueError, match="1m"):
        run_mapping_episodes(daily, **kwargs)


def test_mapping_supplies_identical_max_candidate_warmup_to_every_candidate(monkeypatch) -> None:
    import scripts.chart_regime_strategy_mapping as module

    calls = []

    def fake_backtest(snapshot, **kwargs):
        calls.append((snapshot, kwargs))
        return _evidence_result(kwargs)

    monkeypatch.setattr(module, "run_scheduler_driven_backtest", fake_backtest)
    start = datetime(2026, 1, 5, tzinfo=timezone.utc)
    episodes = tuple(build_weekly_episodes(start, start + timedelta(days=7)))
    short = _candidate("short")
    long = SchedulerBacktestCandidate(
        candidate_id="long",
        strategies=short.strategies,
        take_profit_ratio=short.take_profit_ratio,
        stop_loss_ratio=short.stop_loss_ratio,
        equity_ratio=short.equity_ratio,
        leverage=short.leverage,
        candle_limit=5,
    )

    run_mapping_episodes(
        _minute_market(start, 1),
        episodes=episodes,
        assignments={start: "cluster"},
        candidates=(short, long),
    )

    expected_context_start = start - timedelta(minutes=5)
    assert len(calls) == 2
    assert all(snapshot.opened_at == expected_context_start for snapshot, _ in calls)
    assert calls[0][0].candles == calls[1][0].candles
    assert all(kwargs["context_start_at"] == expected_context_start for _, kwargs in calls)


def test_canonical_hash_type_tags_decimals_without_spelling_differences() -> None:
    assert _canonical_hash({"value": Decimal("100")}) == _canonical_hash(
        {"value": Decimal("1E2")}
    )
    assert _canonical_hash({"value": Decimal("1")}) != _canonical_hash({"value": "1"})


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("return_ratio", "0.1"),
        ("daily_return_ratio", "0.1"),
        ("trades_per_day", "1"),
        ("net_win_rate", "2"),
        ("max_drawdown_ratio", "2"),
        ("average_net_trade_expectancy_ratio", "0.1"),
        ("profit_factor", "1"),
    ),
)
def test_mapping_rejects_tampered_derived_summary(monkeypatch, field, value) -> None:
    import scripts.chart_regime_strategy_mapping as module

    monkeypatch.setattr(
        module,
        "run_scheduler_driven_backtest",
        lambda snapshot, **kwargs: _evidence_result(kwargs, **{field: value}),
    )
    start = datetime(2026, 1, 5, tzinfo=timezone.utc)
    episodes = tuple(build_weekly_episodes(start, start + timedelta(days=7)))

    with pytest.raises(ValueError, match=field):
        run_mapping_episodes(
            _minute_market(start, 1),
            episodes=episodes,
            assignments={start: "cluster"},
            candidates=(_candidate("a"),),
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("entry_price", "0", "entry_price"),
        ("quantity", "0", "quantity"),
        ("margin", "0", "margin"),
        ("fee_paid", "-0.1", "fee_paid"),
        ("net_pnl", "2", "net_pnl"),
        ("entry_at", "2026-01-04T23:59:00+00:00", "entry_at"),
        ("exit_at", "2026-01-05T00:00:00+00:00", "exit_at"),
        ("holding_bars", 2, "holding_bars"),
    ),
)
def test_mapping_rejects_invalid_trade_accounting_or_bounds(
    monkeypatch, field, value, message
) -> None:
    import scripts.chart_regime_strategy_mapping as module

    start = datetime(2026, 1, 5, tzinfo=timezone.utc)

    def fake_backtest(snapshot, **kwargs):
        trade = _accounted_trade(
            kwargs,
            entry_at=start,
            exit_at=start + timedelta(minutes=1),
        )
        result = _result_for_trades(kwargs, [trade])
        result["trades"][0][field] = value
        return result

    monkeypatch.setattr(module, "run_scheduler_driven_backtest", fake_backtest)
    episodes = tuple(build_weekly_episodes(start, start + timedelta(days=7)))
    with pytest.raises(ValueError, match=message):
        run_mapping_episodes(
            _minute_market(start, 1),
            episodes=episodes,
            assignments={start: "cluster"},
            candidates=(_candidate("a"),),
        )


@pytest.mark.parametrize(
    ("forgery", "message"),
    (("gross", "gross_pnl"), ("fee", "fee_paid"), ("margin", "margin")),
)
def test_mapping_rejects_coherent_reported_trade_forgery(monkeypatch, forgery, message) -> None:
    import scripts.chart_regime_strategy_mapping as module

    start = datetime(2026, 1, 5, tzinfo=timezone.utc)

    def fake_backtest(snapshot, **kwargs):
        trade = _accounted_trade(kwargs, entry_at=start, exit_at=start + timedelta(minutes=1))
        if forgery == "gross":
            trade["gross_pnl"] = "2"
            trade["fee_paid"] = "0.2"
            trade["net_pnl"] = "1.8"
        elif forgery == "fee":
            trade["fee_paid"] = "0.2"
            trade["net_pnl"] = "0.8"
        else:
            trade["margin"] = "34"
        return _result_for_trades(kwargs, [trade])

    monkeypatch.setattr(module, "run_scheduler_driven_backtest", fake_backtest)
    episodes = tuple(build_weekly_episodes(start, start + timedelta(days=7)))
    with pytest.raises(ValueError, match=message):
        run_mapping_episodes(
            _minute_market(start, 1),
            episodes=episodes,
            assignments={start: "cluster"},
            candidates=(_candidate("a"),),
        )


@pytest.mark.parametrize("mode", ("overlap", "reordered"))
def test_mapping_rejects_non_chronological_single_position_trades(monkeypatch, mode) -> None:
    import scripts.chart_regime_strategy_mapping as module

    start = datetime(2026, 1, 5, tzinfo=timezone.utc)

    def fake_backtest(snapshot, **kwargs):
        first = _accounted_trade(
            kwargs, entry_at=start, exit_at=start + timedelta(minutes=2)
        )
        second = _accounted_trade(
            kwargs,
            entry_at=start + timedelta(minutes=1 if mode == "overlap" else 2),
            exit_at=start + timedelta(minutes=3),
        )
        trades = [first, second] if mode == "overlap" else [second, first]
        return _result_for_trades(kwargs, trades)

    monkeypatch.setattr(module, "run_scheduler_driven_backtest", fake_backtest)
    episodes = tuple(build_weekly_episodes(start, start + timedelta(days=7)))
    with pytest.raises(ValueError, match="chronological|overlap"):
        run_mapping_episodes(
            _minute_market(start, 1),
            episodes=episodes,
            assignments={start: "cluster"},
            candidates=(_candidate("a"),),
        )


def test_mapping_reconstructs_drawdown_and_allows_equity_below_zero(monkeypatch) -> None:
    import scripts.chart_regime_strategy_mapping as module

    start = datetime(2026, 1, 5, tzinfo=timezone.utc)
    forged = {"enabled": True}

    def fake_backtest(snapshot, **kwargs):
        trade = _accounted_trade(
            kwargs,
            entry_at=start,
            exit_at=start + timedelta(minutes=1),
            entry_price=Decimal("100"),
            exit_price=Decimal("1"),
            quantity=Decimal("200"),
        )
        result = _result_for_trades(kwargs, [trade])
        if forged["enabled"]:
            result["max_drawdown_ratio"] = "0"
        return result

    monkeypatch.setattr(module, "run_scheduler_driven_backtest", fake_backtest)
    episodes = tuple(build_weekly_episodes(start, start + timedelta(days=7)))
    kwargs = {
        "episodes": episodes,
        "assignments": {start: "cluster"},
        "candidates": (_candidate("a"),),
    }
    with pytest.raises(ValueError, match="max_drawdown_ratio"):
        run_mapping_episodes(_minute_market(start, 1), **kwargs)

    forged["enabled"] = False
    rows = run_mapping_episodes(_minute_market(start, 1), **kwargs)
    assert Decimal(rows[0]["max_drawdown_ratio"]) > Decimal("1")
