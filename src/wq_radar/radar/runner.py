"""Run the SQL model chain over the event log.

Models execute in filename order; only 05_pingpong_detection.sql takes a
parameter (min_oscillations, a validated integer rendered into the
template). Everything else is static SQL.
"""

from __future__ import annotations

import logging
from importlib import resources
from pathlib import Path

import duckdb
import pandas as pd

from wq_radar.config import AnalysisConfig

log = logging.getLogger(__name__)

MODEL_ORDER = [
    "01_stg_events",
    "02_claim_journeys",
    "03_fct_wq_kpis",
    "04_fct_claim_stats",
    "05_pingpong_detection",
    "06_conflict_pairs",
]


def _sql(name: str) -> str:
    return (resources.files("wq_radar") / "sql" / f"{name}.sql").read_text()


class Radar:
    def __init__(self, analysis: AnalysisConfig,
                 con: duckdb.DuckDBPyConnection | None = None) -> None:
        self.analysis = analysis
        self.con = con or duckdb.connect()

    def load_events(self, events: pd.DataFrame | str | Path) -> int:
        if isinstance(events, (str, Path)):
            path = Path(events)
            if not path.exists():
                raise FileNotFoundError(
                    f"{path} not found. Run the simulator first: wq-radar generate"
                )
            self.con.execute(
                "CREATE OR REPLACE TABLE raw_events AS SELECT * FROM read_parquet(?)",
                [str(path)],
            )
        else:
            self.con.register("events_df", events)
            self.con.execute(
                "CREATE OR REPLACE TABLE raw_events AS SELECT * FROM events_df"
            )
        n = self.con.execute("SELECT COUNT(*) FROM raw_events").fetchone()[0]
        log.info("events loaded", extra={"rows": n})
        return n

    def build_models(self) -> None:
        if not isinstance(self.analysis.min_oscillations, int):
            raise TypeError("min_oscillations must be an integer")
        for name in MODEL_ORDER:
            sql = _sql(name).replace(
                "{min_oscillations}", str(self.analysis.min_oscillations)
            )
            self.con.execute(sql)
            log.info("model built", extra={"model": name})

    def frame(self, view: str) -> pd.DataFrame:
        if view not in MODEL_ORDER and view not in {
            "stg_events", "claim_journeys", "fct_wq_kpis",
            "fct_claim_stats", "pingpong_claims", "conflict_pairs",
        }:
            raise ValueError(f"unknown view: {view}")
        return self.con.execute(f"SELECT * FROM {view}").fetchdf()  # noqa: S608
