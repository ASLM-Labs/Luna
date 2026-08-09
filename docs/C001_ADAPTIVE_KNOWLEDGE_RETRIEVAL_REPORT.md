# C-001 Adaptive Knowledge Retrieval Report

## Result

C-001 implements a deterministic, non-executing knowledge-source router on top of existing Luna
context, verified-memory, research/evidence, and capability-lineage foundations.

Status: `IMPLEMENTED_UNVERIFIED`

Final `VERIFIED` status still requires merge containment and CI evidence.

## Implemented behavior

The router distinguishes:

- internal model knowledge;
- already-observed working context;
- verified memory;
- project/document RAG when available;
- Phase 14 Research Gateway/web when available;
- structured APIs when suitable and available.

It routes current/fast-changing or high-uncertainty facts away from stale internal knowledge, prefers
structured APIs for suitable current structured data, and requires research/API routes to retain
freshness and citation/provenance requirements.

Contradictory evidence causes `STOP_REINSPECT` before any source selection.

## Privacy and memory safety

Missing user-specific information is not silently sent to public research. A user-specific request with
no adequate working context, verified memory, or suitable authorized structured source stops rather
than leaking the question to a public-research fallback.

No retrieval result becomes long-term memory automatically. Retrieval output remains evidence/context;
any future persistence must pass the existing reviewed memory-candidate flow.

## Integration boundary

C-001 chooses a source family only. It does not directly call the network, execute a structured API,
create a project RAG backend, or grant runtime authority.

Existing boundaries remain authoritative:

- Phase 9 for verified-memory storage/retrieval;
- Phase 12B for observed layered context;
- Phase 14 for network/domain/budget/provenance/injection enforcement;
- C-002 for capability identity and dependency lineage.

## Deterministic fixtures

The verifier covers:

```text
stable + low uncertainty + known
-> INTERNAL

observed sufficient context
-> WORKING_CONTEXT

user-specific + verified memory available
-> VERIFIED_MEMORY

document-specific + project RAG available
-> PROJECT_RAG

current structured data + API available
-> STRUCTURED_API

high uncertainty + research available
-> RESEARCH_GATEWAY

contradictory evidence
-> STOP_REINSPECT

current data + no fresh governed source
-> STOP_REINSPECT
```

The same profile produces the same route.

## Known limitations

- Source availability is caller-supplied and must come from governed runtime state.
- C-001 does not measure live source quality by itself.
- Project/document RAG and structured APIs are not fabricated when unavailable.
- Actual research execution remains Phase 14-owned.
- Evaluation metrics are declared but require later measured task/eval corpora for empirical values.

## Authority

Runtime authority: none.

External-action authority: none.

Automatic memory commit: none.

Promotion authority: none.
