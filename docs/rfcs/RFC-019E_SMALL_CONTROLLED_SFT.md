# RFC-019E — Small Controlled SFT Governance

Status: IMPLEMENTED_UNVERIFIED
Phase: 19E

## Purpose

Phase 19E introduces the governed boundary between a normalized Luna training corpus and an external
small supervised fine-tuning run. It validates that the corpus is eligible for the first controlled
SFT, freezes a trainer-neutral candidate specification, and defines the evidence required before a
trained artifact may be recorded as an unpromoted candidate.

The repository does not contain a GPU trainer backend and this phase must not fabricate model weights.
A real training run remains an operator-controlled external execution. Phase 19E records only a
candidate whose training receipt proves that the run actually happened and that its artifact is bound
to the frozen corpus and configuration.

## Normalized corpus contract

The first controlled SFT accepts normalized JSONL rows with explicit Luna training metadata. Every
accepted row must provide:

- a unique record identity;
- source trajectory identity and canonical task family;
- the assistant step and total step count;
- context messages and one assistant target message;
- a loss mask that selects only the target assistant message;
- `split=train`;
- `train_role=policy`;
- `d1_decision=train_candidate`;
- `tool_schema=luna-canonical-tools-v0.1`;
- `normalization=privacy-and-context-v0.1`;
- positive trajectory, step, and loss weights;
- source derivation metadata.

Validation/held-out rows are rejected by the Phase 19E importer. Held-out data remains evaluation-only.

## No raw hidden chain-of-thought

The corpus audit rejects explicit raw hidden chain-of-thought fields. Phase 19E trains on observable
assistant targets, tool requests, tool observations, visible replans, verification, and final outputs.
It does not require or ingest hidden token-by-token reasoning.

## Target-only loss

Cumulative trajectories can repeat earlier assistant content many times. Therefore only the message at
`target_message_index` may receive loss:

`system=0, user=0, previous assistant=0, tool output=0, target assistant=1`.

This prevents repeated historical assistant messages from receiving unintended training weight.

## Conservative first-SFT mixture

The default policy treats the first controlled SFT as an implementation-policy curriculum:

- implementation records are the primary allowed subset;
- model-judge records may not exceed 20 percent of the audited corpus;
- harness/ops records may not exceed 5 percent;
- seed-authoring is excluded;
- security records are excluded until a dedicated governed corpus exists.

These values are initial safety/governance bounds, not claims of optimal training ratios.

## Frozen candidate specification

A candidate may be prepared only from a passing corpus audit. The frozen specification binds:

- candidate identity;
- base-model identity and revision;
- trainer identity and revision;
- corpus SHA-256 and record count;
- Phase 19E policy SHA-256;
- random seed;
- epoch count;
- learning rate;
- maximum sequence length;
- target-only loss;
- explicit non-use of held-out data.

Changing one of these values changes the candidate specification SHA-256.

## External training receipt

Phase 19E does not interpret a training command as success merely because it was requested. To record a
trained candidate, an external receipt must prove:

- `training_executed=true`;
- exit code zero;
- exact training-spec SHA-256;
- exact corpus SHA-256;
- exact base-model revision;
- exact trainer revision;
- trained artifact SHA-256 and byte count;
- training-log SHA-256;
- independent evidence references;
- held-out data was not used during training;
- no runtime authority was granted.

A failed, unexecuted, mismatched, or held-out-contaminated receipt is rejected.

## Promotion boundary

A successfully recorded Phase 19E artifact has state
`TRAINED_CANDIDATE_UNPROMOTED`.

Phase 19E never grants release-promotion authority. Candidate weights cannot replace the current Luna
runtime merely because training completed. Phase 19F remains responsible for fixed-baseline,
held-out/OOD, regression, safety, calibration, and multi-metric improvement comparison.

## Relationship to earlier Phase 19 work

- Phase 19A provides trace governance, leak-free splitting, target transformation, and cognitive
  dimensions.
- Phase 19B freezes held-out/OOD evaluation and evaluator identity.
- Phase 19C checks learning integrity and self-confirmation risks.
- Phase 19D separates counterfactual hypotheses from controlled replay evidence.
- Phase 19E binds an eligible corpus to a controlled SFT candidate without granting promotion.

## Not claimed

This implementation package does not claim:

- that the user's full trace archive has been imported into the repository;
- that a GPU/QLoRA/SFT job was executed by this package;
- that trained weights are bundled in the repository;
- that candidate quality improved;
- that Phase 19F evaluation has run;
- that a trained candidate is promoted.
