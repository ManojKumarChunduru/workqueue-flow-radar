from __future__ import annotations

import json

import pandas as pd
import pytest

from wq_radar.cli import main
from wq_radar.config import AnalysisConfig, GeneratorConfig, load_settings
from wq_radar.generator.event_simulator import simulate
from wq_radar.radar.runner import Radar
from wq_radar.radar.scorer import score


@pytest.fixture(scope="session")
def cfg() -> GeneratorConfig:
    return GeneratorConfig(seed=7, n_claims=6000)


@pytest.fixture(scope="session")
def sim(cfg):
    return simulate(cfg)


@pytest.fixture(scope="session")
def analyzed(sim):
    radar = Radar(AnalysisConfig())
    radar.load_events(sim.events)
    radar.build_models()
    return radar


def test_settings_env_override(tmp_path, monkeypatch):
    cfgfile = tmp_path / "settings.yaml"
    cfgfile.write_text("generator:\n  n_claims: 50\n")
    monkeypatch.setenv("WQ_RADAR__GENERATOR__N_CLAIMS", "77")
    assert load_settings(cfgfile).generator.n_claims == 77


def test_invalid_config_rejected():
    with pytest.raises(ValueError):
        GeneratorConfig(n_conflicting_pairs=20, n_rules=10)
    with pytest.raises(ValueError):
        AnalysisConfig(min_oscillations=1)


def test_simulator_deterministic(cfg):
    a, b = simulate(cfg), simulate(cfg)
    pd.testing.assert_frame_equal(a.events, b.events)
    pd.testing.assert_frame_equal(a.ground_truth, b.ground_truth)


def test_every_claim_resolves_exactly_once(sim):
    resolves = sim.events[sim.events.event_type == "resolve"].groupby("claim_id").size()
    assert len(resolves) == len(sim.claims)
    assert (resolves == 1).all()


def test_event_times_monotonic_within_claim(sim):
    g = sim.events.sort_values(["claim_id", "event_id"]).groupby("claim_id")["event_time"]
    assert (g.apply(lambda s: s.is_monotonic_increasing)).all()


def test_victims_oscillate_between_exactly_two_queues(sim):
    gt = sim.ground_truth
    victims = gt[gt.kind == "claim"]
    assert len(victims) > 0
    routes = sim.events[sim.events.event_type == "route_in"]
    for victim in victims.itertuples(index=False):
        wqs = set(routes[routes.claim_id == victim.claim_id].wq_id)
        assert wqs == {victim.wq_a, victim.wq_b}


def test_detection_perfect_on_labeled_world(analyzed, sim):
    result = score(
        analyzed.frame("pingpong_claims"),
        analyzed.frame("conflict_pairs"),
        sim.ground_truth,
    )
    assert result.claim_precision == 1.0
    assert result.claim_recall == 1.0
    assert result.pair_attribution_rate == 1.0
    assert result.pairs_fired + result.pairs_dormant == result.pairs_planted


def test_rework_round_trips_not_flagged(analyzed, sim):
    """The false positive trap: a legitimate A -> B -> A return is 2
    transitions and must stay under the min_oscillations threshold."""
    routes = sim.events[sim.events.event_type == "route_in"]
    counts = routes.groupby("claim_id").size()
    victims = set(sim.ground_truth[sim.ground_truth.kind == "claim"].claim_id)
    rework = set(counts[counts == 3].index) - victims
    assert len(rework) > 0
    detected = set(analyzed.frame("pingpong_claims").claim_id)
    assert not (rework & detected)


def test_journeys_reconstruct_visit_chain(analyzed, sim):
    journeys = analyzed.frame("claim_journeys")
    per_claim_visits = journeys.groupby("claim_id").size()
    routes = sim.events[sim.events.event_type == "route_in"].groupby("claim_id").size()
    pd.testing.assert_series_equal(
        per_claim_visits.sort_index(), routes.sort_index(), check_names=False
    )
    assert journeys["visit_hours"].min() >= 0


def test_kpis_reconcile_to_events(analyzed, sim):
    kpis = analyzed.frame("fct_wq_kpis")
    assert int(kpis["touches"].sum()) == int((sim.events.event_type == "touch").sum())
    assert int(kpis["resolved"].sum()) == len(sim.claims)


def test_min_oscillations_must_be_int():
    radar = Radar(AnalysisConfig())
    object.__setattr__(radar.analysis, "min_oscillations", "3; DROP TABLE x")
    radar.load_events(pd.DataFrame({
        "event_id": ["EV1"], "claim_id": ["C1"],
        "event_time": [pd.Timestamp("2025-05-01")],
        "event_type": ["resolve"], "wq_id": ["WQ01"],
        "user_id": [None], "rule_id": [None],
    }))
    with pytest.raises(TypeError):
        radar.build_models()


def test_cli_all_end_to_end(tmp_path, capsys):
    root = tmp_path / "world"
    cfgfile = tmp_path / "settings.yaml"
    cfgfile.write_text(
        f"""
generator:
  seed: 5
  n_claims: 3000
paths:
  data_dir: "{root}"
  events_file: "{root}/events.parquet"
  claims_file: "{root}/claims.parquet"
  rules_file: "{root}/rules.parquet"
  labels_file: "{root}/truth.parquet"
  duckdb_file: "{root}/radar.duckdb"
  output_dir: "{root}/out"
"""
    )
    assert main(["all", "--config", str(cfgfile), "--quiet"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["claim_precision"] == 1.0
    assert payload["claim_recall"] == 1.0
    assert (root / "out" / "wq-daily-ops-packet.xlsx").exists()
    assert (root / "out" / "wq-daily-ops-summary.pdf").exists()
