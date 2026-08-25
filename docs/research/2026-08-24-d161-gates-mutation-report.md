# D-161 mutation-pass results

- source: `/Users/arc.elixir/dev/sw-dev-blueprint@0518bad1af123791f680e3ee27581e7e97ddfec8` (isolated exact-HEAD clone)
- baseline: green
- suite: `python3 -m pytest scripts/selftest/selftest_gates.py -q`
- totals: 6 mutants; 6 killed; 0 survived; 0 authoring errors
- enforcement: report-only; survivors are evidence for oracle improvement, never a build gate

| verdict | file | mutation | reason |
|---|---|---|---|
| KILLED | `scripts/check-ac-postconditions.py` | `if verbs and not POST_CONDITION.search(ac_text):` → `if verbs and POST_CONDITION.search(ac_text):` | detection inverted: flags ACs that have a post-condition, lets state-verb ACs without one pass |
| KILLED | `scripts/check-ac-postconditions.py` | `return 1 if all_errors else 0` → `return 0 if all_errors else 1` | exit code inverted: violations report success |
| KILLED | `scripts/check-ac-postconditions.py` | `spawn\|terminate\|kill\|unload\|evict\|delete\|release\|clear\|cancel` → `spawn\|kill\|unload\|evict\|delete\|release\|clear\|cancel` | verb list loses 'terminate', the verb the 2a fixture AC uses |
| KILLED | `scripts/flake-ledger.py` | `if getattr(args, "spec_version", 1) < 1:` → `if getattr(args, "spec_version", 1) < 0:` | boundary moves from 1 to 0: spec-version 0 accepted |
| KILLED | `scripts/check-test-direction.py` | `hits = sorted(set(AC_ID.findall(py.read_text())) & new)` → `hits = sorted(set(AC_ID.findall(py.read_text())) \| new)` | intersection becomes union: carried tests citing approved ACs get flagged |
| KILLED | `scripts/check-test-direction.py` | `if hits:` → `if not hits:` | finding condition inverted: citing a new AC passes, clean files fail |
