from __future__ import annotations

import pytest

from systemgate import auth


@pytest.fixture
def slow(monkeypatch):
    """Every PBKDF2 run, with a fresh cache of matched keys."""
    monkeypatch.setattr(auth, "_matched", {})
    calls = []
    real = auth.hashlib.pbkdf2_hmac
    monkeypatch.setattr(auth.hashlib, "pbkdf2_hmac", lambda *args: calls.append(args) or real(*args))
    return calls


def test_a_matched_key_is_not_hashed_again(slow):
    encoded = auth.hash_key("right-key-1234")
    slow.clear()

    assert auth.verify_key("right-key-1234", encoded)
    assert len(slow) == 1
    assert auth.verify_key("right-key-1234", encoded)
    assert not auth.verify_key("wrong-key-1234", encoded)
    assert not auth.verify_key("right-key-12345", encoded)
    assert len(slow) == 1


def test_a_wrong_key_before_any_match_still_runs_the_full_check(slow):
    encoded = auth.hash_key("right-key-1234")
    slow.clear()

    assert not auth.verify_key("wrong-key-1234", encoded)
    assert not auth.verify_key("wrong-key-1234", encoded)
    assert len(slow) == 2


def test_a_new_key_file_is_checked_in_full(slow):
    first = auth.hash_key("right-key-1234")
    assert auth.verify_key("right-key-1234", first)
    rotated = auth.hash_key("other-key-5678")
    slow.clear()

    assert not auth.verify_key("right-key-1234", rotated)
    assert auth.verify_key("other-key-5678", rotated)
    assert len(slow) == 2
    assert auth.verify_key("other-key-5678", rotated)
    assert len(slow) == 2
