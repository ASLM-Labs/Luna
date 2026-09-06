# Luna

**YOUR AI ASSISTANT**

> A governed AI runtime for reliable execution, durable continuity, explicit verification, and controlled capability growth.

[![Quality](https://github.com/ASLM-Labs/Luna/actions/workflows/quality.yml/badge.svg)](https://github.com/ASLM-Labs/Luna/actions/workflows/quality.yml)
![Python](https://img.shields.io/badge/Python-3.12%20%7C%203.13-3776AB?logo=python&logoColor=white)
![Ruff](https://img.shields.io/badge/Ruff-checked-261230)
![mypy](https://img.shields.io/badge/mypy-strict-2A6DB2)

---

## Intelligence with boundaries

Luna is built around a simple principle:

> **Intelligence may propose. Evidence, policy, and runtime state decide what becomes authoritative.**

Luna separates reasoning from authority, planning from execution, observations from evidence, and evidence from verified completion.

The system is designed to remain understandable as it grows: one authoritative root identity, explicit execution boundaries, durable runtime state, deterministic verification, and capability expansion that does not silently grant itself more power.

```mermaid
flowchart LR
    USER["User"] --> LUNA["Luna"]
    LUNA --> UNDERSTAND["Understand"]
    UNDERSTAND --> PLAN["Plan"]
    PLAN --> ACT["Act"]
    ACT --> OBSERVE["Observe"]
    OBSERVE --> VERIFY["Verify"]
    VERIFY -->|Verified| COMPLETE["Complete"]
    VERIFY -->|Changed basis| PLAN
    VERIFY -->|Insufficient authority| BLOCK["Block"]
```

---

## What Luna is

Luna is not just a chat interface around a model. It is a **stateful AI execution system** that coordinates:

- task contracts and authoritative task state
- layered context composition
- planning and replanning
- model interaction and action resolution
- registered tools and safe workspace operations
- owned subprocess boundaries
- durable queues, checkpoints, and resume
- observations, evidence, and verification
- reviewed long-term memory
- desktop, Discord, voice, and CLI surfaces
- governed advanced-cognition research

The model participates in the system.

**It does not own the system.**

---

## Architecture

```mermaid
flowchart TB
    subgraph SURFACES["Product Surfaces"]
        DESKTOP["Desktop"]
        DISCORD["Discord"]
        VOICE["Voice"]
        CLI["CLI"]
    end

    subgraph CONTROL["Authoritative Luna Runtime"]
        IDENTITY["Identity & Task Contract"]
        CONTEXT["Context Composition"]
        PLANNER["Planning & Replanning"]
        POLICY["Policy Agent"]
        ACTION["Action Resolution"]
        RECOVERY["Recovery & Isolation"]
    end

    subgraph EXECUTION["Execution Boundaries"]
        TOOLS["Registered Tools"]
        WORKSPACE["Workspace"]
        PROCESS["Owned Process Trees"]
        PROVIDERS["Model / Provider Adapters"]
        QUEUE["Durable Queue & Scheduler"]
    end

    subgraph TRUST["Trust & Continuity"]
        OBS["Observations"]
        EVIDENCE["Evidence"]
        VERIFY["Verification"]
        JOURNAL["Runtime Journal"]
        CHECKPOINT["Checkpoint / Resume"]
        MEMORY["Verified Memory"]
    end

    SURFACES --> CONTROL
    CONTROL --> EXECUTION
    EXECUTION --> OBS
    OBS --> EVIDENCE
    EVIDENCE --> VERIFY
    VERIFY --> CONTROL
    CONTROL <--> JOURNAL
    CONTROL <--> CHECKPOINT
    CONTROL <--> MEMORY
```

The key distinction is that **execution does not automatically imply truth**, and **model output does not automatically imply authority**.

---

## The authoritative runtime loop

Luna maintains one authoritative task state and advances it through an explicit action-observation-verification cycle.

```mermaid
stateDiagram-v2
    [*] --> Contracted
    Contracted --> ContextReady
    ContextReady --> Planned
    Planned --> ActionSelected
    ActionSelected --> Dispatched
    Dispatched --> Observed
    Observed --> Verification
    Verification --> Completed: evidence sufficient
    Verification --> Planned: changed basis / replan
    Verification --> Suspended: durable suspension
    Verification --> Blocked: policy / integrity / authority
    Verification --> Rollback: verification failure
    Rollback --> Planned
    Suspended --> ContextReady: resume
    Completed --> [*]
    Blocked --> [*]
```

A tool call is therefore not the end of an operation. It is an observation-producing event inside a larger governed state machine.

---

## One Luna. One authority.

Luna is intentionally built around a **single authoritative voice**.

Models, memory, retrieval systems, tools, external evidence, and parallel workers may contribute information. None of them silently become equal authorities.

```mermaid
flowchart TD
    ROOT["Luna Root Authority"]
    MODEL["Model"] -->|proposal| ROOT
    MEMORY["Memory"] -->|data| ROOT
    RETRIEVAL["Retrieval"] -->|evidence candidates| ROOT
    WORKER["Worker"] -->|candidate output| ROOT
    TOOL["Tool"] -->|observation| ROOT
    EXTERNAL["External Evidence"] -->|evidence| ROOT
    ROOT --> DECISION["Authoritative Decision"]
```

### Capability is not authority

```mermaid
flowchart LR
    CAN["Can it do this?"] --> MAY["May it do this?"]
    MAY --> SCOPE["Is it in scope?"]
    SCOPE --> STATE["Is current state valid?"]
    STATE --> EXECUTE["Execute"]
```

An implementation may technically support an operation while policy, scope, current state, or risk still forbids it.

---

## Context is structured, not dumped

Luna composes model-visible context through canonical layers with different control and trust semantics.

```mermaid
flowchart TB
    ACTIVE["1 · ACTIVE<br/>Current control state"]
    TASK["2 · TASK<br/>Task contract & requirements"]
    CONTINUITY["3 · RUNTIME CONTINUITY<br/>Resume-safe working state"]
    WORKSPACE["4 · WORKSPACE<br/>Observed project data"]
    MEMORY["5 · VERIFIED MEMORY<br/>Reviewed long-term context"]
    ACTIVE --> TASK --> CONTINUITY --> WORKSPACE --> MEMORY
```

This design keeps several invariants explicit:

- active control state has priority
- passive data cannot escalate authority
- stale continuity can be rejected
- unverified memory does not become trusted context
- secrets can be removed before model exposure
- missing critical context remains visible instead of being invented

---

## Planning is not execution

A plan is an intention. An action must pass a separate resolution boundary before anything happens.

```mermaid
sequenceDiagram
    participant U as User
    participant L as Luna Runtime
    participant M as Model
    participant R as Action Resolver
    participant T as Tool
    participant V as Verifier

    U->>L: Task
    L->>M: Bounded context + task state
    M-->>L: Proposed action
    L->>R: Resolve proposal

    alt Authorized
        R-->>L: Prepared action
        L->>T: Execute one governed action
        T-->>L: Observation
        L->>V: Evidence + expected outcome
        V-->>L: Verification result
    else Denied
        R-->>L: Structured denial
    end
```

This prevents a model-generated tool call from becoming an implicit permission grant.

---

## Safe execution

```mermaid
flowchart TD
    REQUEST["Proposed Action"] --> REGISTERED{"Registered?"}
    REGISTERED -->|No| DENY["Deny"]
    REGISTERED -->|Yes| PERMISSION{"Authorized?"}
    PERMISSION -->|No| DENY
    PERMISSION -->|Yes| IMPACT{"Impact / Risk"}
    IMPACT -->|Read-only / low| SAFE["Safe execution boundary"]
    IMPACT -->|Write / higher risk| ISOLATE["Isolation / snapshot / worktree"]
    SAFE --> RUN["Execute"]
    ISOLATE --> RUN
    RUN --> OBSERVE["Capture observation"]
    OBSERVE --> VERIFY["Verify"]
    VERIFY -->|Pass| ACCEPT["Accept"]
    VERIFY -->|Failure| RECOVER["Recover / Rollback / Replan"]
```

Luna's runtime foundations include exact-argv process execution, bounded output, explicit environments, process-tree ownership, workspace protection, rollback/recovery, scope checks, and governed side-effect handling.

---

## Evidence before completion

> **Successful execution and verified completion are different events.**

```mermaid
flowchart LR
    OUTPUT["Tool / Model Output"] --> OBS["Observation"]
    OBS --> EVIDENCE["Evidence"]
    EVIDENCE --> CHECK["Verification"]
    CHECK -->|Strong + current + consistent| COMPLETE["Verified Complete"]
    CHECK -->|Weak| MORE["Gather more evidence"]
    CHECK -->|Changed state| REPLAN["Replan"]
    CHECK -->|Conflict| BLOCK["Block"]
    MORE --> EVIDENCE
```

This prevents false completion from tool output alone, stale evidence, contradictory evidence, or unverified model confidence.

---

## Durable by design

Luna treats interruption and restart as normal runtime conditions.

```mermaid
flowchart TD
    RUN["Running Task"] --> JOURNAL["Runtime Journal"]
    RUN --> CHECKPOINT["Checkpoint"]
    CHECKPOINT --> STOP["Process Stops"]
    STOP --> RESUME["Resume Validation"]
    RESUME --> COMPAT["Compatibility Check"]
    COMPAT -->|Compatible| CONTINUE["Continue"]
    COMPAT -->|Schema / contract drift| BLOCK["Fail Closed"]
    CONTINUE --> RUN
```

Continuity is protected through durable journals, checkpoint integrity, compatibility validation, replay fences, resumable state, and explicit suspend/cancel controls.

---

## Memory is reviewed knowledge

```mermaid
flowchart LR
    EXPERIENCE["Observed Experience"] --> CANDIDATE["Memory Candidate"]
    CANDIDATE --> REVIEW["Validation / Review"]
    REVIEW -->|Accepted| STORE["Verified Memory"]
    REVIEW -->|Rejected| DROP["Discard"]
    STORE --> RETRIEVE["Scoped Retrieval"]
    RETRIEVE --> CONTEXT["Data-only context"]
```

Long-term memory is intentionally separated from transient context. Provenance, verification state, confidence, scope, supersession, expiry, and forgetting remain explicit concerns.

---

## Recovery instead of blind retry

```mermaid
flowchart TD
    FAIL["Failure"] --> CLASSIFY{"Failure basis"}
    CLASSIFY -->|Permission / scope| BLOCK["Block"]
    CLASSIFY -->|Integrity| STOP["Stop"]
    CLASSIFY -->|Stale state| REINSPECT["Reinspect"]
    CLASSIFY -->|Verification| ROLLBACK["Rollback"]
    CLASSIFY -->|Transient + changed basis| RETRY["Bounded retry"]
    REINSPECT --> REPLAN["Replan"]
    ROLLBACK --> REPLAN
    RETRY --> OBSERVE["Observe new result"]
```

A failed action does not become more valid merely because it is attempted again. Retry state is bounded, evidence-aware, cancellable, and durable.

---

## C-011: parallel cognition without parallel authority

C-011 is Luna's governed parallel-cognition track. It explores bounded parallel cognition while preserving the single authoritative root identity.

```mermaid
flowchart TB
    ROOT["Luna<br/>Authoritative Root"] --> ORCH["Governed Parallel Cognition"]
    ORCH --> W1["Worker A"]
    ORCH --> W2["Worker B"]
    ORCH --> W3["Worker C"]
    W1 --> R1["Candidate"]
    W2 --> R2["Candidate"]
    W3 --> R3["Candidate"]
    R1 --> RECON["Reconciliation"]
    R2 --> RECON
    R3 --> RECON
    RECON -->|data / evidence only| ROOT
```

Workers do not receive root identity, completion authority, memory-commit authority, promotion authority, or unrestricted tool authority by default.

### Native isolation

Existing Common / Ultra native paths remain isolated from the C-011 ABI-v2 experimentation surface.

```mermaid
flowchart LR
    subgraph EXISTING["Existing Neural Path"]
        COMMON["Common / Ultra"] --> ABI1["Native ABI v1"] --> BRIDGE1["Native Bridge"]
    end

    subgraph C011["C-011 Isolated Path"]
        PARALLEL["Parallel Cognition"] --> ABI2["C-011 ABI v2"] --> BRIDGE2["Isolated Native Bridge"]
    end

    ABI1 -.-|No implicit replacement| ABI2
```

The separation is deliberate: advanced capability work should not silently replace previously verified execution paths.

---

## Product surfaces

The same governed runtime can sit behind multiple user-facing interfaces without fragmenting authority.

```mermaid
flowchart TB
    USER["User"]
    USER --> DESKTOP["Desktop"]
    USER --> DISCORD["Discord"]
    USER --> VOICE["Voice"]
    USER --> CLI["CLI"]
    DESKTOP --> GATE["Ingress / Identity / Policy"]
    DISCORD --> GATE
    VOICE --> GATE
    CLI --> GATE
    GATE --> CORE["Luna Runtime"]
```

Product surfaces submit requests. They do not independently redefine identity, policy, evidence, or completion semantics.

---

## Research and learning governance

Luna contains foundations for controlled research, evaluation, learning-integrity, and candidate-improvement workflows.

```mermaid
flowchart LR
    TRACE["Structured Traces"] --> DATA["Governed Dataset"]
    DATA --> CANDIDATE["Candidate Improvement"]
    CANDIDATE --> EVAL["Independent Evaluation"]
    EVAL --> INTEGRITY["Learning Integrity"]
    INTEGRITY --> GATE["Improvement Gate"]
    GATE -->|Evidence sufficient| REVIEW["Controlled Review"]
    GATE -->|Regression / contamination| REJECT["Reject"]
```

The architecture separates runtime execution, dataset preparation, evaluation, candidate training evidence, and promotion decisions. A candidate improvement cannot promote itself.

---

## System map

At a higher level, Luna can be viewed as four interacting systems.

```mermaid
flowchart TB
    subgraph THINK["Cognition"]
        CTX["Context"]
        PLAN["Planning"]
        MODEL["Model Policy"]
        PC["Parallel Cognition"]
    end

    subgraph ACT["Action"]
        SELECT["Action Selection"]
        TOOLS["Tools"]
        PROCESS["Processes"]
        WORKSPACE["Workspace"]
    end

    subgraph TRUST["Trust"]
        OBS["Observations"]
        EVIDENCE["Evidence"]
        VERIFY["Verification"]
        AUDIT["Audit"]
    end

    subgraph TIME["Continuity"]
        JOURNAL["Journal"]
        CHECKPOINT["Checkpoint"]
        QUEUE["Queue"]
        MEMORY["Verified Memory"]
    end

    THINK --> ACT
    ACT --> TRUST
    TRUST --> THINK
    THINK <--> TIME
    ACT <--> TIME
    TRUST <--> TIME
```

---

## Repository map

```text
Luna/
├─ src/luna/
│  ├─ actions/
│  ├─ context/
│  ├─ continuity/
│  ├─ modeling/
│  ├─ neural/
│  ├─ parallel_cognition/
│  ├─ planning/
│  ├─ recovery/
│  ├─ runtime/
│  ├─ shell/
│  ├─ tools/
│  ├─ verification/
│  └─ workspace/
├─ native/neural_bridge/
├─ scripts/
├─ tests/
├─ docs/
└─ .github/workflows/
```

Implementation, native boundaries, tests, verification scripts, and technical evidence are kept separate intentionally.

---

## Development

### Install

```bash
python -m pip install --upgrade pip setuptools
python -m pip install -e ".[dev]"
```

### Runtime checks

```bash
python -m luna --version
python -m luna status
```

### Test and static analysis

```bash
python -m pytest -q -p no:cacheprovider --basetemp=.pytest_tmp
python -m ruff check .
python -m mypy src
```

### Canonical Windows repository gate

```bat
scripts\check.bat
```

---

## Verification philosophy

Luna uses executable verification extensively.

Tests ask:

> Does this implementation behave correctly?

Capability and phase verifiers additionally ask:

> Does the repository still satisfy the architectural contract this capability was built under?

```mermaid
flowchart LR
    CODE["Implementation"] --> TESTS["Tests"]
    CODE --> STATIC["Static Analysis"]
    CODE --> CONTRACTS["Capability Verifiers"]
    TESTS --> GATE["Repository Gate"]
    STATIC --> GATE
    CONTRACTS --> GATE
```

---

## Engineering principles

**Evidence over confidence.** A confident model output is not stronger than missing evidence.

**Explicit authority.** No model, tool, worker, memory item, or external source grants itself permission.

**Observe before infer.** Current observable state has priority over assumptions.

**Recover with changed basis.** Retry is not a substitute for new information.

**Durable state.** Important runtime transitions should survive process restarts.

**Isolation before impact.** Higher-risk operations require stronger execution boundaries.

**One authoritative identity.** Parallel work may increase cognition capacity without creating competing system identities.

**No false claims.** Unexecuted training, unverified results, unavailable capabilities, and incomplete evidence remain visibly incomplete.

---

## Current maturity

Luna is an actively developed AI runtime and research platform. The repository contains substantial foundations across runtime execution, continuity, memory, verification, product gateways, neural execution, and capability governance.

Some advanced paths remain deliberately constrained, experimental, default-off, or subject to further rollout work. That distinction is intentional.

Luna prefers **implemented over imagined, verified over assumed, and explicitly incomplete over falsely complete**.

---

## Technical history

The previous root README contained the detailed phase-by-phase implementation history, boundaries, smoke commands, and capability notes. It has been preserved rather than deleted:

**[Read the full phase and capability history →](docs/legacy/README_PHASE_HISTORY.md)**

---

## Luna

Luna is built around a question larger than *Can an AI perform this task?*

The more important questions are:

- Should it act?
- What does it actually know?
- What changed?
- What evidence supports the result?
- Can the result survive verification?
- Can the system resume safely tomorrow?

That is the foundation Luna is being built on.

**YOUR AI ASSISTANT**
