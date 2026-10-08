"""D-209: Rule 1 is an admission test, not a model-name ban.

seat-check.sh drives the REAL llm-call.sh against a tiny fake server whose
reply shape each test controls. A reasoning model is admitted when its final
answer arrives as content; reasoning-only, truncated, or unparseable replies
are refused.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1]
GOOD_FILE = "=== FILE: src/seat_check_probe.py ===\ndef add(a: int, b: int) -> int:\n    return a + b\n=== END FILE ==="
GOOD_JSON = json.dumps({"verdict": "brief_wrong", "reason": "the brief omits the 201 status",
                        "revised_brief": "Return 201 from POST /items."})


def serve(message: dict, finish: str = "stop"):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *_a):
            pass

        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            body = json.dumps({"model": "m", "choices": [
                {"message": message, "finish_reason": finish}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def check(tmp_path: Path, role: str, message: dict, finish: str = "stop"):
    srv = serve(message, finish)
    try:
        env = {**os.environ, "HOME": str(tmp_path),  # no models.env / profiles
               "SANDBOX_LLM_HOST": "127.0.0.1", "SANDBOX_LLM_PORT": str(srv.server_port),
               f"SWBP_{role.upper()}_MODEL": "m"}
        return subprocess.run(["bash", str(SCRIPTS / "seat-check.sh"), role],
                              capture_output=True, text=True, env=env, timeout=60)
    finally:
        srv.shutdown()


def test_coder_with_complete_content_is_admitted(tmp_path):
    r = check(tmp_path, "coder", {"content": GOOD_FILE})
    assert r.returncode == 0 and "ADMITTED" in r.stdout, (r.stdout, r.stderr)


def test_reasoning_model_with_final_content_is_admitted(tmp_path):
    """The old Rule 1 banned these outright. What matters is the content."""
    r = check(tmp_path, "coder", {"reasoning_content": "Let me think about add()...",
                                  "content": GOOD_FILE})
    assert r.returncode == 0 and "ADMITTED" in r.stdout, (r.stdout, r.stderr)


def test_leading_think_block_in_content_is_admitted(tmp_path):
    r = check(tmp_path, "coder", {"content": "<think>plan the file</think>\n" + GOOD_FILE})
    assert r.returncode == 0, (r.stdout, r.stderr)


@pytest.mark.parametrize("message,finish,why", [
    ({"reasoning_content": "thinking...", "content": ""}, "stop", "llm-call failed"),
    ({"content": GOOD_FILE[:40]}, "length", "did not finish naturally"),
    ({"content": "Sure, here is the code: def add(a, b): return a + b"}, "stop", "not a complete"),
    ({"content": "=== FILE: src/seat_check_probe.py ===\ndef add(:\n=== END FILE ==="}, "stop", "not a complete"),
])
def test_coder_is_refused_without_a_complete_artifact(tmp_path, message, finish, why):
    r = check(tmp_path, "coder", message, finish)
    assert r.returncode == 1 and why in r.stdout, (r.stdout, r.stderr)


def test_em_with_valid_diagnosis_is_admitted(tmp_path):
    r = check(tmp_path, "em", {"content": GOOD_JSON})
    assert r.returncode == 0 and "ADMITTED" in r.stdout, (r.stdout, r.stderr)


def test_em_with_invalid_diagnosis_is_refused(tmp_path):
    r = check(tmp_path, "em", {"content": json.dumps({"verdict": "looks fine"})})
    assert r.returncode == 1 and "not a valid diagnosis" in r.stdout, (r.stdout, r.stderr)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
