# D-161 mutation-pass results

- source: `/Users/arc.elixir/dev/vortex@f7257c7aadf87ed20a90675167f7d2749fd62e62` (isolated exact-HEAD clone)
- baseline: green
- suite: `python3 -m pytest tests -q`
- totals: 6 mutants; 4 killed; 2 survived; 0 authoring errors
- enforcement: report-only; survivors are evidence for oracle improvement, never a build gate

| verdict | file | mutation | reason |
|---|---|---|---|
| KILLED | `src/vortex/catalog.py` | `exclusive: bool = True` → `exclusive: bool = False` | Default exclusivity silently inverted |
| KILLED | `src/vortex/catalog.py` | `if e.public_id == public_id:` → `if e.public_id != public_id:` | Catalog lookup returns the wrong model |
| SURVIVED | `src/vortex/manager.py` | `* 0.8 - used` → `* 1.0 - used` | Memory headroom policy weakened from 80 to 100 percent |
| KILLED | `src/vortex/app.py` | `!= "ready":` → `== "ready":` | Chat accepts unloaded models and rejects ready ones |
| SURVIVED | `src/vortex/operations.py` | `"model": op.public_id` → `"model": op.id` | Operation snapshot reports its operation ID as the model |
| KILLED | `src/vortex/ui.py` | `op.state === "ready"` → `op.state === "done"` | Operation poll waits for a terminal state the backend never emits |
