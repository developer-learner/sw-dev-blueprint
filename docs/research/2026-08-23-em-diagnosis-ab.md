# EM diagnosis brief A/B (2026-08-23)

## Question

Does a denser diagnosis-only rubric improve the mid-tier EM's schema validity
and substantive verdict accuracy over the current `.opencode/prompts/em.md`?

This was a standalone `scripts/em-bench.sh` replay, not a milestone, refreeze,
or orchestrate run. Both variants used the same non-thinking
`Qwen3.8-27B-MLX-8bit` server and a 2000-token output cap. The candidate brief
is preserved at `docs/research/2026-08-23-em-diagnosis-dense-brief.md`; it was
not installed as the production prompt.

## Corpus and results

Three archived testchat diagnosis calls were selected: two schema-invalid
replies and one schema-valid production misdiagnosis.

| Archive entry | Historical outcome | Current brief | Dense candidate |
|---|---|---|---|
| `2026-08-09_001955_diagnosis` | `brief_wrong` omitted `revised_brief` | FIXED: valid `brief_wrong` | FIXED: valid `brief_wrong` |
| `2026-08-16_035958_diagnosis` | `revised_brief` exceeded 2500 chars | FIXED: valid `brief_wrong` | FIXED: valid `brief_wrong` |
| `2026-08-16_033518_diagnosis` | transient 422 forced into `contract_or_test_wrong` | repeated `contract_or_test_wrong` | changed to `brief_wrong` |

The bench's mechanical score calls the third dense result a MISMATCH and the
current result a MATCH, because it compares with the archived verdict. Manual
adjudication is required here: the active v111 evidence says the same committed
implementation passed all 15 focused tests and that the 422 could not be
reproduced. It explicitly records no brief, contract, test, or implementation
defect.

## Adjudication

Neither variant diagnosed the third case correctly:

- The current brief blamed the test's HTTP-200 assertion, despite the supplied
  evidence saying the test passes against the unchanged implementation.
- The dense candidate stopped blaming the test but blamed the brief instead,
  inventing a missing `model=request.model` instruction that cannot explain a
  422 raised before streaming. AC-172 already requires the model id to pass
  through unchanged.

The forced error is structural. The diagnosis schema permits only
`brief_wrong`, `decomposition_wrong`, or `contract_or_test_wrong`; it cannot
represent a transient/environmental failure. More context density merely moves
the false blame between the three allowed defect buckets.

## Verdict

Do **not** ship the dense candidate. D-71's bounded retry plus the current brief
already repaired both historical schema failures in this sample. The remaining
quality defect is verdict taxonomy, not missing diagnosis context.

Follow-up: decide whether to add a `transient_or_environmental` verdict and its
shell-owned routing semantics. That is a behavior/contract change across the
schema, validator, prompt, orchestrator, and escalation evidence, so it remains
a separate decision rather than being smuggled in as prompt wording.
