# PRD — linkbox (M1: core bookmarks API)

## Problem

The CEO saves links in chat windows, notes files, and browser tabs, and
loses them. He wants one small self-hosted place to throw URLs at and get
them back later, filtered by tag or search, with a read/unread state —
usable from curl today and a UI later.

## Product

`linkbox` — a personal read-later bookmarks HTTP API. Single user, no
auth, runs on localhost. SQLite on disk; no external services.

## M1 scope (this milestone)

- Save a bookmark: URL (required, must be http/https), optional title,
  tags, and notes. Saving the same URL twice is rejected — the URL is the
  identity of a bookmark.
- List bookmarks, newest first, filterable by: a tag, a case-insensitive
  text search over url/title/notes, and read/unread state. Filters
  combine.
- Fetch, update (title, tags, notes, read flag), and delete a single
  bookmark by id.
- Data survives restarts (SQLite file; path from `LINKBOX_DB` env var,
  default `data/linkbox.db`).

## Explicitly out of scope for M1

Auth, multi-user, fetching page titles from the web, favicons, full-text
ranking, import/export, any UI. The API is the product this milestone.

## Success criteria

The frozen test suite is the binding definition (D-54). Informally: the
CEO can curl every operation above against a running instance and the
data is still there after a restart.
