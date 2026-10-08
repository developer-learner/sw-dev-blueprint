#!/usr/bin/env python3
"""e2e_fake_llm.py — a scripted stand-in for the local model server (D-208).

Serves the OpenAI-compatible endpoints llm-call.sh uses (/v1/models and
/v1/chat/completions) so the REAL orchestrate.sh can run end to end with no
model loaded. Each role answers from a fixed script; every request is logged
as one JSON line so the harness can assert what the pipeline asked and when.

    e2e_fake_llm.py --port 18765 --ws <app root> --src <dir with correct
                    storage.py/api.py> --log <requests.jsonl>

The script deliberately misbehaves first, to drive every D-207 path:
  planner  : plan #1 omits a task (plan gate must reject), plan #2 is valid
  coder    : src/storage.py — first a SPEC PROBLEM report, then (after the
             EM consult revises the brief) the correct file
             src/api.py — first prose with no file block (reply-format
             gate), then a file that fails the frozen tests (test verdict),
             then (after the consult) an anchored edit that fixes it
  consults : always brief_wrong with a revised brief
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


GOOD_ROUTE = '@app.post("/api/v1/bookmarks", status_code=201)'
BAD_ROUTE = '@app.post("/api/v1/bookmarks", status_code=200)'


def build_state(ws: Path, src: Path) -> dict:
    storage = (src / "storage.py").read_text()
    # The reference api.py predates the lint gate: drop its unused imports so
    # the "correct" answer is correct by today's gates too.
    api = (src / "api.py").read_text().replace(
        "from fastapi import FastAPI, HTTPException, Path, Depends, Query",
        "from fastapi import FastAPI, HTTPException, Query").replace(
        "from pydantic import BaseModel, Field", "from pydantic import BaseModel")
    buggy_api = api.replace(GOOD_ROUTE, BAD_ROUTE)
    assert buggy_api != api, "could not derive the buggy api.py"
    return {
        "ws": ws,
        "plans": ["incomplete", "valid"],
        "coder": {
            "src/storage.py": [
                "=== SPEC PROBLEM: the brief names the storage functions but not the "
                "LINKBOX_DB environment variable the frozen tests set ===",
                f"=== FILE: src/storage.py ===\n{storage}\n=== END FILE ===",
            ],
            "src/api.py": [
                "Sure! Here is how I would implement the API module.",
                f"=== FILE: src/api.py ===\n{buggy_api}\n=== END FILE ===",
                # the buggy file is now committed: the fix is an anchored edit
                f"<<<<<<< SEARCH\n{BAD_ROUTE}\n=======\n{GOOD_ROUTE}\n>>>>>>> REPLACE",
            ],
        },
        "lock": threading.Lock(),
    }


def node_ids(ws: Path, test_file: str) -> list[str]:
    ids = (ws / "scripts/.approved/test-nodeids").read_text().split()
    return [i for i in ids if i.startswith(test_file + "::")]


BRIEF_STORAGE = (
    "Create src/storage.py: a SQLite-backed bookmark store whose database path "
    "comes from the LINKBOX_DB environment variable. Implement exactly the "
    "entry points in contracts.json — DuplicateURL, init_db, add_bookmark, "
    "get_bookmark, list_bookmarks, update_bookmark, delete_bookmark — with the "
    "signatures and behavior in the ERD. Acceptance: the mapped storage tests pass."
)
BRIEF_API = (
    "Create src/api.py: a FastAPI app named app exposing the five "
    "/api/v1/bookmarks routes in contracts.json on top of src/storage.py, with "
    "the error shapes in contracts.json (404 bookmark not found, 409 duplicate "
    "url, 422 bad url). Acceptance: the mapped api tests pass."
)


def plan(state: dict, kind: str) -> str:
    ws = state["ws"]
    tasks = [{"id": "T1", "file": "src/storage.py", "depends_on": [],
              "brief": BRIEF_STORAGE, "contracts": [],
              "tests": node_ids(ws, "tests/test_storage.py")}]
    if kind == "valid":
        tasks.append({"id": "T2", "file": "src/api.py", "depends_on": ["T1"],
                      "brief": BRIEF_API, "contracts": [],
                      "tests": node_ids(ws, "tests/test_api.py")})
    version = 1 if kind == "incomplete" else 2
    return json.dumps({"erd_version": 1, "version": version, "tasks": tasks})


def diagnosis(user: str) -> str:
    brief = BRIEF_API if "src/api.py" in user else BRIEF_STORAGE
    return json.dumps({
        "verdict": "brief_wrong",
        "reason": "the brief left out a detail the frozen tests depend on",
        "revised_brief": brief + " Read the database path from LINKBOX_DB on every call.",
    })


class Handler(BaseHTTPRequestHandler):
    state: dict = {}
    log_path: Path = Path("requests.jsonl")

    def log_message(self, *_args) -> None:  # quiet
        pass

    def _send(self, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        self._send({"object": "list", "data": [{"id": "sim-em"}, {"id": "sim-coder"}]})

    def do_POST(self) -> None:
        req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        system, user = req["messages"][0]["content"], req["messages"][1]["content"]
        st = self.state
        with st["lock"]:
            if "You are the coder" in system:
                m = re.search(r"Write EXACTLY one file: (\S+)", user)
                target = m.group(1) if m else "?"
                queue = st["coder"].get(target, [])
                content = queue.pop(0) if queue else "=== NO CHANGES ==="
                role = f"coder:{target}"
            elif user.strip() == "SMOKE_OK":
                content, role = "SMOKE_OK", "em:smoke"
            elif "Decompose the frozen ERD" in user:
                kind = st["plans"].pop(0) if st["plans"] else "valid"
                content, role = plan(st, kind), f"em:plan:{kind}"
            else:
                content, role = diagnosis(user), "em:consult"
            with open(self.log_path, "a") as fh:
                fh.write(json.dumps({"t": time.time(), "role": role,
                                     "reply_head": content[:90]}) + "\n")
        self._send({"id": f"sim-{time.time_ns()}", "model": req.get("model", ""),
                    "object": "chat.completion",
                    "choices": [{"index": 0, "finish_reason": "stop",
                                 "message": {"role": "assistant", "content": content}}],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1}})


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=18765)
    ap.add_argument("--ws", type=Path, required=True)
    ap.add_argument("--src", type=Path, required=True)
    ap.add_argument("--log", type=Path, required=True)
    a = ap.parse_args()
    Handler.state = build_state(a.ws, a.src)
    Handler.log_path = a.log
    ThreadingHTTPServer(("127.0.0.1", a.port), Handler).serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
