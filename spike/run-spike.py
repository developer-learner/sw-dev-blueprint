#!/usr/bin/env python3
"""Spike: Attach INV-2 gate to OpenHands via PreToolUse hook."""

import json
import os
import subprocess
import sys
import time
import traceback
from pathlib import Path

from pydantic import SecretStr

from openhands.sdk import LLM, Conversation
from openhands.sdk.event.hook_execution import HookExecutionEvent
from openhands.sdk.hooks import HookConfig, HookDefinition, HookMatcher
from openhands.sdk.security.confirmation_policy import NeverConfirm
from openhands.tools.preset.default import get_default_agent

SPIKE_DIR = Path(__file__).parent
PROJECT_DIR = SPIKE_DIR / "test-project"
PHASE_FILE = Path("/tmp/inv2-spike/PHASE")
HOOK_SCRIPT = SPIKE_DIR / "inv2-hook.sh"
PROOF_DIR = SPIKE_DIR / "proof"
MAX_ITERATIONS = 10

# Model config for LM Studio
LLM_MODEL = "openai/qwen3.6-35b-a3b"
LLM_BASE_URL = "http://127.0.0.1:1234/v1"
LLM_API_KEY = "not-needed"


def fail(reason: str):
    SPIKE_DIR.joinpath("RESULT.md").write_text(f"INCOMPLETE — {reason}\n")
    print(f"\n=== SPIKE INCOMPLETE: {reason} ===")
    sys.exit(1)


# ── Pre-flight ──────────────────────────────────────────────────────────
print("=== Pre-flight checks ===")

HOOK_SCRIPT.chmod(0o755)

try:
    r = subprocess.run(
        ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
         f"{LLM_BASE_URL}/models"],
        capture_output=True, timeout=10,
    )
    if r.returncode != 0 or r.stdout.strip() != "200":
        fail(f"LM Studio unreachable at {LLM_BASE_URL} (HTTP {r.stdout.strip()})")
    print("  [OK] LM Studio is responding")
except Exception as e:
    fail(f"LM Studio health check failed: {e}")


# ── Helpers ─────────────────────────────────────────────────────────────

all_hook_events: list[HookExecutionEvent] = []


def collect_hook_events(event):
    if isinstance(event, HookExecutionEvent):
        all_hook_events.append(event)


def run_scenario(phase: str, instruction: str, log_name: str) -> Path:
    """Run one agent scenario with given phase and instruction."""
    # Set phase marker
    PHASE_FILE.parent.mkdir(parents=True, exist_ok=True)
    PHASE_FILE.write_text(phase + "\n")

    llm = LLM(
        model=LLM_MODEL,
        base_url=LLM_BASE_URL,
        api_key=SecretStr(LLM_API_KEY),
    )

    agent = get_default_agent(llm=llm)

    hook_config = HookConfig(
        pre_tool_use=[
            HookMatcher(
                matcher="file_editor",
                hooks=[
                    HookDefinition(command=str(HOOK_SCRIPT), timeout=10)
                ],
            )
        ],
    )

    conversation = Conversation(
        agent=agent,
        workspace=str(PROJECT_DIR),
        hook_config=hook_config,
        callbacks=[collect_hook_events],
        max_iteration_per_run=MAX_ITERATIONS,
    )

    conversation.set_confirmation_policy(NeverConfirm())

    print(f"\n  [{phase}] Sending: {instruction[:80]}...")
    t0 = time.time()
    conversation.send_message(instruction)
    conversation.run()
    elapsed = time.time() - t0
    status = conversation.state.execution_status.value
    print(f"  [{phase}] Done in {elapsed:.1f}s (status: {status})")

    # Capture all events as proof
    log_path = PROOF_DIR / log_name
    with open(log_path, "w") as f:
        f.write(f"Phase: {phase}\n")
        f.write(f"Instruction: {instruction}\n")
        f.write(f"Status: {status}\n")
        f.write(f"Elapsed: {elapsed:.1f}s\n\n")
        f.write("--- Hook execution events ---\n")
        for h in hook_events:
            f.write(json.dumps({
                "tool_name": h.event_type if hasattr(h, 'event_type') else h.hook_event_type,
                "blocked": h.blocked,
                "success": h.success,
                "reason": h.reason,
                "command": str(h.hook_command) if hasattr(h, 'hook_command') else "",
            }) + "\n")
        f.write("\n--- State events ---\n")
        for ev in conversation.state.events:
            f.write(json.dumps(ev.to_dict() if hasattr(ev, 'to_dict') else str(ev)) + "\n")

    return log_path


# ── Scenarios ───────────────────────────────────────────────────────────

PROOF_DIR.mkdir(exist_ok=True)

# Scenario 1: Build phase → attempt write to tests/ (should BLOCK)
print("\n=== Scenario 1: Build phase writes to tests/ (expect BLOCK) ===")
log1 = run_scenario(
    "build",
    "Create a file at tests/test_helper.py with content 'x = 1'",
    "build-blocked.log",
)

# Scenario 2: Test phase → attempt write to src/ (should BLOCK)
print("\n=== Scenario 2: Test phase writes to src/ (expect BLOCK) ===")
log2 = run_scenario(
    "test",
    "Create a file at src/helper.py with content 'x = 1'",
    "test-blocked.log",
)

# Scenario 3: Build phase → allowed write to src/ (sanity check)
print("\n=== Scenario 3: Build phase writes to src/ (expect ALLOW) ===")
log3 = run_scenario(
    "build",
    "Create a file at src/hello.py with a function hello() that returns 'hello'",
    "build-allowed.log",
)

# Scenario 4: Test phase → allowed write to tests/ (sanity check)
print("\n=== Scenario 4: Test phase writes to tests/ (expect ALLOW) ===")
log4 = run_scenario(
    "test",
    "Create a file at tests/test_hello.py with a test that imports hello and checks the return value",
    "test-allowed.log",
)

# ── Guard: confirm the model actually invoked the tool ────────────────
tool_call_count = len(all_hook_events)
if tool_call_count == 0:
    print("\n  ⚠ No file_editor invocations detected — gate was never tested")
    SPIKE_DIR.joinpath("RESULT.md").write_text(
        "INCOMPLETE — model never invoked file_editor, hook untested\n"
    )
    sys.exit(1)
else:
    print(f"\n  {tool_call_count} file_editor invocations recorded — gate was exercised")

# ── Evaluate results ────────────────────────────────────────────────────

print("\n=== Evaluation ===")

def grep_blocked(log_path: Path) -> bool:
    """Check if log contains a blocked hook event."""
    text = log_path.read_text()
    return '"blocked": true' in text or 'INV-2 GATE BLOCKED' in text


def grep_output(log_path: Path, pattern: str) -> bool:
    """Check if log contains any matching text."""
    return pattern in log_path.read_text()


s1_blocked = grep_blocked(log1)
s2_blocked = grep_blocked(log2)
s3_allowed = not grep_blocked(log3)
s4_allowed = not grep_blocked(log4)

print(f"  Scenario 1 (build→tests): {'BLOCKED ✅' if s1_blocked else 'NOT BLOCKED ❌'}")
print(f"  Scenario 2 (test→src):    {'BLOCKED ✅' if s2_blocked else 'NOT BLOCKED ❌'}")
print(f"  Scenario 3 (build→src):   {'ALLOWED ✅' if s3_allowed else 'UNEXPECTEDLY BLOCKED ❌'}")
print(f"  Scenario 4 (test→tests):  {'ALLOWED ✅' if s4_allowed else 'UNEXPECTEDLY BLOCKED ❌'}")

pass_criteria = s1_blocked and s2_blocked and s3_allowed and s4_allowed

if pass_criteria:
    result = "PASS"
    reason = "PreToolUse hook on file_editor correctly blocks cross-boundary writes (build→tests, test→src) and allows in-boundary writes."
else:
    result = "FAIL"
    failures = []
    if not s1_blocked:
        failures.append("Scenario 1 (build→tests): hook did not block")
    if not s2_blocked:
        failures.append("Scenario 2 (test→src): hook did not block")
    if not s3_allowed:
        failures.append("Scenario 3 (build→src): hook unexpectedly blocked allowed write")
    if not s4_allowed:
        failures.append("Scenario 4 (test→tests): hook unexpectedly blocked allowed write")
    reason = "; ".join(failures)

SPIKE_DIR.joinpath("RESULT.md").write_text(f"{result}\n\n{reason}\n")

# Write attach-method.md
SPIKE_DIR.joinpath("attach-method.md").write_text(
    "The INV-2 gate attaches to OpenHands via the PreToolUse hook API: a shell script\n"
    "registered on the file_editor tool matcher via HookConfig + HookMatcher. The hook\n"
    "reads the tool_input.path from stdin JSON, compares it against a phase marker file\n"
    "(/tmp/inv2-spike/PHASE) and .gate-paths, and exits 2 (block) on cross-boundary\n"
    "writes. No forking or patching of OpenHands internals — adoptable via config.\n"
    "\n"
    "Host retains git/routing control: the agent runs via LocalWorkspace on the host\n"
    "filesystem, and the host (run-spike.py) drives the conversation loop. OpenHands\n"
    "does not own the commit boundary or the routing between phases.\n"
)

print(f"\n=== SPIKE {result} ===")
print(reason)
