# RFC-C002 — Capability Lineage & Dependency Mapping

Status: IMPLEMENTED_UNVERIFIED

## Purpose

C-002 creates a read-only governance layer that answers:

```text
capability
-> prerequisites
-> implementation components
-> evidence/verifiers
-> freshness
-> downstream dependents
-> regression blast radius
```

It does not grant runtime authority, execute another capability, mutate the roadmap automatically,
or certify a capability as improved or production-ready.

## Canonical identity rule

The current capability IDs and names come from the explicit capability queue in
`docs/LUNA_ROADMAP.md`. Planning/review prose may suggest implementation order, but a conflicting
ID/title pair cannot silently redefine a canonical capability identity.

## Registry contract

Each record carries:

- stable capability ID and name;
- evidence-oriented status;
- hard and preferred capability prerequisites;
- source/foundation references;
- implementation/verifier/evidence references where implemented;
- metrics;
- authority boundary and rollback/disable path;
- source/evidence revision and evidence freshness.

`VERIFIED` requires current repository evidence. Documentation or model self-report alone cannot
produce verified status.

## Deterministic validation

The registry rejects:

- duplicate IDs or names;
- unknown dependencies;
- self-dependencies;
- the same prerequisite declared as both hard and preferred;
- dependency cycles;
- implemented status without implementation, verifier, and evidence references;
- verified status without current evidence.

## Blast-radius query

Blast radius is derived only from explicit dependency edges. It returns deterministic direct and
indirect dependents plus dependency paths. Preferred edges may be excluded for a hard-dependency-only
view.

An omitted or unresolved planning edge is not invented by C-002.

## Authority boundary

C-002 is metadata and impact analysis only.

```text
registry/query
-> observation
-> human/runtime/evaluation decision elsewhere
```

No automatic capability promotion, roadmap mutation, training, worker execution, self-optimization,
or external action is added by this RFC.
