# TRACE v0.7 — Causal State & Consequence Layer

## Purpose

TRACE v0.7 extends evidence-grounded verification with an explicit event/state
model. It answers a different class of question from Path Finder:

- what changed;
- which explicit event preceded another;
- which causal assertion is evidence-backed versus model-derived;
- how an entity state changes after an event;
- whether the same state can be deterministically replayed;
- what downstream consequences are linked to a root event;
- how scenario/counterfactual branches remain separated from observed reality.

The layer **does not infer causality from chronology**. A causal edge is its own
auditable analytical object with provenance, confidence and epistemic class.

## Hard epistemic boundary

Every event and state snapshot is one of:

- `OBSERVED` — grounded in a TRACE source/evidence record;
- `DERIVED` — produced by an identified analytical model;
- `SIMULATED` — produced only on a non-reality scenario/counterfactual branch.

A simulated event cannot be written to the canonical REALITY branch. An
observed event cannot be written to a scenario branch.

## Canonical objects

### causal_branches

The fixed REALITY branch has UUID
`00000000-0000-0000-0000-000000000001`. Counterfactual and scenario branches
must have a parent branch and can optionally identify the event at which they
forked.

### causal_events

Canonical fields include event key/type, branch, epistemic class, subject and
object entities, source record or model reference, occurrence time, correlation
ID, payload, confidence, assumptions and a stable SHA-256 event hash.

### causal_edges

Edges are explicit assertions: `CAUSES`, `ENABLES`, `CONTRIBUTES`,
`CORRELATES`, or `COUNTERFACTUAL`. Causal edges are constrained to one
branch, cannot point backwards in event time and are rejected when they would
create a causal cycle.

### entity_state_snapshots / state_transitions

An entity+branch has one immutable BASE snapshot. Each applied event creates a
new immutable TRANSITION snapshot and an append-only transition receipt with
the JSON merge patch, changed keys and before/after hashes.

## Deterministic replay

Replay starts from the BASE snapshot, applies persisted transition patches in
event-time order, and verifies the hash before and after every step. A broken
chain fails closed instead of returning a reconstructed state.

## Consequence traversal

The consequence endpoint performs bounded downstream traversal of explicit
causal edges and joins downstream events to state transition receipts. It
therefore reports what the stored causal model says changed without promoting
that model to an observed fact.

## Internal API

All routes are internal/authenticated and intentionally excluded from the
public OpenAPI contract:

- `POST /api/internal/causal/branches`
- `POST /api/internal/causal/events`
- `POST /api/internal/causal/links`
- `POST /api/internal/causal/state/seed`
- `POST /api/internal/causal/state/transition`
- `POST /api/internal/causal/state/replay`
- `GET /api/internal/causal/events/{id}/graph`
- `GET /api/internal/causal/events/{id}/consequences`

## Governance

v0.7 is decision-support infrastructure, not an automated legal conclusion
engine. `DERIVED` and `SIMULATED` outputs must remain visibly labelled in
all downstream user interfaces and reports. Corrections are represented by new
append-only objects; historical analytical receipts are not destructively
rewritten.
