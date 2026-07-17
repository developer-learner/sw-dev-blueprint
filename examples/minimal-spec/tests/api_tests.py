"""Frozen suite — src/api.py (linkbox M1, spec v1).

In-process only (TestClient / ASGI); no real sockets (D-30 sandbox has
no network). Observes the system only through declared entry points and
routes (INV-4).
"""

import pytest
from fastapi.testclient import TestClient

from src.api import app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("LINKBOX_DB", str(tmp_path / "linkbox.db"))
    return TestClient(app)


def _create(client, url, **extra):
    return client.post("/api/v1/bookmarks", json={"url": url, **extra})


def test_create_returns_201_and_record(client):
    resp = _create(client, "https://example.com/a", title="A", tags=["t1"], notes="n")
    assert resp.status_code == 201
    body = resp.json()
    assert body["id"] == 1
    assert body["url"] == "https://example.com/a"
    assert body["title"] == "A"
    assert body["tags"] == ["t1"]
    assert body["notes"] == "n"
    assert body["read"] is False
    assert isinstance(body["created_at"], str) and body["created_at"]


def test_create_rejects_non_http_url(client):
    resp = _create(client, "ftp://example.com/file")
    assert resp.status_code == 422
    assert resp.json()["detail"] == "url must start with http:// or https://"


def test_create_duplicate_url_is_409(client):
    assert _create(client, "https://example.com/dup").status_code == 201
    resp = _create(client, "https://example.com/dup")
    assert resp.status_code == 409
    assert resp.json()["detail"] == "duplicate url"


def test_list_newest_first(client):
    _create(client, "https://example.com/1")
    _create(client, "https://example.com/2")
    resp = client.get("/api/v1/bookmarks")
    assert resp.status_code == 200
    assert [b["url"] for b in resp.json()] == [
        "https://example.com/2",
        "https://example.com/1",
    ]


def test_list_filters_combine(client):
    _create(client, "https://example.com/py", title="Python Weekly", tags=["python"])
    _create(client, "https://example.com/rs", title="Rust Weekly", tags=["rust"])
    resp = client.get("/api/v1/bookmarks", params={"tag": "python", "q": "weekly"})
    assert [b["url"] for b in resp.json()] == ["https://example.com/py"]
    resp = client.get("/api/v1/bookmarks", params={"tag": "python", "q": "rust"})
    assert resp.json() == []


def test_list_unread_filter(client):
    _create(client, "https://example.com/keep")
    done = _create(client, "https://example.com/done").json()
    client.patch(f"/api/v1/bookmarks/{done['id']}", json={"read": True})
    resp = client.get("/api/v1/bookmarks", params={"unread": "true"})
    assert [b["url"] for b in resp.json()] == ["https://example.com/keep"]
    resp = client.get("/api/v1/bookmarks", params={"unread": "false"})
    assert [b["url"] for b in resp.json()] == ["https://example.com/done"]


def test_get_by_id_and_404(client):
    made = _create(client, "https://example.com/get").json()
    resp = client.get(f"/api/v1/bookmarks/{made['id']}")
    assert resp.status_code == 200
    assert resp.json()["url"] == "https://example.com/get"
    resp = client.get("/api/v1/bookmarks/9999")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "bookmark not found"


def test_patch_updates_and_404(client):
    made = _create(client, "https://example.com/upd", title="old").json()
    resp = client.patch(
        f"/api/v1/bookmarks/{made['id']}",
        json={"title": "new", "read": True},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["title"] == "new"
    assert body["read"] is True
    assert body["url"] == "https://example.com/upd"
    resp = client.patch("/api/v1/bookmarks/9999", json={"title": "x"})
    assert resp.status_code == 404


def test_delete_204_then_404(client):
    made = _create(client, "https://example.com/del").json()
    resp = client.delete(f"/api/v1/bookmarks/{made['id']}")
    assert resp.status_code == 204
    assert client.get(f"/api/v1/bookmarks/{made['id']}").status_code == 404
    assert client.delete(f"/api/v1/bookmarks/{made['id']}").status_code == 404
