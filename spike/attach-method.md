The INV-2 gate attaches to OpenHands via the PreToolUse hook API: a shell script
registered on the file_editor tool matcher via HookConfig + HookMatcher. The hook
reads the tool_input.path from stdin JSON, compares it against a phase marker file
(/tmp/inv2-spike/PHASE) and .gate-paths, and exits 2 (block) on cross-boundary
writes. No forking or patching of OpenHands internals — adoptable via config.

Host retains git/routing control: the agent runs via LocalWorkspace on the host
filesystem, and the host (run-spike.py) drives the conversation loop. OpenHands
does not own the commit boundary or the routing between phases.
