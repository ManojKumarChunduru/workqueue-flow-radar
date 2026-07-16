# ADR-0002: Detect conflicts from observed behavior, over static rule analysis

Status: accepted
Date: 2026-07-16

## Context

A conflicting rule pair can in principle be found two ways: statically,
by intersecting rule predicates and comparing target queues, or
behaviorally, by detecting the oscillation the conflict causes in the
event log.

## Options considered

1. Behavioral: detect oscillating claims, attribute to the rule pair
   from route_in rule ids.
2. Static: pairwise predicate intersection over the rule definitions.
3. Both.

## Decision

Option 1 first, with option 2 as the documented follow-on rather than a
rejected idea.

- Rule definitions are often not extractable. In real deployments the
  full rule set with evaluation semantics (precedence, context,
  overrides) is harder to obtain than WQ history, which lands in the
  reporting database as ordinary rows. A tool that needs only the
  event log deploys anywhere the history exists.
- Behavior includes the semantics static analysis has to guess.
  Precedence decides whether an overlap ever fires: this project's own
  default seed planted a conflict whose 86 matching claims were ALL
  captured by higher-priority rules, so the pair never produced a
  single oscillation. Static intersection would flag it; whether that
  flag is signal or noise depends on precedence and traffic, which the
  event log already encodes.
- Behavioral findings arrive priced. Victim claims, wasted hours,
  wasted touches: the numbers that turn a rule fix into a priority.

## Consequences

- Dormant conflicts are invisible by construction. The scorer therefore
  reports pairs as fired, attributed, or dormant, and the shipped
  default world honestly includes one dormant pair. The follow-on
  static analyzer is the right tool for those, and its trigger is
  organizational: when the team owns the rule export, add it.
- A conflict interrupted after a single bounce is indistinguishable
  from legitimate rework in the log; the min_oscillations threshold is
  the documented precision/recall dial.
