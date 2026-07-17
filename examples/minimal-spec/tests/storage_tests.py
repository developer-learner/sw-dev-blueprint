"""Frozen suite — src/storage.py (linkbox M1, spec v1).

Observes the system only through declared entry points (INV-4).
Each test gets its own SQLite file via the LINKBOX_DB env var.
"""

import pytest

from src.storage import (
    DuplicateURL,
    add_bookmark,
    delete_bookmark,
    get_bookmark,
    init_db,
    list_bookmarks,
    update_bookmark,
)


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    monkeypatch.setenv("LINKBOX_DB", str(tmp_path / "linkbox.db"))
    init_db()


def test_add_returns_full_record():
    rec = add_bookmark("https://example.com/a", title="A", tags=["read-later"], notes="n")
    assert rec["id"] == 1
    assert rec["url"] == "https://example.com/a"
    assert rec["title"] == "A"
    assert rec["notes"] == "n"
    assert rec["tags"] == ["read-later"]
    assert rec["read"] is False
    assert isinstance(rec["created_at"], str) and "T" in rec["created_at"]


def test_add_defaults():
    rec = add_bookmark("https://example.com/bare")
    assert rec["title"] == ""
    assert rec["notes"] == ""
    assert rec["tags"] == []
    assert rec["read"] is False


def test_duplicate_url_raises():
    add_bookmark("https://example.com/dup")
    with pytest.raises(DuplicateURL):
        add_bookmark("https://example.com/dup")


def test_list_newest_first():
    add_bookmark("https://example.com/1")
    add_bookmark("https://example.com/2")
    add_bookmark("https://example.com/3")
    urls = [b["url"] for b in list_bookmarks()]
    assert urls == [
        "https://example.com/3",
        "https://example.com/2",
        "https://example.com/1",
    ]


def test_list_filters_by_tag():
    add_bookmark("https://example.com/py", tags=["python", "blog"])
    add_bookmark("https://example.com/rs", tags=["rust"])
    hits = list_bookmarks(tag="python")
    assert [b["url"] for b in hits] == ["https://example.com/py"]
    assert list_bookmarks(tag="golang") == []


def test_list_search_is_case_insensitive_over_url_title_notes():
    add_bookmark("https://example.com/one", title="Deep Learning Weekly")
    add_bookmark("https://example.com/two", notes="great SQLITE walkthrough")
    add_bookmark("https://example.com/UNRELATED")
    assert [b["url"] for b in list_bookmarks(q="deep learning")] == ["https://example.com/one"]
    assert [b["url"] for b in list_bookmarks(q="sqlite")] == ["https://example.com/two"]
    assert [b["url"] for b in list_bookmarks(q="unrelated")] == ["https://example.com/UNRELATED"]
    assert list_bookmarks(q="no-such-text") == []


def test_list_filters_by_unread():
    kept = add_bookmark("https://example.com/unread")
    done = add_bookmark("https://example.com/read")
    update_bookmark(done["id"], {"read": True})
    assert [b["url"] for b in list_bookmarks(unread=True)] == ["https://example.com/unread"]
    assert [b["url"] for b in list_bookmarks(unread=False)] == ["https://example.com/read"]
    assert kept["read"] is False


def test_get_bookmark_found_and_missing():
    rec = add_bookmark("https://example.com/get")
    assert get_bookmark(rec["id"])["url"] == "https://example.com/get"
    assert get_bookmark(9999) is None


def test_update_applies_only_known_fields():
    rec = add_bookmark("https://example.com/upd", title="old")
    out = update_bookmark(
        rec["id"],
        {"title": "new", "tags": ["a", "b"], "read": True, "bogus": "ignored"},
    )
    assert out["title"] == "new"
    assert out["tags"] == ["a", "b"]
    assert out["read"] is True
    assert out["url"] == "https://example.com/upd"
    again = get_bookmark(rec["id"])
    assert again["title"] == "new" and again["read"] is True


def test_update_missing_returns_none():
    assert update_bookmark(9999, {"title": "x"}) is None


def test_delete_bookmark():
    rec = add_bookmark("https://example.com/del")
    assert delete_bookmark(rec["id"]) is True
    assert get_bookmark(rec["id"]) is None
    assert delete_bookmark(rec["id"]) is False


def test_data_persists_across_calls():
    add_bookmark("https://example.com/persist", title="still here")
    # every public call opens a fresh connection; the file is the state
    assert [b["title"] for b in list_bookmarks()] == ["still here"]
