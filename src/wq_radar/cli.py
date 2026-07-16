"""Command line interface.

    wq-radar generate   Simulate claims and write the event log
    wq-radar analyze    Build the SQL models, write analysis parquets
    wq-radar report     Render the daily ops packet (Excel + PDF)
    wq-radar score      Detection quality vs planted ground truth
    wq-radar all        generate + analyze + report + score
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import pandas as pd

from wq_radar.config import Settings, load_settings
from wq_radar.generator.event_simulator import simulate
from wq_radar.logging_conf import configure_logging
from wq_radar.radar.runner import Radar
from wq_radar.radar.scorer import score
from wq_radar.report.packet import build_packet

log = logging.getLogger(__name__)

ANALYSIS_VIEWS = ["fct_wq_kpis", "fct_claim_stats", "pingpong_claims", "conflict_pairs"]


def cmd_generate(settings: Settings) -> None:
    result = simulate(settings.generator)
    Path(settings.paths.data_dir).mkdir(parents=True, exist_ok=True)
    result.events.to_parquet(settings.paths.events_file, index=False)
    result.claims.to_parquet(settings.paths.claims_file, index=False)
    result.rules.to_parquet(settings.paths.rules_file, index=False)
    result.ground_truth.to_parquet(settings.paths.labels_file, index=False)


def cmd_analyze(settings: Settings) -> None:
    radar = Radar(settings.analysis)
    radar.load_events(settings.paths.events_file)
    radar.build_models()
    out_dir = Path(settings.paths.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for view in ANALYSIS_VIEWS:
        radar.frame(view).to_parquet(out_dir / f"{view}.parquet", index=False)
    log.info("analysis written", extra={"views": ANALYSIS_VIEWS, "dir": str(out_dir)})


def _load_view(settings: Settings, view: str) -> pd.DataFrame:
    path = Path(settings.paths.output_dir) / f"{view}.parquet"
    if not path.exists():
        raise FileNotFoundError(f"{path} not found. Run: wq-radar analyze")
    return pd.read_parquet(path)


def cmd_report(settings: Settings) -> None:
    xlsx, pdf = build_packet(
        settings.paths.output_dir,
        kpis=_load_view(settings, "fct_wq_kpis"),
        pingpong=_load_view(settings, "pingpong_claims"),
        conflicts=_load_view(settings, "conflict_pairs"),
        claim_stats=_load_view(settings, "fct_claim_stats"),
    )
    log.info("packet complete", extra={"xlsx": str(xlsx), "pdf": str(pdf)})


def cmd_score(settings: Settings) -> None:
    ground_truth = pd.read_parquet(settings.paths.labels_file)
    result = score(
        _load_view(settings, "pingpong_claims"),
        _load_view(settings, "conflict_pairs"),
        ground_truth,
    )
    print(json.dumps(result.as_dict(), indent=2))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="wq-radar")
    parser.add_argument(
        "command", choices=["generate", "analyze", "report", "score", "all"],
        help="workflow step to execute",
    )
    parser.add_argument("--config", default=None, help="path to settings.yaml")
    parser.add_argument("--quiet", action="store_true", help="log warnings and above only")
    args = parser.parse_args(argv)

    configure_logging(logging.WARNING if args.quiet else logging.INFO)
    settings = load_settings(args.config)

    steps = {
        "generate": [cmd_generate],
        "analyze": [cmd_analyze],
        "report": [cmd_report],
        "score": [cmd_score],
        "all": [cmd_generate, cmd_analyze, cmd_report, cmd_score],
    }[args.command]
    for step in steps:
        step(settings)
    return 0


if __name__ == "__main__":
    sys.exit(main())
