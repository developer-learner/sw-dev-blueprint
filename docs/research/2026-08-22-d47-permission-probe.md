# D-47 live probe — OpenCode bash permission matching (2026-08-22)

**Question (Rule 6 assumption flagged by the D-47 review):** does OpenCode
match `permission.bash` globs against the *raw command string* or against
*parsed sub-commands*? If raw-string, an allow rule like
`scripts/bootstrap.sh*` would let `scripts/bootstrap.sh && <anything>`
through as allowed.

**Method:** headless probes under `opencode run` v1.18.19, isolated scratch
project with a minimal `opencode.json`, model served through vortex's
gateway (`qwen3.8-27b-8bit` via `127.0.0.1:9000/v1`). Each instruction asked
for exactly one command; markers were plain files in the project dir
(out-of-project paths trip the separate `external_directory` guard and would
confound results). Auto-mode was NOT used — unmatched/ask rules auto-reject
in run mode, which is the observable.

## Results

| # | Config (bash rules, in order) | Command issued | Outcome |
|---|---|---|---|
| 1 | none relevant (control, before any bash rules) | `echo PROBE-ALLOWED baseline` | executed — defaults are permissive |
| 2 | `{"echo PROBE-ALLOWED*": "allow"}` only | `touch ./marker-control` | **executed unprompted** — unmatched commands fall through to default-allow |
| 3 | `{"touch ./marker-deny*": "deny", "*": "allow"}` | `touch ./marker-deny-test` | executed — **last matching rule wins**; a trailing catch-all allow overrides an earlier deny |
| 4 | `{"*": "ask", "echo PROBE-ALLOWED*": "allow"}` | `echo PROBE-ALLOWED baseline2` | executed — correct-order allow works |
| 5 | same as 4 | `echo PROBE-ALLOWED && touch ./marker-raw` | **rejected**: `permission requested: bash (echo PROBE-ALLOWED, touch ./marker-raw); auto-rejecting` — compound parsed into sub-commands; no raw-string pass-through; marker absent |
| 6 | `{"*": "ask", "scripts/bootstrap.sh*": "allow"}` | `scripts/bootstrap.sh --flag` | executed — blueprint's real pattern shape allows its intended target |
| 7 | `"bash": {"*": "deny"}` (+ edit deny-all) | any bash | bash tool hidden from the model entirely ("I don't have a bash/shell tool") — full-deny manifests as tool removal |

## Findings

1. **D-47's raw-string fear is retired behaviorally**: OpenCode parses
   compound commands and evaluates them as a set — `A && B` is not masked by
   an allow rule written for `A`. Docs state bash matches "parsed commands";
   probe 5 confirms it in behavior on v1.18.19.
2. **The larger hazard is the default, not the matcher**: unmatched commands
   are ALLOWED unless a catch-all rule says otherwise. The blueprint's
   `opencode.json` has no bash catch-all, so its allow list grants nothing it
   promises — everything else is already permitted. A conductor could run
   arbitrary bash (including writing protected files, bypassing
   `permission.edit`) without a single prompt.
3. **Rule order matters**: last match wins. Any deny must come AFTER the
   catch-all, or it is dead text.
4. Full-tool denial (`"*": "deny"`) removes the tool rather than failing
   per-call — relevant when composing least-privilege agent configs.
5. `external_directory` is an independent guard (default ask) that caught
   out-of-project writes even while bash was permissive — layered defense
   observed working.

## Consequence for the blueprint config

The honest-layer statement in D-47/D-24/D-39 ("soft enforcement, friction +
visibility") understates it: today's project config provides ~zero bash
friction because of the permissive default. If the CEO wants the allowlist to
mean anything, the bash block needs a leading `"*": "ask"` (then existing
specific allows after it). Recorded here as evidence; changing the shipped
config is an integration decision outside A3's boundary.
