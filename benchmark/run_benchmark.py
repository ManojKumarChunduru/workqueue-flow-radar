"""Benchmark analyze throughput at increasing event volumes.

Per volume step: simulate (excluded from throughput; production events
arrive from the EHR's WQ history), analyze (load + all six SQL models +
result extraction), packet render, and score. Throughput is events per
second over the analyze step.

Usage:
    python benchmark/run_benchmark.py [--claims 20000 100000 250000]

Results land in benchmark/results/ with machine context.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from wq_radar.config import AnalysisConfig, GeneratorConfig  # noqa: E402
from wq_radar.generator.event_simulator import simulate  # noqa: E402
from wq_radar.radar.runner import Radar  # noqa: E402
from wq_radar.radar.scorer import score  # noqa: E402
from wq_radar.report.packet import build_packet  # noqa: E402

VIEWS = ["fct_wq_kpis", "fct_claim_stats", "pingpong_claims", "conflict_pairs"]


def _machine_context() -> dict:
    mem_gb = None
    try:
        mem_gb = round(os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE") / 1024**3, 1)
    except (ValueError, OSError):
        pass
    return {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "duckdb": duckdb.__version__,
        "pandas": pd.__version__,
        "cpu_count": os.cpu_count(),
        "ram_gb": mem_gb,
    }


def bench(n_claims: int, work_dir: Path) -> dict:
    cfg = GeneratorConfig(seed=42, n_claims=n_claims)
    timings: dict[str, float] = {}

    t0 = time.perf_counter()
    sim = simulate(cfg)
    timings["simulate"] = time.perf_counter() - t0
    n_events = len(sim.events)

    t0 = time.perf_counter()
    radar = Radar(AnalysisConfig())
    radar.load_events(sim.events)
    radar.build_models()
    frames = {v: radar.frame(v) for v in VIEWS}
    timings["analyze"] = time.perf_counter() - t0

    t0 = time.perf_counter()
    build_packet(work_dir, frames["fct_wq_kpis"], frames["pingpong_claims"],
                 frames["conflict_pairs"], frames["fct_claim_stats"])
    timings["packet"] = time.perf_counter() - t0

    t0 = time.perf_counter()
    metrics = score(frames["pingpong_claims"], frames["conflict_pairs"], sim.ground_truth)
    timings["score"] = time.perf_counter() - t0

    return {
        "n_claims": n_claims,
        "n_events": n_events,
        "timings_seconds": {k: round(v, 3) for k, v in timings.items()},
        "analyze_events_per_second": round(n_events / timings["analyze"]),
        "detection": metrics.as_dict(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--claims", nargs="+", type=int, default=[20_000, 100_000, 250_000])
    args = parser.parse_args()

    results = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "machine": _machine_context(),
        "note": (
            "Throughput is events/second over the analyze step (load + "
            "six SQL models + result extraction). Simulation excluded: "
            "production events arrive from the EHR's WQ history."
        ),
        "steps": [],
    }
    for n in args.claims:
        with tempfile.TemporaryDirectory() as tmp:
            print(f"benchmarking {n:,} claims ...", file=sys.stderr)
            results["steps"].append(bench(n, Path(tmp)))

    out_dir = REPO_ROOT / "benchmark" / "results"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = out_dir / f"benchmark_{stamp}.json"
    out_path.write_text(json.dumps(results, indent=2))
    print(f"\nresults written to {out_path}\n")
    print("| claims | events | analyze s | events/s | packet s | P | R |")
    print("|---:|---:|---:|---:|---:|---:|---:|")
    for s in results["steps"]:
        d = s["detection"]
        print(
            f"| {s['n_claims']:,} | {s['n_events']:,} | {s['timings_seconds']['analyze']} "
            f"| {s['analyze_events_per_second']:,} | {s['timings_seconds']['packet']} "
            f"| {d['claim_precision']} | {d['claim_recall']} |"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
