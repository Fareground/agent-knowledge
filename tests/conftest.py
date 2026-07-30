"""Shared fixtures. Every store-touching test runs against both stores —
parity between SQLiteStore and InMemoryStore is an acceptance criterion."""

from __future__ import annotations

import pytest
from fg_agent_id import KeyPair

from fg_agent_knowledge import InMemoryStore, KnowledgeBase, SQLiteStore


@pytest.fixture(params=["memory", "sqlite"])
def store(request, tmp_path):
    if request.param == "memory":
        return InMemoryStore()
    return SQLiteStore(str(tmp_path / "kb.db"))


@pytest.fixture
def kb(store):
    return KnowledgeBase(store)


@pytest.fixture
def agent_a():
    return KeyPair.generate()


@pytest.fixture
def agent_b():
    return KeyPair.generate()


@pytest.fixture
def human():
    return KeyPair.generate()
