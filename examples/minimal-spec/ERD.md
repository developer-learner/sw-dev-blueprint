ERD — linkbox M1: core bookmarks API (erd_version 1)

Stack: FastAPI + stdlib sqlite3 (NO ORM, NO aiosqlite — plain synchronous
sqlite3 from the standard library). All endpoints are plain `def` (sync).
No new dependencies beyond what requirements.txt already pins.

The bookmark record (one shape everywhere — storage returns it, the API
serializes it verbatim):

    {"id": int, "url": str, "title": str, "notes": str,
     "tags": list[str], "read": bool, "created_at": str}

created_at is `datetime.now(timezone.utc).isoformat()` at insert time.
Defaults when absent on create: title "", notes "", tags [], read false.

File inventory (M1 build) — DAG order

1. src/storage.py — NEW. The only file that touches SQLite. Pure
   synchronous stdlib: sqlite3, json, os, datetime. No FastAPI imports.

   Table (created lazily): every public function below gets its own
   connection via a private `_connect()` helper that (a) creates the
   parent directory of the DB path if needed, (b) opens
   `sqlite3.connect(path)` with `row_factory = sqlite3.Row`, and
   (c) runs:

       CREATE TABLE IF NOT EXISTS bookmarks (
           id INTEGER PRIMARY KEY AUTOINCREMENT,
           url TEXT NOT NULL UNIQUE,
           title TEXT NOT NULL DEFAULT '',
           notes TEXT NOT NULL DEFAULT '',
           tags TEXT NOT NULL DEFAULT '[]',
           read INTEGER NOT NULL DEFAULT 0,
           created_at TEXT NOT NULL
       )

   The DB path is read PER CALL from the environment:
   `os.environ.get("LINKBOX_DB", "data/linkbox.db")` — never cached at
   import time (tests point different tests at different temp files).
   `tags` is stored as a JSON array string; `read` as 0/1. A private
   `_row_to_dict(row)` converts a row to the bookmark record above
   (json.loads the tags, bool() the read flag).

   Public surface (exact signatures):
   - `class DuplicateURL(Exception)` — raised when inserting a url that
     already exists (catch sqlite3.IntegrityError on INSERT).
   - `init_db() -> None` — just opens and closes a `_connect()`.
   - `add_bookmark(url: str, title: str = "", tags: list[str] | None = None,
     notes: str = "") -> dict` — inserts, returns the full record.
   - `get_bookmark(bookmark_id: int) -> dict | None`
   - `list_bookmarks(tag: str | None = None, q: str | None = None,
     unread: bool | None = None) -> list[dict]` — SELECT all ordered by
     id DESC, then filter in Python (personal scale, correctness over
     cleverness): tag = exact membership in the tags list; q =
     case-insensitive substring against url, title, or notes; unread True
     keeps only read == False, unread False keeps only read == True.
   - `update_bookmark(bookmark_id: int, fields: dict) -> dict | None` —
     applies only the keys "title", "notes", "tags", "read" if present
     in `fields` (ignore any other keys); returns the updated record, or
     None if the id does not exist.
   - `delete_bookmark(bookmark_id: int) -> bool` — True if a row was
     deleted, False if the id did not exist.

2. src/api.py — NEW. Depends on src/storage.py. Defines the FastAPI app
   and all routes in this one file. Module level: `app = FastAPI(title=
   "linkbox")`. Request bodies via two pydantic BaseModel classes defined
   here: BookmarkCreate (url: str; title: str = ""; tags: list[str] = [];
   notes: str = "") and BookmarkUpdate (title/notes/tags/read, each
   optional, default None). All handlers are sync `def`.

   Routes (all under /api/v1):
   - POST /api/v1/bookmarks — if the url does not start with "http://"
     or "https://", raise HTTPException(422, "url must start with
     http:// or https://"). On storage.DuplicateURL raise
     HTTPException(409, "duplicate url"). Success: status 201, body =
     the bookmark record.
   - GET /api/v1/bookmarks — optional query params tag (str), q (str),
     unread (bool); pass straight through to storage.list_bookmarks;
     returns the JSON array.
   - GET /api/v1/bookmarks/{bookmark_id} — 200 with the record, or
     HTTPException(404, "bookmark not found").
   - PATCH /api/v1/bookmarks/{bookmark_id} — build the fields dict from
     the body's fields that are not None
     (`body.model_dump(exclude_none=True)`), call
     storage.update_bookmark; 404 as above if it returns None, else 200
     with the updated record.
   - DELETE /api/v1/bookmarks/{bookmark_id} — 404 as above if
     storage.delete_bookmark returns False, else status 204 with empty
     body.

   All error bodies are FastAPI's default shape: {"detail": "<message>"}.

Constraints (both files): type hints on every public signature, no
global mutable state, no threads, no network calls, stdlib +
fastapi/pydantic only, each file under 150 lines.
