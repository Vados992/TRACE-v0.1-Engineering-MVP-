"""TRACE v0.7 causal state and consequence engine.

Facts, derived analytics and simulations are deliberately separated. This module
does not infer causality from chronology: a causal edge is an explicit,
auditable assertion with its own evidence/model provenance.
"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from decimal import Decimal
from typing import Literal
from uuid import UUID, uuid4

from psycopg.types.json import Jsonb
from pydantic import AwareDatetime, Field, model_validator

from . import audit
from .adapters import StrictModel
from .db import connection

REALITY_BRANCH_ID = UUID("00000000-0000-0000-0000-000000000001")
EPISTEMIC = Literal["OBSERVED", "DERIVED", "SIMULATED"]
CAUSAL_EDGE_TYPES = {"CAUSES", "ENABLES", "CONTRIBUTES", "COUNTERFACTUAL"}


def canonical_hash(value) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def apply_merge_patch(state: dict, patch: dict) -> dict:
    """Deterministic RFC-7396-style merge patch for JSON objects."""
    result = deepcopy(state)
    for key in sorted(patch):
        value = patch[key]
        if value is None:
            result.pop(key, None)
        elif isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = apply_merge_patch(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


class BranchCreateRequest(StrictModel):
    name: str = Field(min_length=3, max_length=300)
    branch_type: Literal["COUNTERFACTUAL", "SCENARIO"]
    parent_branch_id: UUID = REALITY_BRANCH_ID
    fork_event_id: UUID | None = None
    assumptions: dict = Field(default_factory=dict)


class EventCreateRequest(StrictModel):
    event_key: str = Field(min_length=3, max_length=300)
    event_type: str = Field(min_length=2, max_length=200)
    epistemic_class: EPISTEMIC
    branch_id: UUID = REALITY_BRANCH_ID
    subject_entity_id: UUID | None = None
    object_entity_id: UUID | None = None
    source_record_id: UUID | None = None
    occurred_at: AwareDatetime
    correlation_id: UUID | None = None
    payload: dict = Field(default_factory=dict)
    confidence: Decimal = Field(default=Decimal("1"), ge=0, le=1)
    model_ref: str | None = Field(default=None, min_length=3, max_length=500)
    assumptions: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def provenance_boundary(self):
        if self.epistemic_class == "OBSERVED" and not self.source_record_id:
            raise ValueError("OBSERVED events require source_record_id")
        if self.epistemic_class != "OBSERVED" and not self.model_ref:
            raise ValueError("DERIVED/SIMULATED events require model_ref")
        if self.epistemic_class == "SIMULATED" and self.branch_id == REALITY_BRANCH_ID:
            raise ValueError("SIMULATED events cannot be written to the REALITY branch")
        return self


class CausalLinkRequest(StrictModel):
    cause_event_id: UUID
    effect_event_id: UUID
    edge_type: Literal["CAUSES", "ENABLES", "CONTRIBUTES", "CORRELATES", "COUNTERFACTUAL"]
    epistemic_class: EPISTEMIC
    evidence_source_record_id: UUID | None = None
    confidence: Decimal = Field(ge=0, le=1)
    rationale: str = Field(min_length=10, max_length=5000)
    model_ref: str | None = Field(default=None, min_length=3, max_length=500)

    @model_validator(mode="after")
    def provenance_boundary(self):
        if self.cause_event_id == self.effect_event_id:
            raise ValueError("self-causation is not allowed")
        if self.epistemic_class == "OBSERVED" and not self.evidence_source_record_id:
            raise ValueError("OBSERVED causal edges require evidence_source_record_id")
        if self.epistemic_class != "OBSERVED" and not self.model_ref:
            raise ValueError("DERIVED/SIMULATED causal edges require model_ref")
        return self


class StateSeedRequest(StrictModel):
    entity_id: UUID
    branch_id: UUID = REALITY_BRANCH_ID
    as_of: AwareDatetime
    epistemic_class: EPISTEMIC
    state: dict
    source_event_id: UUID | None = None
    confidence: Decimal = Field(default=Decimal("1"), ge=0, le=1)
    model_ref: str | None = Field(default=None, min_length=3, max_length=500)
    assumptions: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def provenance_boundary(self):
        if not self.state:
            raise ValueError("base state cannot be empty")
        if self.epistemic_class == "OBSERVED" and not self.source_event_id:
            raise ValueError("OBSERVED state requires source_event_id")
        if self.epistemic_class != "OBSERVED" and not self.model_ref:
            raise ValueError("DERIVED/SIMULATED state requires model_ref")
        if self.epistemic_class == "SIMULATED" and self.branch_id == REALITY_BRANCH_ID:
            raise ValueError("SIMULATED state cannot be written to the REALITY branch")
        return self


class StateTransitionRequest(StrictModel):
    entity_id: UUID
    branch_id: UUID = REALITY_BRANCH_ID
    event_id: UUID
    base_snapshot_id: UUID
    patch: dict

    @model_validator(mode="after")
    def non_empty_patch(self):
        if not self.patch:
            raise ValueError("transition patch cannot be empty")
        return self


class ReplayRequest(StrictModel):
    entity_id: UUID
    branch_id: UUID = REALITY_BRANCH_ID
    until: AwareDatetime | None = None


class CausalStateService:
    async def create_branch(self, body: BranchCreateRequest, actor: str):
        async with connection() as conn:
            async with conn.transaction():
                parent = await (
                    await conn.execute(
                        "SELECT id,branch_type FROM causal_branches WHERE id=%s",
                        (body.parent_branch_id,),
                    )
                ).fetchone()
                if not parent:
                    raise ValueError("parent branch not found")
                if body.fork_event_id:
                    event = await (
                        await conn.execute(
                            "SELECT branch_id FROM causal_events WHERE id=%s",
                            (body.fork_event_id,),
                        )
                    ).fetchone()
                    if not event or event["branch_id"] != body.parent_branch_id:
                        raise ValueError("fork_event_id must belong to parent branch")
                row = await (
                    await conn.execute(
                        """INSERT INTO causal_branches(
                               name,branch_type,parent_branch_id,fork_event_id,assumptions,created_by
                           ) VALUES (%s,%s,%s,%s,%s,%s)
                           RETURNING id,name,branch_type,parent_branch_id,fork_event_id,created_at""",
                        (
                            body.name,
                            body.branch_type,
                            body.parent_branch_id,
                            body.fork_event_id,
                            Jsonb(body.assumptions),
                            actor,
                        ),
                    )
                ).fetchone()
                await audit.record(
                    conn,
                    actor,
                    "CAUSAL_BRANCH_CREATED",
                    str(row["id"]),
                    {"branch_type": body.branch_type},
                )
                return row

    async def create_event(self, body: EventCreateRequest, actor: str):
        async with connection() as conn:
            async with conn.transaction():
                branch = await (
                    await conn.execute(
                        "SELECT branch_type FROM causal_branches WHERE id=%s",
                        (body.branch_id,),
                    )
                ).fetchone()
                if not branch:
                    raise ValueError("branch not found")
                if body.epistemic_class == "OBSERVED" and branch["branch_type"] != "REALITY":
                    raise ValueError("OBSERVED events belong only to REALITY")
                if body.epistemic_class == "SIMULATED" and branch["branch_type"] == "REALITY":
                    raise ValueError("SIMULATED events require a non-reality branch")
                material = body.model_dump(mode="json")
                event_hash = canonical_hash(material)
                row = await (
                    await conn.execute(
                        """INSERT INTO causal_events(
                               event_key,event_hash,branch_id,event_type,epistemic_class,
                               subject_entity_id,object_entity_id,source_record_id,occurred_at,
                               correlation_id,payload,confidence,model_ref,assumptions,created_by
                           ) VALUES (
                               %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s
                           )
                           RETURNING id,event_key,event_hash,branch_id,event_type,
                                     epistemic_class,occurred_at,confidence,created_at""",
                        (
                            body.event_key,
                            event_hash,
                            body.branch_id,
                            body.event_type,
                            body.epistemic_class,
                            body.subject_entity_id,
                            body.object_entity_id,
                            body.source_record_id,
                            body.occurred_at,
                            body.correlation_id,
                            Jsonb(body.payload),
                            body.confidence,
                            body.model_ref,
                            Jsonb(body.assumptions),
                            actor,
                        ),
                    )
                ).fetchone()
                await audit.record(
                    conn,
                    actor,
                    "CAUSAL_EVENT_CREATED",
                    str(row["id"]),
                    {
                        "event_type": body.event_type,
                        "epistemic_class": body.epistemic_class,
                        "event_hash": event_hash,
                    },
                )
                return row

    async def link_events(self, body: CausalLinkRequest, actor: str):
        if body.edge_type in CAUSAL_EDGE_TYPES:
            causal = True
        else:
            causal = False
        async with connection() as conn:
            async with conn.transaction():
                events = await (
                    await conn.execute(
                        """SELECT id,branch_id,occurred_at FROM causal_events
                           WHERE id=ANY(%s)""",
                        ([body.cause_event_id, body.effect_event_id],),
                    )
                ).fetchall()
                by_id = {row["id"]: row for row in events}
                if len(by_id) != 2:
                    raise ValueError("cause/effect event not found")
                cause = by_id[body.cause_event_id]
                effect = by_id[body.effect_event_id]
                if cause["branch_id"] != effect["branch_id"]:
                    raise ValueError("causal edges cannot cross branches")
                if causal and cause["occurred_at"] > effect["occurred_at"]:
                    raise ValueError("cause cannot occur after effect")
                if causal:
                    cycle = await (
                        await conn.execute(
                            """WITH RECURSIVE reach(id,path) AS (
                                   SELECT effect_event_id,ARRAY[cause_event_id,effect_event_id]
                                   FROM causal_edges
                                   WHERE cause_event_id=%s
                                     AND edge_type IN ('CAUSES','ENABLES','CONTRIBUTES','COUNTERFACTUAL')
                                   UNION ALL
                                   SELECT e.effect_event_id,r.path || e.effect_event_id
                                   FROM causal_edges e
                                   JOIN reach r ON e.cause_event_id=r.id
                                   WHERE e.edge_type IN ('CAUSES','ENABLES','CONTRIBUTES','COUNTERFACTUAL')
                                     AND NOT e.effect_event_id=ANY(r.path)
                               )
                               SELECT 1 AS found FROM reach WHERE id=%s LIMIT 1""",
                            (body.effect_event_id, body.cause_event_id),
                        )
                    ).fetchone()
                    if cycle:
                        raise ValueError("causal edge would create a cycle")
                row = await (
                    await conn.execute(
                        """INSERT INTO causal_edges(
                               cause_event_id,effect_event_id,edge_type,epistemic_class,
                               evidence_source_record_id,confidence,rationale,model_ref,created_by
                           ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                           RETURNING id,cause_event_id,effect_event_id,edge_type,
                                     epistemic_class,confidence,created_at""",
                        (
                            body.cause_event_id,
                            body.effect_event_id,
                            body.edge_type,
                            body.epistemic_class,
                            body.evidence_source_record_id,
                            body.confidence,
                            body.rationale,
                            body.model_ref,
                            actor,
                        ),
                    )
                ).fetchone()
                await audit.record(
                    conn,
                    actor,
                    "CAUSAL_EDGE_CREATED",
                    str(row["id"]),
                    {
                        "edge_type": body.edge_type,
                        "epistemic_class": body.epistemic_class,
                    },
                )
                return row

    async def seed_state(self, body: StateSeedRequest, actor: str):
        state_hash = canonical_hash(body.state)
        async with connection() as conn:
            async with conn.transaction():
                branch = await (
                    await conn.execute(
                        "SELECT branch_type FROM causal_branches WHERE id=%s",
                        (body.branch_id,),
                    )
                ).fetchone()
                if not branch:
                    raise ValueError("branch not found")
                if body.epistemic_class == "OBSERVED" and branch["branch_type"] != "REALITY":
                    raise ValueError("OBSERVED state belongs only to REALITY")
                if body.epistemic_class == "SIMULATED" and branch["branch_type"] == "REALITY":
                    raise ValueError("SIMULATED state requires a non-reality branch")
                if body.source_event_id:
                    event = await (
                        await conn.execute(
                            "SELECT branch_id,occurred_at FROM causal_events WHERE id=%s",
                            (body.source_event_id,),
                        )
                    ).fetchone()
                    if not event or event["branch_id"] != body.branch_id:
                        raise ValueError("source_event_id must belong to the same branch")
                    if event["occurred_at"] > body.as_of:
                        raise ValueError("base state cannot predate its source event")
                row = await (
                    await conn.execute(
                        """INSERT INTO entity_state_snapshots(
                               entity_id,branch_id,snapshot_kind,as_of,epistemic_class,state,
                               state_hash,source_event_id,confidence,model_ref,assumptions,created_by
                           ) VALUES (%s,%s,'BASE',%s,%s,%s,%s,%s,%s,%s,%s,%s)
                           RETURNING id,entity_id,branch_id,as_of,epistemic_class,state_hash,created_at""",
                        (
                            body.entity_id,
                            body.branch_id,
                            body.as_of,
                            body.epistemic_class,
                            Jsonb(body.state),
                            state_hash,
                            body.source_event_id,
                            body.confidence,
                            body.model_ref,
                            Jsonb(body.assumptions),
                            actor,
                        ),
                    )
                ).fetchone()
                await audit.record(
                    conn,
                    actor,
                    "STATE_BASE_CREATED",
                    str(row["id"]),
                    {"entity_id": str(body.entity_id), "state_hash": state_hash},
                )
                return row

    async def apply_transition(self, body: StateTransitionRequest, actor: str):
        async with connection() as conn:
            async with conn.transaction():
                base = await (
                    await conn.execute(
                        """SELECT id,entity_id,branch_id,as_of,state,state_hash
                           FROM entity_state_snapshots WHERE id=%s""",
                        (body.base_snapshot_id,),
                    )
                ).fetchone()
                if not base:
                    raise ValueError("base snapshot not found")
                if base["entity_id"] != body.entity_id or base["branch_id"] != body.branch_id:
                    raise ValueError("base snapshot does not match entity/branch")
                if canonical_hash(base["state"]) != base["state_hash"]:
                    raise ValueError("base snapshot integrity failure")
                event = await (
                    await conn.execute(
                        """SELECT id,branch_id,occurred_at,epistemic_class,model_ref
                           FROM causal_events WHERE id=%s""",
                        (body.event_id,),
                    )
                ).fetchone()
                if not event or event["branch_id"] != body.branch_id:
                    raise ValueError("event does not belong to state branch")
                if event["occurred_at"] < base["as_of"]:
                    raise ValueError("transition event predates base snapshot")
                new_state = apply_merge_patch(base["state"], body.patch)
                new_hash = canonical_hash(new_state)
                changed = sorted(
                    key
                    for key in set(base["state"]) | set(new_state)
                    if base["state"].get(key) != new_state.get(key)
                )
                transition_class = event["epistemic_class"] + "_APPLY"
                snapshot = await (
                    await conn.execute(
                        """INSERT INTO entity_state_snapshots(
                               entity_id,branch_id,snapshot_kind,as_of,epistemic_class,state,
                               state_hash,source_event_id,confidence,model_ref,assumptions,created_by
                           ) VALUES (%s,%s,'TRANSITION',%s,%s,%s,%s,%s,1,%s,'{}'::jsonb,%s)
                           RETURNING id,entity_id,branch_id,as_of,epistemic_class,state_hash""",
                        (
                            body.entity_id,
                            body.branch_id,
                            event["occurred_at"],
                            event["epistemic_class"],
                            Jsonb(new_state),
                            new_hash,
                            body.event_id,
                            event["model_ref"],
                            actor,
                        ),
                    )
                ).fetchone()
                transition = await (
                    await conn.execute(
                        """INSERT INTO state_transitions(
                               entity_id,branch_id,event_id,from_snapshot_id,to_snapshot_id,
                               transition_class,patch,changed_keys,before_hash,after_hash,created_by
                           ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                           RETURNING id,event_id,from_snapshot_id,to_snapshot_id,
                                     transition_class,changed_keys,before_hash,after_hash,created_at""",
                        (
                            body.entity_id,
                            body.branch_id,
                            body.event_id,
                            body.base_snapshot_id,
                            snapshot["id"],
                            transition_class,
                            Jsonb(body.patch),
                            Jsonb(changed),
                            base["state_hash"],
                            new_hash,
                            actor,
                        ),
                    )
                ).fetchone()
                await audit.record(
                    conn,
                    actor,
                    "STATE_TRANSITION_APPLIED",
                    str(transition["id"]),
                    {
                        "event_id": str(body.event_id),
                        "before_hash": base["state_hash"],
                        "after_hash": new_hash,
                        "changed_keys": changed,
                    },
                )
                return {"snapshot": snapshot, "transition": transition}

    async def replay(self, body: ReplayRequest):
        async with connection() as conn:
            base = await (
                await conn.execute(
                    """SELECT id,state,state_hash,as_of FROM entity_state_snapshots
                       WHERE entity_id=%s AND branch_id=%s AND snapshot_kind='BASE'""",
                    (body.entity_id, body.branch_id),
                )
            ).fetchone()
            if not base:
                raise ValueError("base snapshot not found")
            state = base["state"]
            if canonical_hash(state) != base["state_hash"]:
                raise ValueError("base snapshot integrity failure")
            args = [body.entity_id, body.branch_id]
            cutoff = ""
            if body.until is not None:
                cutoff = " AND e.occurred_at <= %s"
                args.append(body.until)
            rows = await (
                await conn.execute(
                    f"""SELECT t.id,t.event_id,t.patch,t.before_hash,t.after_hash,
                               e.occurred_at,e.event_type,e.epistemic_class
                        FROM state_transitions t
                        JOIN causal_events e ON e.id=t.event_id
                        WHERE t.entity_id=%s AND t.branch_id=%s{cutoff}
                        ORDER BY e.occurred_at,t.created_at,t.id""",
                    tuple(args),
                )
            ).fetchall()
            current_hash = base["state_hash"]
            timeline = []
            for row in rows:
                if row["before_hash"] != current_hash:
                    raise ValueError("transition chain discontinuity")
                state = apply_merge_patch(state, row["patch"])
                current_hash = canonical_hash(state)
                if current_hash != row["after_hash"]:
                    raise ValueError("transition replay hash mismatch")
                timeline.append(
                    {
                        "event_id": row["event_id"],
                        "event_type": row["event_type"],
                        "epistemic_class": row["epistemic_class"],
                        "occurred_at": row["occurred_at"],
                        "state_hash": current_hash,
                    }
                )
            return {
                "entity_id": body.entity_id,
                "branch_id": body.branch_id,
                "base_snapshot_id": base["id"],
                "events_applied": len(rows),
                "state": state,
                "state_hash": current_hash,
                "timeline": timeline,
            }

    async def graph(
        self,
        event_id: UUID,
        direction: Literal["downstream", "upstream"] = "downstream",
        max_depth: int = 5,
    ):
        if not 1 <= max_depth <= 8:
            raise ValueError("max_depth must be between 1 and 8")
        if direction == "downstream":
            seed = "cause_event_id=%s"
            join = "e.cause_event_id=w.effect_event_id"
            next_id = "e.effect_event_id"
        else:
            seed = "effect_event_id=%s"
            join = "e.effect_event_id=w.cause_event_id"
            next_id = "e.cause_event_id"
        sql = f"""WITH RECURSIVE walk AS (
                     SELECT id,cause_event_id,effect_event_id,edge_type,epistemic_class,
                            confidence,rationale,1 AS depth,
                            ARRAY[cause_event_id,effect_event_id] AS path
                     FROM causal_edges WHERE {seed}
                     UNION ALL
                     SELECT e.id,e.cause_event_id,e.effect_event_id,e.edge_type,
                            e.epistemic_class,e.confidence,e.rationale,w.depth+1,
                            w.path || {next_id}
                     FROM causal_edges e
                     JOIN walk w ON {join}
                     WHERE w.depth < %s AND NOT {next_id}=ANY(w.path)
                 )
                 SELECT w.*,c.event_type AS cause_type,c.occurred_at AS cause_time,
                        x.event_type AS effect_type,x.occurred_at AS effect_time
                 FROM walk w
                 JOIN causal_events c ON c.id=w.cause_event_id
                 JOIN causal_events x ON x.id=w.effect_event_id
                 ORDER BY w.depth,c.occurred_at,x.occurred_at,w.id"""
        async with connection() as conn:
            root = await (
                await conn.execute("SELECT id FROM causal_events WHERE id=%s", (event_id,))
            ).fetchone()
            if not root:
                raise ValueError("event not found")
            return await (await conn.execute(sql, (event_id, max_depth))).fetchall()

    async def consequences(self, event_id: UUID, max_depth: int = 5):
        edges = await self.graph(event_id, "downstream", max_depth)
        event_ids = sorted({row["effect_event_id"] for row in edges}, key=str)
        if not event_ids:
            return {"root_event_id": event_id, "edges": [], "state_changes": []}
        async with connection() as conn:
            changes = await (
                await conn.execute(
                    """SELECT t.id,t.event_id,t.entity_id,t.branch_id,t.transition_class,
                              t.changed_keys,t.before_hash,t.after_hash,e.occurred_at
                       FROM state_transitions t
                       JOIN causal_events e ON e.id=t.event_id
                       WHERE t.event_id=ANY(%s)
                       ORDER BY e.occurred_at,t.id""",
                    (event_ids,),
                )
            ).fetchall()
        return {"root_event_id": event_id, "edges": edges, "state_changes": changes}


def new_correlation_id() -> UUID:
    return uuid4()
