# TRACE v0.3 Relationship Intelligence

## Objective

Convert authoritative source observations into canonical graph relationships without collapsing evidence, source identity, time or uncertainty.

## Three-layer relation model

### 1. Source observation

A source says that A and B have relationship R under a defined source schema.

Stored in `relationship_observations` with:

- source;
- source record;
- subject;
- relation type;
- object;
- time interval;
- amount/currency if applicable;
- immutable semantic key;
- source-specific details.

### 2. Canonical relationship

Equivalent observations may reference one canonical relationship in `relationships`.

The canonical relationship is the object traversed by Path Finder.

### 3. Reconciliation state

Source disagreements remain visible in `reconciliation_conflicts` rather than being silently overwritten.

## Entity reconciliation policy

Priority order:

1. exact LEI;
2. exact CELEX;
3. exact EU Transparency Register ID;
4. exact source identifier;
5. exact cross-source national registration identifier with matching jurisdiction;
6. name similarity → human-review queue only.

Natural persons remain subject to the stronger v0.1 rule: name-only matching never auto-merges.

## GLEIF semantics

GLEIF Level 2 represents direct and ultimate **accounting consolidating parent** relationships. TRACE stores those semantics exactly and does not infer percentage ownership or beneficial ownership.

## TED semantics

TED eForms/search data can contain multiple buyers and multiple winners. TRACE therefore treats the notice as an explicit graph node.

Safe pattern:

```text
Buyer ──BUYER_FOR_PROCUREMENT_NOTICE──> Notice
Notice ──AWARDED_TO───────────────────> Winner
```

Only where buyer and winner are both unique does TRACE also create:

```text
Buyer ──AWARDED_CONTRACT_TO──> Winner
```

A notice-level total becomes a `money_flow` only when the payer/recipient pair is unambiguous.

## Lobbying semantics

TRACE distinguishes:

- registration in a transparency system;
- documented meeting with an institution;
- explicit disclosed interest in an identified policy/legal act.

Free-text subject similarity is not enough for `LOBBIED_ON`.

## Cellar legal graph

The Cellar metadata builder accepts only relation-like predicates whose RDF object resolves to a CELEX resource. Unknown predicates are ignored. This biases toward precision rather than recall.

## Reconciliation and Path Finder

Canonical relationships are committed directly to PostgreSQL. Path Finder therefore sees relationship-intelligence output immediately.

`/relationships/{id}/why` exposes both the original canonical claim evidence and all attached source observations/conflicts.
