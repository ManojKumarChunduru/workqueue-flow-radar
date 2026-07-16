"""Score radar output against the simulator's ground truth.

Two levels:

- Claim level: precision and recall of ping-pong victim detection.
  Rework claims (legitimate single round trips) are the natural false
  positive pressure; flagging them means the oscillation threshold is
  wrong.
- Rule-pair level: of the planted conflicting pairs that actually FIRED
  (at least one victim claim in the window), how many did attribution
  name correctly, matching both queues and both rule ids. Pairs that
  never fired are reported as dormant, not as misses: a behavioral
  detector cannot see a conflict that produced no behavior, and saying
  so is the point of ADR-0002.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass

import pandas as pd

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Score:
    claim_precision: float
    claim_recall: float
    victims_planted: int
    victims_detected: int
    true_positives: int
    pairs_planted: int
    pairs_fired: int
    pairs_attributed: int
    pairs_dormant: int
    pair_attribution_rate: float

    def as_dict(self) -> dict:
        return asdict(self)


def score(
    pingpong: pd.DataFrame, conflict_pairs: pd.DataFrame, ground_truth: pd.DataFrame
) -> Score:
    truth_claims = ground_truth[ground_truth["kind"] == "claim"]
    truth_pairs = ground_truth[ground_truth["kind"] == "rule_pair"]

    victims = set(truth_claims["claim_id"])
    detected = set(pingpong["claim_id"]) if not pingpong.empty else set()
    tp = len(victims & detected)
    precision = tp / len(detected) if detected else 0.0
    recall = tp / len(victims) if victims else 0.0

    fired_pair_nos = set(truth_claims["pair_no"])
    detected_pairs = set()
    if not conflict_pairs.empty:
        for row in conflict_pairs.itertuples(index=False):
            detected_pairs.add(
                (frozenset({row.wq_x, row.wq_y}), frozenset({row.rule_into_x, row.rule_into_y}))
            )

    attributed = 0
    for row in truth_pairs.itertuples(index=False):
        if row.pair_no not in fired_pair_nos:
            continue
        key = (frozenset({row.wq_a, row.wq_b}), frozenset({row.rule_a, row.rule_b}))
        if key in detected_pairs:
            attributed += 1

    pairs_fired = len(fired_pair_nos)
    result = Score(
        claim_precision=round(precision, 4),
        claim_recall=round(recall, 4),
        victims_planted=len(victims),
        victims_detected=len(detected),
        true_positives=tp,
        pairs_planted=len(truth_pairs),
        pairs_fired=pairs_fired,
        pairs_attributed=attributed,
        pairs_dormant=len(truth_pairs) - pairs_fired,
        pair_attribution_rate=round(attributed / pairs_fired, 4) if pairs_fired else 0.0,
    )
    log.info("scoring complete", extra=result.as_dict())
    return result
