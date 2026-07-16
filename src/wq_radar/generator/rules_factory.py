"""Build the routing rule set, including planted conflicting pairs.

A routing rule is a predicate over claim attributes plus a target
workqueue: "denials with CARC 197 for payer PAY02 route to WQ_AUTH".
Real HB rule sets accrete for years across analysts, and the classic
failure is two rules whose predicates overlap but route to different
queues. When queue A's rule engine re-evaluates a claim it routes it to
B; B's engine routes it back to A. Staff see the same claim reappear;
nobody sees the pair of rules causing it.

The factory builds a plausible rule set and plants n_conflicting_pairs
of overlapping rules. Ground truth (which pairs conflict) is written to
the labels file the radar never reads.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from wq_radar.config import GeneratorConfig

PAYERS = ["PAY01", "PAY02", "PAY03", "PAY04", "PAY05", "PAY06"]
DEPARTMENTS = ["ED", "ISRG", "OSRG", "RAD", "CARD", "LAB", "PT", "ONC", "OB", "MED"]
CARC_CODES = ["16", "18", "29", "45", "50", "197", "11", "4", "27", "23"]
BALANCE_BANDS = ["LT_500", "B500_5K", "B5K_25K", "GT_25K"]

ATTRIBUTES = {
    "payer_id": PAYERS,
    "department_id": DEPARTMENTS,
    "carc_code": CARC_CODES,
    "balance_band": BALANCE_BANDS,
}


@dataclass(frozen=True)
class Rule:
    rule_id: str
    predicate: dict[str, str]  # attribute -> required value (AND semantics)
    target_wq: str
    priority: int

    def matches(self, claim: dict) -> bool:
        return all(claim.get(attr) == val for attr, val in self.predicate.items())


def build_rules(cfg: GeneratorConfig, rng: np.random.Generator) -> tuple[list[Rule], pd.DataFrame]:
    workqueues = [f"WQ{i:02d}" for i in range(1, cfg.n_workqueues + 1)]
    rules: list[Rule] = []
    conflict_rows: list[dict] = []

    n_plain = cfg.n_rules - 2 * cfg.n_conflicting_pairs

    # Plain rules: 2-attribute predicates, distinct enough to not collide.
    used_predicates: set[tuple] = set()
    while len(rules) < n_plain:
        attrs = rng.choice(list(ATTRIBUTES), size=2, replace=False)
        predicate = {a: str(rng.choice(ATTRIBUTES[a])) for a in attrs}
        key = tuple(sorted(predicate.items()))
        if key in used_predicates:
            continue
        used_predicates.add(key)
        rules.append(
            Rule(
                rule_id=f"R{len(rules) + 1:03d}",
                predicate=predicate,
                target_wq=str(rng.choice(workqueues)),
                priority=len(rules) + 1,
            )
        )

    # Conflicting pairs: both rules match the same claim shape (rule B's
    # predicate is a superset of rule A's), but they route to different
    # queues. Claims matching B match both; whichever queue the claim
    # sits in, the other rule pulls it away.
    for pair_no in range(cfg.n_conflicting_pairs):
        attrs = rng.choice(list(ATTRIBUTES), size=2, replace=False)
        base_pred = {a: str(rng.choice(ATTRIBUTES[a])) for a in attrs}
        extra_attr = str(rng.choice([a for a in ATTRIBUTES if a not in base_pred]))
        super_pred = dict(base_pred)
        super_pred[extra_attr] = str(rng.choice(ATTRIBUTES[extra_attr]))

        wq_a, wq_b = rng.choice(workqueues, size=2, replace=False)
        rule_a = Rule(
            rule_id=f"R{len(rules) + 1:03d}", predicate=base_pred,
            target_wq=str(wq_a), priority=len(rules) + 1,
        )
        rules.append(rule_a)
        rule_b = Rule(
            rule_id=f"R{len(rules) + 1:03d}", predicate=super_pred,
            target_wq=str(wq_b), priority=len(rules) + 1,
        )
        rules.append(rule_b)
        conflict_rows.append(
            {
                "pair_no": pair_no,
                "rule_a": rule_a.rule_id,
                "rule_b": rule_b.rule_id,
                "wq_a": rule_a.target_wq,
                "wq_b": rule_b.target_wq,
                "conflict_predicate": str(sorted(super_pred.items())),
            }
        )

    return rules, pd.DataFrame(conflict_rows)


def rules_frame(rules: list[Rule]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "rule_id": r.rule_id,
                "predicate": str(sorted(r.predicate.items())),
                "target_wq": r.target_wq,
                "priority": r.priority,
            }
            for r in rules
        ]
    )
