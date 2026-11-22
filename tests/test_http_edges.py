"""HTTP edges: unknown routes and methods, odd keys, and limits at their boundaries."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

KEY = "http-edges-key-1234"
ROUTES = ["/vitals", "/services", "/containers", "/processes", "/logs/errors", "/packages"]


def make_client(tmp_path, monkeypatch):
    monkeypatch.setenv("SYSTEMGATE_ADMIN_KEY", KEY)
    monkeypatch.setenv("SYSTEMGATE_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("SYSTEMGATE_BACKUP_ROOT", str(tmp_path / "backups"))
    from systemgate.main import app

    return TestClient(app)


def good():
    return {"X-SystemGate-Key": KEY}


@pytest.mark.parametrize("path", ["/", "/nope", "/vitals/extra", "/admin"])
def test_an_unknown_route_is_404_with_or_without_the_key(tmp_path, monkeypatch, path):
    with make_client(tmp_path, monkeypatch) as client:
        for headers in ({}, good()):
            response = client.get(path, headers=headers, follow_redirects=False)
            assert response.status_code in (404, 307), (path, response.status_code)
            assert KEY not in response.text


@pytest.mark.parametrize("method", ["head", "options"])
def test_head_and_options_are_not_offered(tmp_path, monkeypatch, method):
    with make_client(tmp_path, monkeypatch) as client:
        for path in ["/health", *ROUTES, "/backups", "/runtime"]:
            response = getattr(client, method)(path, headers=good())
            assert response.status_code == 405, (method, path)


def test_health_refuses_a_write_even_with_the_key(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        for method in ("post", "put", "patch", "delete"):
            response = getattr(client, method)("/health", headers=good())
            assert response.status_code == 405, method


@pytest.mark.parametrize("path", [*ROUTES, "/backups", "/runtime"])
def test_the_key_in_the_query_string_or_a_wrong_header_name_is_not_a_key(
    tmp_path, monkeypatch, path
):
    with make_client(tmp_path, monkeypatch) as client:
        assert client.get(path, params={"key": KEY, "X-SystemGate-Key": KEY}).status_code == 401
        assert client.get(path, headers={"X-Embeddings-Key": KEY}).status_code == 401
        assert client.get(path, headers={"Authorization": f"Bearer {KEY}"}).status_code == 401


def test_the_key_header_name_is_case_insensitive_but_its_value_is_exact(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        assert client.get("/backups", headers={"x-systemgate-key": KEY}).status_code == 200
        for value in (KEY.upper(), KEY + " x", KEY[:-1], "x" + KEY):
            response = client.get("/backups", headers={"X-SystemGate-Key": value})
            assert response.status_code == 401, value


@pytest.mark.parametrize(
    "value",
    [b"", b" ", "ключ-не-тот".encode(), b"\xff\xfe", b"k" * 100_000],
    ids=["empty", "blank", "non-ascii", "binary", "very-long"],
)
def test_an_odd_key_header_is_a_wrong_key_not_a_crash(tmp_path, monkeypatch, value):
    with make_client(tmp_path, monkeypatch) as client:
        response = client.get("/backups", headers={"X-SystemGate-Key": value})
        assert response.status_code == 401
        assert response.json() == {"detail": "missing or invalid X-SystemGate-Key"}


@pytest.mark.parametrize("path", ["/processes", "/services"])
@pytest.mark.parametrize("value", ["", "1.5", "1e2", "0x10", "--1", " ", "٣"])
def test_a_limit_that_is_not_an_integer_is_refused(tmp_path, monkeypatch, path, value):
    with make_client(tmp_path, monkeypatch) as client:
        response = client.get(path, params={"limit": value}, headers=good())
        assert response.status_code == 422, (path, value)


@pytest.mark.parametrize("limit", ["0", "-1", "-100000"])
def test_a_limit_below_one_still_returns_one_process(tmp_path, monkeypatch, limit):
    with make_client(tmp_path, monkeypatch) as client:
        response = client.get("/processes", params={"limit": limit}, headers=good())
        assert response.status_code == 200
        assert len(response.json()["results"]) == 1


def test_the_process_limit_is_exact_at_the_cap_and_one_over(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        at = client.get("/processes", params={"limit": 100}, headers=good()).json()["results"]
        over = client.get("/processes", params={"limit": 101}, headers=good()).json()["results"]
        assert len(over) == len(at) <= 100


def test_a_repeated_limit_is_read_as_its_last_value(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        assert client.get("/processes?limit=abc&limit=1", headers=good()).status_code == 200
        assert client.get("/processes?limit=1&limit=abc", headers=good()).status_code == 422


def test_a_service_limit_below_one_still_answers(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        response = client.get("/services", params={"limit": -5}, headers=good())
        assert response.status_code == 200
        assert len(response.json()["results"]) <= 1
