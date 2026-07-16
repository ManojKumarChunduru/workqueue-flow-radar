"""Typed configuration loading.

config/settings.yaml drives the tool, overridable with WQ_RADAR_CONFIG
(file path) or WQ_RADAR__SECTION__KEY environment variables.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

ENV_CONFIG_PATH = "WQ_RADAR_CONFIG"
ENV_PREFIX = "WQ_RADAR__"


@dataclass(frozen=True)
class GeneratorConfig:
    seed: int = 42
    n_claims: int = 20_000
    start_date: str = "2025-05-01"
    horizon_days: int = 30
    n_workqueues: int = 8
    n_rules: int = 24
    n_conflicting_pairs: int = 3
    mean_touches_per_visit: float = 1.6
    defer_rate: float = 0.12
    rework_rate: float = 0.05
    max_bounce_cycles: int = 6

    def __post_init__(self) -> None:
        if self.n_claims <= 0:
            raise ValueError("n_claims must be positive")
        for name in ("defer_rate", "rework_rate"):
            if not 0.0 <= getattr(self, name) <= 1.0:
                raise ValueError(f"{name} must be within [0, 1]")
        if self.n_conflicting_pairs * 2 > self.n_rules:
            raise ValueError("not enough rules to host the conflicting pairs")
        if self.max_bounce_cycles < 2:
            raise ValueError("max_bounce_cycles must be at least 2")


@dataclass(frozen=True)
class AnalysisConfig:
    min_oscillations: int = 3

    def __post_init__(self) -> None:
        if self.min_oscillations < 2:
            raise ValueError("min_oscillations below 2 would flag every rework return")


@dataclass(frozen=True)
class PathsConfig:
    data_dir: str = "data"
    events_file: str = "data/wq_events.parquet"
    claims_file: str = "data/claims.parquet"
    rules_file: str = "data/routing_rules.parquet"
    labels_file: str = "data/ground_truth.parquet"
    duckdb_file: str = "data/radar.duckdb"
    output_dir: str = "output"


@dataclass(frozen=True)
class Settings:
    generator: GeneratorConfig = field(default_factory=GeneratorConfig)
    analysis: AnalysisConfig = field(default_factory=AnalysisConfig)
    paths: PathsConfig = field(default_factory=PathsConfig)


def _coerce(raw: str, template: object) -> object:
    if isinstance(template, bool):
        return raw.lower() in {"1", "true", "yes"}
    if isinstance(template, int):
        return int(raw)
    if isinstance(template, float):
        return float(raw)
    return raw


def _apply_env_overrides(data: dict) -> dict:
    for key, value in os.environ.items():
        if not key.startswith(ENV_PREFIX):
            continue
        path = key[len(ENV_PREFIX):].lower().split("__")
        if len(path) != 2:
            continue
        section, leaf = path
        if section in data and leaf in data[section]:
            data[section][leaf] = _coerce(value, data[section][leaf])
    return data


def load_settings(config_path: str | Path | None = None) -> Settings:
    path = Path(config_path or os.environ.get(ENV_CONFIG_PATH, "config/settings.yaml"))
    data: dict = {}
    if path.exists():
        with path.open() as fh:
            data = yaml.safe_load(fh) or {}
    for section in ("generator", "analysis", "paths"):
        data.setdefault(section, {})
    data = _apply_env_overrides(data)
    return Settings(
        generator=GeneratorConfig(**data["generator"]),
        analysis=AnalysisConfig(**data["analysis"]),
        paths=PathsConfig(**data["paths"]),
    )
