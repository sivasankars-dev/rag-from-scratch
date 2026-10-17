"""Orchestration tests: no PDF access, model download, or embedding API."""
import importlib.util
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/run_parent_child_ingestion.py"
spec = importlib.util.spec_from_file_location("parent_child_ingestion", SCRIPT)
ingestion = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ingestion)


class FakeChildStore:
    def __init__(self):
        self.records = {}
        self.collection = self
        self.deletions = []

    def delete(self, where):
        self.deletions.append(where)
        self.records = {key: value for key, value in self.records.items()
                        if value["source"] != where["source"]}

    def get(self, where, include):
        return {"ids": [key for key, value in self.records.items()
                        if value["source"] == where["source"]]}

    def store_children(self, children, embeddings):
        assert len(children) == len(embeddings)
        self.records.update({child["child_id"]: child for child in children})


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(ingestion, "PARENT_PATH", tmp_path / "parents.json")
    monkeypatch.setattr(ingestion, "CHROMA_PATH", tmp_path / "chroma")
    store = FakeChildStore()
    factory = Mock(return_value=store)
    embedder = Mock()
    embedder.embed_texts.side_effect = lambda texts: [[1.0, 0.0] for _ in texts]
    return store, factory, Mock(return_value=embedder)


def run(pages, setup):
    _, factory, embeddings = setup
    loader = Mock(return_value=pages)
    counts = ingestion.ingest(loader, embeddings, child_factory=factory)
    loader.assert_called_once_with(ingestion.PDF_PATH)
    return counts


def test_pages_configuration_and_paths(setup, monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(tmp_path)
    counts = run([
        {"text": " ", "page_number": 1},
        {"text": " ".join(f"w{i}" for i in range(101)), "page_number": 2},
        {"text": "another page", "page_number": 4},
    ], setup)
    assert counts == {"pages": 3, "parents": 3, "children": 7}
    store, factory, embeddings = setup
    assert {c["page_number"] for c in store.records.values()} == {2, 4}
    assert {c["source"] for c in store.records.values()} == {ingestion.SOURCE}
    texts = embeddings.return_value.embed_texts.call_args.args[0]
    assert texts[0].split()[-10:] == texts[1].split()[:10]
    assert len(texts[0].split()) == 30
    assert ingestion.PDF_PATH == SCRIPT.parents[3] / "data/documents" / ingestion.SOURCE
    factory.assert_called_once_with(persist_directory=str(tmp_path / "chroma"),
                                    collection_name=ingestion.COLLECTION_NAME)
    assert "Persisted parents: 3" in capsys.readouterr().out


def test_reruns_remove_stale_records_and_preserve_other_source(setup):
    store, _, _ = setup
    other = {"parent_id": "other", "text": "keep", "source": "other.pdf"}
    ingestion.ParentChildStore(ingestion.PARENT_PATH).store_parent(other)
    store.records["other_child"] = {"source": "other.pdf"}
    # Simulate an older ID scheme alongside the new page-aware IDs.
    ingestion.ParentChildStore(ingestion.PARENT_PATH).store_parent(
        {"parent_id": "old_id", "source": ingestion.SOURCE})
    store.records["old_child"] = {"source": ingestion.SOURCE}
    run([{"text": "word " * 250, "page_number": 1}], setup)
    pages = [{"text": "short text", "page_number": 1}]
    run(pages, setup)
    before = dict(store.records)
    run(pages, setup)
    assert store.records == before
    assert len(store.records) == 2
    stored = json.loads(ingestion.PARENT_PATH.read_text())
    assert len(stored) == 2
    assert stored["other"] == other
    assert "old_id" not in stored and "old_child" not in store.records
    assert all(where == {"source": ingestion.SOURCE} for where in store.deletions)


@pytest.mark.parametrize("pages", [[], [{"text": "  ", "page_number": 1}],
                                    [{"text": None, "page_number": 2}]])
def test_empty_content_never_initializes_model_or_stores(setup, pages):
    _, factory, embeddings = setup
    with pytest.raises(ValueError, match="No nonempty"):
        run(pages, setup)
    factory.assert_not_called()
    embeddings.assert_not_called()
    assert not ingestion.PARENT_PATH.exists()


@pytest.mark.parametrize("failure", [RuntimeError("model failed"), []])
def test_embedding_failure_precedes_reset(setup, failure):
    store, factory, embeddings = setup
    ingestion.PARENT_PATH.write_text('{"old": {"source": "keep"}}')
    before = ingestion.PARENT_PATH.read_bytes()
    embeddings.return_value.embed_texts.side_effect = failure if isinstance(failure, Exception) else None
    embeddings.return_value.embed_texts.return_value = []
    with pytest.raises((RuntimeError, ValueError)):
        run([{"text": "some text", "page_number": 1}], setup)
    assert ingestion.PARENT_PATH.read_bytes() == before
    factory.assert_not_called()
    assert not store.deletions


def test_duplicate_page_ids_rejected_before_reset(setup):
    page = {"text": "text", "page_number": 1}
    with pytest.raises(ValueError, match="Duplicate parent"):
        run([page, page], setup)
    setup[2].assert_not_called()


def test_stored_count_mismatch_is_failure(setup):
    setup[0].store_children = Mock()
    with pytest.raises(RuntimeError, match="Stored child IDs/count"):
        run([{"text": "some text", "page_number": 1}], setup)


def test_main_uses_existing_level2_interfaces(monkeypatch):
    loader = Mock()
    embedding_module = Mock()
    modules = Mock(side_effect=[loader, embedding_module])
    monkeypatch.setattr(ingestion, "load_level2_module", modules)

    def fake_ingest(load_pages, embedding_factory):
        assert load_pages is loader.extract_text_from_pdf
        assert embedding_factory() is embedding_module.EmbeddingService.return_value

    monkeypatch.setattr(ingestion, "ingest", fake_ingest)
    ingestion.main()
    assert modules.call_args_list[0].args == (
        "level2_document_loader", "document_loader.py")
    assert modules.call_args_list[1].args == (
        "level2_embedding_service", "embedding_service.py")
