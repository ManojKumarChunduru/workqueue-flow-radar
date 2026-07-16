"""Simulate claims through the workqueue lifecycle, emitting the event
log the radar will analyze.

Event vocabulary (one row per event, mirroring how WQ history lands in
a Clarity-style extract):

    route_in   claim enters a workqueue (carries the routing rule_id)
    touch      a user works the claim
    defer      a user defers the claim (time passes)
    route_out  claim leaves the workqueue
    resolve    claim is closed

Three claim populations:

- Normal claims: route to their queue, get touched, maybe deferred,
  resolve. Most of the world.
- Rework claims (rework_rate): one legitimate round trip, queue A to
  queue B and back, exactly 2 transitions, then resolve. These exist to
  punish naive cycle detection: a single return is normal operations.
- Ping-pong victims: claims matching a planted conflicting rule pair
  oscillate between the pair's two queues for 3+ transitions until a
  supervisor force-resolves. Labeled as ground truth.

The radar never reads the labels; it must find the victims and name the
conflicting rule pairs from the event log alone.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd

from wq_radar.config import GeneratorConfig
from wq_radar.generator.rules_factory import ATTRIBUTES, Rule, build_rules, rules_frame

log = logging.getLogger(__name__)

BALANCE_RANGES = {
    "LT_500": (40, 500),
    "B500_5K": (500, 5_000),
    "B5K_25K": (5_000, 25_000),
    "GT_25K": (25_000, 180_000),
}
DEFAULT_WQ = "WQ00"
STAFF_PER_WQ = 4


@dataclass
class SimulationResult:
    claims: pd.DataFrame
    events: pd.DataFrame
    rules: pd.DataFrame
    ground_truth: pd.DataFrame


class _EventWriter:
    def __init__(self) -> None:
        self.rows: list[dict] = []
        self._n = 0

    def emit(self, claim_id: str, when: pd.Timestamp, event_type: str,
             wq_id: str, user_id: str | None, rule_id: str | None) -> None:
        self._n += 1
        self.rows.append(
            {
                "event_id": f"EV{self._n:010d}",
                "claim_id": claim_id,
                "event_time": when,
                "event_type": event_type,
                "wq_id": wq_id,
                "user_id": user_id,
                "rule_id": rule_id,
            }
        )


def _build_claims(cfg: GeneratorConfig, rng: np.random.Generator) -> pd.DataFrame:
    n = cfg.n_claims
    bands = rng.choice(list(BALANCE_RANGES), size=n)
    balances = np.array(
        [round(float(rng.uniform(*BALANCE_RANGES[b])), 2) for b in bands]
    )
    start = pd.Timestamp(cfg.start_date)
    created = start + pd.to_timedelta(
        rng.integers(0, cfg.horizon_days * 24 * 60, size=n), unit="m"
    )
    return pd.DataFrame(
        {
            "claim_id": [f"CLM{i:08d}" for i in range(n)],
            "payer_id": rng.choice(ATTRIBUTES["payer_id"], size=n),
            "department_id": rng.choice(ATTRIBUTES["department_id"], size=n),
            "carc_code": rng.choice(ATTRIBUTES["carc_code"], size=n),
            "balance_band": bands,
            "balance": balances,
            "created_at": created,
        }
    )


def _first_match(rules: list[Rule], claim: dict) -> Rule | None:
    for rule in rules:  # rules are priority-ordered
        if rule.matches(claim):
            return rule
    return None


def _staff(rng: np.random.Generator, wq_id: str) -> str:
    return f"{wq_id}_U{rng.integers(1, STAFF_PER_WQ + 1)}"


def simulate(cfg: GeneratorConfig) -> SimulationResult:
    rng = np.random.default_rng(cfg.seed)
    rules, conflicts = build_rules(cfg, rng)
    claims = _build_claims(cfg, rng)

    conflict_lookup: dict[str, dict] = {}
    for row in conflicts.itertuples(index=False):
        conflict_lookup[row.rule_b] = row._asdict()

    writer = _EventWriter()
    truth_rows: list[dict] = []

    hours = lambda h: pd.Timedelta(hours=float(h))  # noqa: E731

    for claim in claims.itertuples(index=False):
        cdict = claim._asdict()
        clock = claim.created_at
        rule = _first_match(rules, cdict)
        wq = rule.target_wq if rule else DEFAULT_WQ
        rule_id = rule.rule_id if rule else None
        writer.emit(claim.claim_id, clock, "route_in", wq, None, rule_id)

        # Does this claim sit on a planted conflict? It does when the
        # SUPERSET rule of a pair also matches: two live rules, two
        # different target queues.
        pair = None
        if rule is not None:
            for rule_b_id, row in conflict_lookup.items():
                rule_b = next(r for r in rules if r.rule_id == rule_b_id)
                if rule.rule_id in (row["rule_a"], rule_b_id) and rule_b.matches(cdict):
                    pair = row
                    break

        if pair is not None:
            # Oscillate: each queue's re-evaluation sends the claim to
            # the other queue of the pair. 3+ transitions, then a
            # supervisor force-resolves.
            transitions = int(rng.integers(3, cfg.max_bounce_cycles + 1))
            here = wq
            rule_for = {pair["wq_a"]: pair["rule_b"], pair["wq_b"]: pair["rule_a"]}
            for _ in range(transitions):
                clock += hours(rng.exponential(6) + 0.5)
                writer.emit(claim.claim_id, clock, "touch", here, _staff(rng, here), None)
                clock += hours(rng.exponential(1) + 0.1)
                writer.emit(claim.claim_id, clock, "route_out", here, None, None)
                there = pair["wq_b"] if here == pair["wq_a"] else pair["wq_a"]
                clock += hours(0.05)
                writer.emit(
                    claim.claim_id, clock, "route_in", there, None, rule_for[here]
                )
                here = there
            clock += hours(rng.exponential(8) + 1)
            writer.emit(claim.claim_id, clock, "resolve", here, _staff(rng, here), None)
            truth_rows.append(
                {"kind": "claim", "claim_id": claim.claim_id,
                 "pair_no": pair["pair_no"], "rule_a": pair["rule_a"],
                 "rule_b": pair["rule_b"], "wq_a": pair["wq_a"], "wq_b": pair["wq_b"]}
            )
            continue

        # Normal lifecycle in the landing queue.
        n_touches = max(1, int(rng.poisson(cfg.mean_touches_per_visit)))
        for _ in range(n_touches):
            clock += hours(rng.exponential(10) + 0.5)
            writer.emit(claim.claim_id, clock, "touch", wq, _staff(rng, wq), None)
            if rng.random() < cfg.defer_rate:
                clock += hours(rng.exponential(2) + 0.2)
                writer.emit(claim.claim_id, clock, "defer", wq, _staff(rng, wq), None)
                clock += hours(rng.exponential(48) + 12)

        if rng.random() < cfg.rework_rate:
            # Legitimate round trip: coding sends it out, it comes back.
            other = f"WQ{int(rng.integers(1, cfg.n_workqueues + 1)):02d}"
            if other == wq:
                other = DEFAULT_WQ
            clock += hours(rng.exponential(2) + 0.2)
            writer.emit(claim.claim_id, clock, "route_out", wq, None, None)
            clock += hours(0.05)
            writer.emit(claim.claim_id, clock, "route_in", other, None, None)
            clock += hours(rng.exponential(12) + 1)
            writer.emit(claim.claim_id, clock, "touch", other, _staff(rng, other), None)
            clock += hours(rng.exponential(1) + 0.1)
            writer.emit(claim.claim_id, clock, "route_out", other, None, None)
            clock += hours(0.05)
            writer.emit(claim.claim_id, clock, "route_in", wq, None, rule_id)
            clock += hours(rng.exponential(6) + 0.5)
            writer.emit(claim.claim_id, clock, "touch", wq, _staff(rng, wq), None)

        clock += hours(rng.exponential(4) + 0.5)
        writer.emit(claim.claim_id, clock, "resolve", wq, _staff(rng, wq), None)

    for row in conflicts.itertuples(index=False):
        truth_rows.append(
            {"kind": "rule_pair", "claim_id": None, "pair_no": row.pair_no,
             "rule_a": row.rule_a, "rule_b": row.rule_b,
             "wq_a": row.wq_a, "wq_b": row.wq_b}
        )

    events = pd.DataFrame(writer.rows)
    ground_truth = pd.DataFrame(truth_rows)
    log.info(
        "simulation complete",
        extra={
            "claims": len(claims),
            "events": len(events),
            "pingpong_victims": int((ground_truth["kind"] == "claim").sum()),
            "conflict_pairs": int((ground_truth["kind"] == "rule_pair").sum()),
        },
    )
    return SimulationResult(
        claims=claims, events=events, rules=rules_frame(rules), ground_truth=ground_truth
    )
