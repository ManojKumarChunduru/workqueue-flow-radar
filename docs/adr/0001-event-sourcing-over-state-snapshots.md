# ADR-0001: Reconstruct journeys from the event log, over storing per-claim state

Status: accepted
Date: 2026-07-16

## Context

The radar needs each claim's queue journey: which queues, in what
order, for how long, ending how. Two shapes were possible for the core
data model: maintain a per-claim state table updated as events arrive,
or keep only the immutable event log and reconstruct journeys at query
time.

## Options considered

1. Event log only; journeys reconstructed with window functions.
2. A materialized claim-state table maintained by the loader.
3. Both (event log plus a maintained rollup).

## Decision

Option 1: the event log is the only stored truth, and
`claim_journeys` is a view built with LAG/LEAD over route_in events.

- It matches reality. WQ history arrives from the EHR as events; a
  state table would be a derived artifact pretending to be a source.
- Every question stays answerable. Aging, touch counts, oscillation,
  and any future metric replay from the same log; a state table only
  answers the questions it was designed for.
- Determinism is a one-line fix at the right layer: staging orders by
  (event_time, event_id) so timestamp ties cannot shuffle journeys
  between runs. Correct ordering lives in one view instead of in every
  consumer.
- The reconstruction SQL is the demonstration this repo exists to
  make: visit chains, transition detection, and oscillation counting
  are window-function problems, and solving them in portable SQL is
  the skill a reporting team actually uses.

## Consequences

- Every analysis pays the reconstruction cost. Measured, that cost is
  acceptable: 1.1M events through all six models in 6.9 seconds on one
  vCPU. The trigger for adding option 3's rollup is an interactive
  consumer querying journeys many times per load.
- Open claims (no resolve event) have journeys that end at their last
  known event, which is the honest representation of an open claim.
