"""Offline contextual evaluation setup checks; no real stores or models."""

import importlib.util
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from services.parent_child_store import ParentChildStore

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/run_evaluate_contextual_retrieval.py"
spec = importlib.util.spec_from_file_location("contextual_eval_runner", SCRIPT)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)

CASE = {"question": "Leave?", "expected_answer": "annual leave",
        "expected_source": "handbook.pdf"}


@pytest.fixture
def stores(tmp_path):
    parent_path = tmp_path / "parents.json"
    parent_path.write_text(json.dumps({"p1": {
        "parent_id": "p1", "source": "handbook.pdf", "text": "Annual leave policy"
    }}))
    chroma_path = tmp_path / "chroma"
    chroma_path.mkdir()
    (chroma_path / "chroma.sqlite3").touch()  # Marker only; never opened.
    collection = Mock()
    collection.count.return_value = 1
    collection.get.return_value = {"metadatas": [
        {"parent_id": "p1", "source": "handbook.pdf"}
    ]}
    client = Mock()
    client.get_collection.return_value = collection
    return dict(parent_factory=ParentChildStore, child_factory=Mock(),
                client_factory=Mock(return_value=client),
                parent_path=parent_path, chroma_path=chroma_path)


def test_existing_collection_setup(stores):
    parents, children = runner.load_stores([CASE], **stores)
    client = stores["client_factory"].return_value
    client.get_collection.assert_called_once_with(name="contextual_employee_handbook")
    client.get_or_create_collection.assert_not_called()
    stores["child_factory"].assert_called_once_with(
        client=client, collection=client.get_collection.return_value)
    assert children is stores["child_factory"].return_value
    assert parents.get_parent("p1")["text"] == "Annual leave policy"


@pytest.mark.parametrize("failure", ["parents", "database", "collection", "empty_parents",
                                     "empty_children", "invalid_json", "orphan", "source"])
def test_invalid_stores_fail_without_creating_collection(stores, failure):
    client = stores["client_factory"].return_value
    collection = client.get_collection.return_value
    if failure == "parents":
        stores["parent_path"].unlink()
    elif failure == "database":
        (stores["chroma_path"] / "chroma.sqlite3").unlink()
    elif failure == "collection":
        client.get_collection.side_effect = ValueError("missing collection")
    elif failure == "empty_parents":
        stores["parent_path"].write_text("{}")
    elif failure == "invalid_json":
        stores["parent_path"].write_text("invalid")
    elif failure == "empty_children":
        collection.count.return_value = 0
    else:
        collection.get.return_value = {"metadatas": [{
            "parent_id": "missing" if failure == "orphan" else "p1",
            "source": "wrong.pdf",
        }]}
    with pytest.raises(ValueError, match="contextual"):
        runner.load_stores([CASE], **stores)
    stores["child_factory"].assert_not_called()
    client.get_or_create_collection.assert_not_called()


def test_wrapper_reuses_search_without_constructor(monkeypatch):
    from services.child_vector_store import ChildVectorStore

    constructor = Mock(side_effect=AssertionError("Must not create stores"))
    monkeypatch.setattr(ChildVectorStore, "__init__", constructor)
    collection = Mock()
    collection.count.return_value = 1
    collection.query.return_value = {
        "ids": [["c1"]], "documents": [["context\n\noriginal"]],
        "metadatas": [[{"parent_id": "p1"}]], "distances": [[0.1]],
    }
    store = runner.existing_child_store(Mock(), collection)
    assert store.search([1.0], top_k=3)[0]["child_id"] == "c1"
    constructor.assert_not_called()


def test_main_uses_twenty_cases_existing_stores_and_real_evaluator(monkeypatch, capsys):
    monkeypatch.setattr(runner, "load_cases", Mock(return_value=[CASE] * 20))
    parents = Mock()
    parents.get_parent.return_value = {
        "parent_id": "p1", "source": "handbook.pdf", "text": "Annual leave policy"
    }
    children = Mock()
    children.search.return_value = [{"metadata": {"parent_id": "p1"}}] * 3
    monkeypatch.setattr(runner, "load_stores", Mock(return_value=(parents, children)))
    embeddings = Mock()
    embeddings.embed_text.return_value = [1.0]
    monkeypatch.setattr(runner, "load_embedding_service", Mock(return_value=embeddings))
    runner.main([])
    runner.load_cases.assert_called_once_with(runner.DATASET_PATH, expected_count=20)
    assert children.search.call_count == 20
    assert all(call.kwargs == {"query_embedding": [1.0], "top_k": 3}
               for call in children.search.call_args_list)
    output = capsys.readouterr().out
    assert "Hit Rate@3 (proxy): 100.00%" in output
    assert "MRR@3 (proxy): 1.0000" in output
    assert "not semantic answer quality" in output
    assert runner.PARENT_PATH == runner.LEVEL3 / "data/contextual_retrieval_full/parents.json"
    assert runner.CHROMA_PATH == runner.LEVEL3 / "data/contextual_retrieval_full/chroma"


def test_preflight_failure_never_loads_embedding_model(monkeypatch):
    monkeypatch.setattr(runner, "load_cases", Mock(return_value=[CASE] * 20))
    monkeypatch.setattr(runner, "load_stores", Mock(side_effect=ValueError("missing")))
    embedding_loader = Mock()
    monkeypatch.setattr(runner, "load_embedding_service", embedding_loader)
    with pytest.raises(ValueError, match="missing"):
        runner.main([])
    embedding_loader.assert_not_called()
