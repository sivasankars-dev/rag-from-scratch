
import json

import pytest

from services.parent_child_store import ParentChildStore


@pytest.fixture
def parent_store(tmp_path):
    storage_path = tmp_path / "parents.json"
    return ParentChildStore(storage_path=storage_path)


def test_store_parent_and_retrieve_it(parent_store):
    parent = {
        "parent_id": "handbook.pdf_parent_0",
        "text": "Employees receive annual leave.",
        "source": "handbook.pdf",
        "page_number": 1,
    }

    parent_store.store_parent(parent)

    result = parent_store.get_parent("handbook.pdf_parent_0")

    assert result == parent


def test_get_unknown_parent_returns_none(parent_store):
    result = parent_store.get_parent("unknown_parent")

    assert result is None


def test_stored_parent_persists_after_reinitialization(tmp_path):
    storage_path = tmp_path / "parents.json"

    store1 = ParentChildStore(storage_path=storage_path)
    parent = {
        "parent_id": "handbook.pdf_parent_0",
        "text": "Employees receive annual leave.",
        "source": "handbook.pdf",
        "page_number": 1,
    }

    store1.store_parent(parent)

    store2 = ParentChildStore(storage_path=storage_path)

    assert store2.get_parent("handbook.pdf_parent_0") == parent
