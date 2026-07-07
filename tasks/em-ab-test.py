#!/usr/bin/env python3
"""A/B test: qwen3.5-122b-a10b vs qwen3.6-27b on an EM-style structured plan task.

Sends the same prompt to both models via LM Studio and scores the outputs
against the plan schema constraints that the real EM is failing on.

Prerequisites:
  - Both models must be loaded in LM Studio before running
  - LM Studio at http://localhost:1234

Usage:
  python3 em-ab-test.py
"""
import json
import re
import time
import httpx

ENDPOINT = "http://localhost:1234/v1/chat/completions"

MODELS = [
    "qwen3.5-122b-a10b",
    "qwen3.6-27b",
]

# Simplified but realistic EM prompt — the exact failure mode
PROMPT = """\
You are the Engineering Manager (EM). Given the frozen spec below, produce a \
valid tasks/plan.json. Reply with ONLY the JSON object, no markdown fences, \
no explanation, no thinking, no commentary. Just the raw JSON.

## Frozen spec (v9)

erd_version: 9
files to build: ["src/static/index.html"]
entry_points: ["src.main:app", "src.services.llm", "src.services.llm:stream_reply", \
"src.services.models", "src.services.models:list_models", "src.services.models:load_nemotron", \
"src.services.models:unload_nemotron", "src.services.models:is_nemotron_loaded", "src.api.chat"]

## Frozen test node-ids (60 total, showing all)

tests/test_chat_api.py::TestM3ChatRouteCarried::test_chat_opens_event_stream_200
tests/test_chat_api.py::TestM3ChatRouteCarried::test_chat_streams_token_events_in_order
tests/test_chat_api.py::TestM3ChatRouteCarried::test_chat_emits_done_after_tokens
tests/test_chat_api.py::TestM3ChatRouteCarried::test_chat_connection_error_emits_error_only
tests/test_chat_api.py::TestM3ChatRouteCarried::test_chat_mid_stream_failure_emits_error_after_tokens
tests/test_page.py::test_root_serves_html
tests/test_models_api.py::test_list_models_includes_lmstudio_entries
tests/test_models_api.py::test_list_models_degrades_when_lmstudio_unreachable
tests/test_models_api.py::test_list_models_omits_nemotron_when_not_loaded
tests/test_models_api.py::test_load_nemotron_spawns_and_confirms_ready
tests/test_models_api.py::test_load_nemotron_idempotent_when_already_loaded
tests/test_models_api.py::test_load_nemotron_timeout_returns_503_and_terminates
tests/test_models_api.py::test_unload_nemotron_terminates_process
tests/test_models_api.py::test_unload_nemotron_idempotent_when_not_loaded
tests/test_models_service.py::test_list_models_includes_lmstudio_entries
tests/test_models_service.py::test_list_models_excludes_models_without_loaded_instances
tests/test_models_service.py::test_list_models_queries_lmstudio_native_endpoint
tests/test_models_service.py::test_list_models_returns_empty_on_exception
tests/test_models_service.py::test_list_models_returns_empty_on_non_2xx
tests/test_models_service.py::test_list_models_omits_nemotron_when_not_loaded
tests/test_models_service.py::test_list_models_includes_nemotron_when_loaded
tests/test_models_service.py::test_is_nemotron_loaded_true_when_probe_succeeds
tests/test_models_service.py::test_is_nemotron_loaded_false_when_probe_unreachable
tests/test_models_service.py::test_is_nemotron_loaded_false_when_probe_non_200
tests/test_models_service.py::test_load_nemotron_spawns_and_confirms_ready
tests/test_models_service.py::test_load_nemotron_idempotent_when_already_loaded
tests/test_models_service.py::test_load_nemotron_timeout_sigints_and_clears_process
tests/test_models_service.py::test_load_nemotron_aborts_when_process_exits_early
tests/test_models_service.py::test_load_nemotron_expands_script_path
tests/test_models_service.py::test_unload_nemotron_sigints_process
tests/test_models_service.py::test_unload_nemotron_idempotent_when_not_loaded
tests/test_models_service.py::test_unload_nemotron_tolerates_externally_started_runtime
tests/test_chat_model_routing.py::test_chat_routes_to_nemotron_when_selected
tests/test_chat_model_routing.py::test_chat_routes_to_lmstudio_when_model_absent_or_other
tests/test_chat_model_routing.py::test_chat_invalid_model_type_is_422
tests/test_chat_model_routing.py::test_chat_nemotron_selected_but_not_loaded_is_422
tests/test_llm_service.py::TestM3StreamReplyCarried::test_request_carries_model_user_message_and_stream_true
tests/test_llm_service.py::TestM3StreamReplyCarried::test_system_prompt_included_when_set
tests/test_llm_service.py::TestM3StreamReplyCarried::test_system_prompt_omitted_when_empty
tests/test_llm_service.py::TestM3StreamReplyCarried::test_content_chunks_yielded_as_tokens_in_order
tests/test_llm_service.py::TestM3StreamReplyCarried::test_clean_completion_yields_done
tests/test_llm_service.py::TestM3StreamReplyCarried::test_empty_stream_yields_error_not_done
tests/test_llm_service.py::TestM3StreamReplyCarried::test_config_read_at_call_time
tests/test_llm_service.py::TestM3StreamReplyCarried::test_connection_error_yields_error_with_no_tokens
tests/test_llm_service.py::TestM3StreamReplyCarried::test_non_2xx_yields_error_with_no_tokens
tests/test_llm_service.py::TestM3StreamReplyCarried::test_timeout_to_first_byte_yields_error
tests/test_llm_service.py::TestM3StreamReplyCarried::test_mid_stream_drop_yields_error_after_tokens
tests/test_llm_service.py::TestM4HistoryUpstream::test_history_entries_in_upstream_messages
tests/test_llm_service.py::TestM4HistoryUpstream::test_history_with_system_prompt_ordering
tests/test_llm_service.py::TestM4HistoryUpstream::test_history_without_system_prompt_ordering
tests/test_llm_service.py::TestM4HistoryUpstream::test_empty_history_matches_m3_behavior
tests/test_llm_service.py::TestM4HistoryUpstream::test_multi_turn_history_preserves_all_entries
tests/test_llm_service.py::TestM4HistoryUpstream::test_history_does_not_affect_streaming_behavior
tests/test_llm_service.py::TestM5ModelParameter::test_model_parameter_overrides_env_default
tests/test_llm_service.py::TestM5ModelParameter::test_model_parameter_none_falls_back_to_env
tests/test_llm_service.py::TestM5ReasoningContent::test_reasoning_content_yields_think_chunks
tests/test_llm_service.py::TestM5ReasoningContent::test_reasoning_then_content_yields_both_in_order
tests/test_chat_api.py::TestM4HistoryRouteCarried::test_chat_sends_history_in_upstream_messages
tests/test_chat_api.py::TestM5ChatModelRouting::test_chat_passes_model_to_stream_reply
tests/test_chat_api.py::TestM5ChatModelRouting::test_chat_think_event_emitted_for_reasoning

## Plan schema rules

The JSON must have these top-level keys:
- "erd_version": integer, must equal 9
- "tasks": array of task objects
- "regression": array of strings — every frozen test node-id that is NOT \
mapped to any task's "tests" array must appear here EXACTLY ONCE. These are \
carried-forward tests. Since M6 only modifies src/static/index.html (no \
backend changes), ALL 60 test node-ids should go in regression (none are \
mapped to the single task, because the task has no pytest tests — M6 is \
frontend-only).

Each task object has exactly these keys (no extras):
- "id": string like "T1"
- "file": string, must be in the files array from contracts.json
- "depends_on": array of task id strings (empty for no deps)
- "brief": string under 2500 chars describing what to implement
- "contracts": array of contract id strings from contracts.json
- "tests": array of frozen test node-id strings mapped to this task
"""


def extract_json(text):
    """Try to extract JSON from model output, stripping thinking blocks and markdown fences."""
    # Strip <think>...</think> blocks (qwen thinking output)
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    # Strip "Thinking Process:" style preambles before JSON
    text = text.strip()

    # Strip markdown fences
    if text.startswith("```"):
        lines = text.split("\n")
        start = 1
        end = len(lines)
        if lines[-1].strip() == "```":
            end = len(lines) - 1
        text = "\n".join(lines[start:end])

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try to find first JSON object in the text
    for i, c in enumerate(text):
        if c == '{':
            depth = 0
            for j in range(i, len(text)):
                if text[j] == '{':
                    depth += 1
                elif text[j] == '}':
                    depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[i:j+1])
                    except json.JSONDecodeError:
                        break
    return None


FROZEN_NODEIDS = set(
    PROMPT.split("## Frozen test node-ids (60 total, showing all)\n\n")[1]
    .split("\n\n## Plan schema rules")[0]
    .strip()
    .split("\n")
)


def score(plan):
    """Score a plan against the schema rules. Returns (score 0-100, list of issues)."""
    issues = []
    points = 0

    if plan is None:
        return 0, ["Failed to parse JSON"]

    # erd_version
    if plan.get("erd_version") == 9:
        points += 15
    else:
        issues.append(f"erd_version={plan.get('erd_version')}, want 9")

    # tasks array exists
    tasks = plan.get("tasks", [])
    if isinstance(tasks, list) and len(tasks) > 0:
        points += 10
    else:
        issues.append("no tasks array or empty")

    # Single task for src/static/index.html
    if len(tasks) == 1:
        points += 10
        t = tasks[0]
        if t.get("file") == "src/static/index.html":
            points += 10
        else:
            issues.append(f"task file={t.get('file')}, want src/static/index.html")
        # Check only allowed keys
        extra = set(t.keys()) - {"id", "file", "depends_on", "brief", "contracts", "tests"}
        if extra:
            issues.append(f"extra task keys: {extra}")
        else:
            points += 5
        # brief under 2500
        if isinstance(t.get("brief"), str) and len(t["brief"]) <= 2500:
            points += 5
        else:
            issues.append("brief missing or over 2500 chars")
    elif len(tasks) > 1:
        issues.append(f"{len(tasks)} tasks, want 1")

    # REGRESSION ARRAY — this is the key failure mode
    regression = plan.get("regression")
    if regression is None:
        issues.append("regression array MISSING (the exact failure mode)")
    elif not isinstance(regression, list):
        issues.append(f"regression is {type(regression).__name__}, not list")
    else:
        points += 15  # array exists
        reg_set = set(regression)

        # All should be valid node-ids
        invalid = reg_set - FROZEN_NODEIDS
        if invalid:
            issues.append(f"{len(invalid)} invalid regression node-ids")
        else:
            points += 10

        # All 60 should be present (no tasks map tests in M6)
        mapped = set()
        for t in tasks:
            mapped.update(t.get("tests", []))
        expected_regression = FROZEN_NODEIDS - mapped

        missing = expected_regression - reg_set
        if missing:
            issues.append(f"{len(missing)} node-ids missing from regression")
        else:
            points += 15

        # No duplicates
        if len(regression) != len(reg_set):
            issues.append(f"{len(regression) - len(reg_set)} duplicate regression entries")
        else:
            points += 5

    return points, issues


def call_model(model_name):
    """Call a model and return (raw_text, parsed_json, duration)."""
    start = time.monotonic()
    try:
        resp = httpx.post(
            ENDPOINT,
            json={
                "model": model_name,
                "messages": [{"role": "user", "content": PROMPT}],
                "temperature": 0.1,
                "max_tokens": 16000,
                "stream": False,
            },
            timeout=180,
        )
        resp.raise_for_status()
        data = resp.json()
        text = data["choices"][0]["message"]["content"]
        duration = time.monotonic() - start
        parsed = extract_json(text)
        return text, parsed, duration
    except Exception as e:
        duration = time.monotonic() - start
        return str(e), None, duration


def main():
    print(f"Frozen node-ids: {len(FROZEN_NODEIDS)}")
    print("=" * 70)

    results = {}
    for model in MODELS:
        print(f"\n{'=' * 70}")
        print(f"MODEL: {model}")
        print(f"{'=' * 70}")

        text, parsed, duration = call_model(model)
        s, issues = score(parsed)
        results[model] = (s, issues, duration)

        print(f"Duration: {duration:.1f}s")
        print(f"Score: {s}/100")
        if issues:
            print("Issues:")
            for issue in issues:
                print(f"  - {issue}")
        else:
            print("PERFECT — no issues")

        if parsed:
            print(f"erd_version: {parsed.get('erd_version')}")
            print(f"tasks: {len(parsed.get('tasks', []))}")
            reg = parsed.get("regression")
            if reg is None:
                print("regression: MISSING")
            else:
                print(f"regression: {len(reg)} entries")
        else:
            print("RAW OUTPUT (first 500 chars):")
            print(text[:500])

    print(f"\n{'=' * 70}")
    print("SUMMARY")
    print(f"{'=' * 70}")
    for model in MODELS:
        s, issues, duration = results[model]
        status = "PASS" if s >= 90 else "MARGINAL" if s >= 60 else "FAIL"
        print(f"  {model:30s}  score={s:3d}/100  time={duration:5.1f}s  {status}")


if __name__ == "__main__":
    main()
