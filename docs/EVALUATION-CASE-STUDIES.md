# Evaluating the evaluation: three software engineering case studies

**Yusuf Mohammed | Draft for review | October 25, 2026**

I built sw-dev-blueprint to pursue reliable software delivery at local-model
cost. Frontier models draft specifications and acceptance tests, local models
plan and write code, and software controls execution and checks acceptance.
Operating that workflow exposed a recurring question: does a failed attempt
reveal a model limitation, or a problem in the task, grader, or execution
environment?

These three cases show how I investigated that question. My role was to define
requirements, direct experiments and investigations, review their conclusions,
and direct changes to the workflow. AI agents helped analyze the evidence and
implement the code and tests. The linked records distinguish observations,
decisions, and verification results.

| Case | Finding | Result |
| --- | --- | --- |
| Diagnosis prompt comparison | Agreement with a historical label could preserve an incorrect diagnosis. | Rejected the denser prompt and expanded the permitted diagnosis categories. |
| Fault-seeding audit | A passing test suite missed deliberately introduced faults. | Detected 45 of 68 faults; used the 23 misses to guide targeted test improvements. |
| Impossible task specification | Required implementation files were absent from the permitted work inventory. | Added a preflight that rejected the historical defective specification and accepted the corrected one. |

## 1. A matching label concealed an incorrect diagnosis

*August 23, 2026*

**Question.** Would a more detailed diagnosis prompt improve the planning
model's ability to explain failed coding tasks?

I directed a comparison using three archived Testchat failures. Two contained
responses that violated the required output schema. The third contained a
well-formed but unsupported diagnosis. Both prompt variants used the same
model server and a 2,000-token output limit.

| Historical case | Existing prompt | Denser candidate |
| --- | --- | --- |
| Missing required revised brief | Produced a schema-valid response | Produced a schema-valid response |
| Revised brief exceeded its length limit | Produced a schema-valid response | Produced a schema-valid response |
| HTTP 422 failure with no reproduced implementation defect | Blamed the test | Blamed the task brief |

The third case exposed two problems. First, the replay tool reported
`MATCH` for the existing prompt because its answer agreed with the archived
verdict. That measured consistency with an earlier answer, not correctness.
Second, the model could choose only among defects in the brief, task
decomposition, or contract/test. None represented the transient or
environmental explanation supported by the supplied record: the unchanged
implementation passed all 15 focused tests, and the 422 could not be
reproduced.

**My contribution and decision.** I reviewed the comparison and directed the
follow-up around the missing diagnosis category. The denser prompt was not
adopted. The schema gained `transient_or_environmental`, with an explicit
evidence requirement and a halt for operator review. It was not an unrestricted
"unknown" category or permission to retry automatically.

**What this established.** More detailed instructions did not resolve the
missing category in these cases. A mechanically valid response and agreement
with a stored label were insufficient measures of diagnostic quality.

**Limits.** This was a targeted three-case replay, not a representative model
benchmark. The record does not establish a general accuracy improvement after
the schema change. A passing rerun alone also cannot prove that an earlier
failure was environmental.

**Evidence:** [experiment and adjudication](research/2026-08-23-em-diagnosis-ab.md),
[replay scoring logic](../scripts/em-bench.sh), and
[D-169: diagnosis-category and routing decision](DECISIONS.md#d-169--2026-08-23--transientenvironmental-diagnoses-halt-for-operator-review-the-shell-never-guesses-a-recovery).

## 2. Passing tests missed 23 planted faults

*August 25, 2026*

**Question.** Would the tests protecting the development workflow detect
plausible faults in its checks and supporting tools?

I directed a fault-seeding audit covering 34 checks and tools. The audit
introduced two selected code mutations per target, for 68 actual faults, and
tested them in isolation against a passing baseline at a pinned repository
revision.

**Result: 45 faults detected; 23 missed.**

The misses were grouped by the apparent weakness in the tests:

| Gap identified in the audit | Missed faults |
| --- | ---: |
| Tests did not exercise the changed branch | 11 |
| Test substitutes made the changed behavior unobservable | 2 |
| Tests exercised code but did not assert the affected output or exit status | 10 |

Examples included a model-identity check with its condition reversed, an
approval-hash check that accepted the wrong hash, and a metrics calculation
that counted successful calls as waste. These were concrete ways that an
apparently healthy suite could permit incorrect behavior.

**My contribution and decision.** I directed targeted test improvements and
follow-up mutation checks. The audit remained diagnostic: its purpose was to
identify missing evidence and improve the tests. A surviving mutation was not
treated as proof that the underlying safeguard should be removed.

The follow-up records report 10 of 10 faults detected in one group and 17 of
17 across another series of checks, including additional cases. Those are
separate, targeted results across different revisions; they should not be
presented as a single repeat of the original 68-fault audit.

**What this established.** Deliberately testing wrong behavior exposed gaps
that the passing baseline concealed. The useful outcome was the specific map
of missing assertions and ineffective fixtures, followed by evidence that
targeted improvements detected the selected faults.

**Limits.** The mutations were selected, not randomly sampled from real-world
defects. Their detection rate is not a general reliability estimate. Tests
improved against known mutations also need independent cases before making
claims about broader coverage.

**Evidence:** [audit report](research/2026-08-25-d161-gates-ext-mutation-report.md),
[mutation definitions](research/2026-08-25-d161-gates-ext-mutants.tsv),
[original results](research/2026-08-25-d161-gates-ext-results.tsv),
[first follow-up](research/2026-08-25-d161-group1-oracle-fixes-results.tsv), and
[additional follow-up checks](research/2026-08-25-d161-group2-oracle-fixes-results.tsv).
The raw output counts a header row as an authoring error; the audit report
explains why the correct denominator is 68 actual faults.

## 3. An impossible task looked like repeated model failure

*July 19, 2026*

**Problem.** A Testchat milestone required a new model-catalog endpoint, but
the frozen specification omitted its implementation files from the inventory
the planner was permitted to use. The plan validator required tasks to match
that inventory. A compliant plan therefore could not contain the work needed
to satisfy the requirement.

The workflow spent roughly 75 minutes in unsuccessful planning and escalation,
including changes of model, before the specification defect was identified.
The corrected specification added the missing files.

**My contribution and decision.** I directed implementation of a preflight
that checks whether new or changed contracts have the necessary implementation
paths available before a specification is frozen. The escalation procedure
also gained a specification-defect check after repeated plan rejection, so
provable task defects could be routed back for correction.

The recorded historical replay tested both sides:

| Input | Preflight result |
| --- | --- |
| Original version 51 specification against the pre-version-51 repository | Rejected in about two seconds, naming a missing implementation file |
| Corrected version 53 specification | Passed the preflight |

**What this established.** The original task violated its own planning
constraints. Changing the model could not repair that contradiction. Replaying
the actual defective and corrected specifications provided evidence that the
new check recognized this failure class.

**Limits.** The 75 minutes describe the original incident; the two seconds
describe a later preflight replay. They are not a controlled productivity
comparison. A passing preflight checks only the conditions it can establish
from contracts and files; it does not prove that every requirement is clear,
correct, or achievable.

**Evidence:** [Testchat incident record](https://github.com/developer-learner/testchat/blob/79befe12fa1a8374dc851f90c9dd8d24af1a8ea3/project-trail/2026-07-19-m28-impossible-spec.md),
[D-78: preflight and historical replay](DECISIONS.md#d-78--2026-07-19--freeze-time-satisfiability-preflight-newchanged-contracts-must-be-implementable-by-the-inventory), and
[D-79: specification-defect escalation](DECISIONS.md#d-79--2026-07-19--escalation-ladder-audits-the-puzzle-before-blaming-the-solver-spec-defect-rung-at-plan-budget-exhaustion).

---

These cases inform how I design evaluations: check what information the model
receives, verify that the task permits a correct solution, test the grader
against plausible wrong solutions, and keep the reported result tied to the
evidence. Results above describe the dated investigations; preparing this page
did not involve new model runs or a fresh benchmark.
