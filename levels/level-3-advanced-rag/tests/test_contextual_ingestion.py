import json

import pytest

from services.contextual_ingestion import (
    build_contextual_record,
    embed_contextual_records,
    prepare_contextual_chunk,
    save_contextual_manifest,
    store_contextual_records,
)


class FakeContextGenerator:
    def generate_context(
        self, document_text, page_number, original_chunk
    ):
        assert document_text == "Full employee handbook."
        assert page_number == 2
        assert original_chunk == "Employees receive 20 annual leave days."

        return "This section explains annual leave policy."


class FakeEmbeddingService:
    def __init__(self):
        self.received_texts = None

    def embed_texts(self, texts):
        self.received_texts = texts
        return [[0.1, 0.2], [0.3, 0.4]]


class IncorrectEmbeddingService:
    def embed_texts(self, texts):
        return []


class RecordingContextGenerator:
    def __init__(self):
        self.calls = []

    def generate_context(
        self, document_text, page_number, original_chunk
    ):
        self.calls.append(
            {
                "document_text": document_text,
                "page_number": page_number,
                "original_chunk": original_chunk,
            }
        )
        return "Generated policy context."


class FakeParentStore:
    def __init__(self):
        self.parents = []

    def store_parent(self, parent):
        self.parents.append(parent)


class FakeChildStore:
    def __init__(self):
        self.children = []
        self.embeddings = None

    def store_children(self, children, embeddings):
        self.children = children
        self.embeddings = embeddings
        
class FailingChildStore:
    def store_children(self, children, embeddings):
        raise RuntimeError("Simulated Chroma write failure")


def make_parent(
    parent_id="parent_1",
    text="Employees receive 20 annual leave days. Leave requests need approval.",
    source="employee_handbook.pdf",
    page_number=2,
):
    return {
        "parent_id": parent_id,
        "text": text,
        "source": source,
        "page_number": page_number,
    }


def make_child(
    child_id="child_1",
    parent_id="parent_1",
    text="Employees receive 20 annual leave days.",
    source="employee_handbook.pdf",
    page_number=2,
):
    return {
        "child_id": child_id,
        "parent_id": parent_id,
        "text": text,
        "source": source,
        "page_number": page_number,
    }


def make_contextual_record(
    child_id,
    original_text,
    parent_text="Parent policy text.",
    parent_id="parent_1",
    source="employee_handbook.pdf",
    page_number=2,
):
    context = "Annual leave policy."
    return {
        "child_id": child_id,
        "parent_id": parent_id,
        "original_text": original_text,
        "context": context,
        "retrieval_text": f"{context}\n\n{original_text}",
        "parent_text": parent_text,
        "source": source,
        "page_number": page_number,
    }


def test_prepare_contextual_chunk_preserves_separate_text_and_context():
    result = prepare_contextual_chunk(
        original_text="Employees receive 20 annual leave days.",
        context="This section explains annual leave.",
    )

    assert result == {
        "original_text": "Employees receive 20 annual leave days.",
        "context": "This section explains annual leave.",
        "retrieval_text": (
            "This section explains annual leave.\n\n"
            "Employees receive 20 annual leave days."
        ),
    }


def test_trims_outer_whitespace_but_preserves_internal_formatting():
    result = prepare_contextual_chunk(
        original_text=" \tFirst  line.\nSecond line.\n ",
        context="\n Policy\tcontext.  ",
    )

    assert result == {
        "original_text": "First  line.\nSecond line.",
        "context": "Policy\tcontext.",
        "retrieval_text": "Policy\tcontext.\n\nFirst  line.\nSecond line.",
    }


@pytest.mark.parametrize("field", ["original_text", "context"])
@pytest.mark.parametrize(
    "value",
    [None, 0, False, [], {}, b"text", "", " \t\n"],
)
def test_rejects_invalid_or_blank_values(field, value):
    arguments = {
        "original_text": "Original text.",
        "context": "Context.",
    }
    arguments[field] = value

    with pytest.raises(
        ValueError,
        match=f"{field} must be a non-empty string",
    ):
        prepare_contextual_chunk(**arguments)


def test_build_contextual_record_preserves_text_and_metadata():
    parent = make_parent()
    child = make_child()
    generator = FakeContextGenerator()

    record = build_contextual_record(
        document_text="Full employee handbook.",
        child=child,
        context_generator=generator,
        parent=parent,
    )

    assert record["parent_text"] == parent["text"]
    assert record["parent_id"] == parent["parent_id"]
    assert record["original_text"] == child["text"]
    assert record["context"] == "This section explains annual leave policy."
    assert record["retrieval_text"] == (
        "This section explains annual leave policy.\n\n"
        "Employees receive 20 annual leave days."
    )
    assert record["child_id"] == "child_1"
    assert record["source"] == "employee_handbook.pdf"
    assert record["page_number"] == 2


def test_build_contextual_record_rejects_mismatched_parent_id():
    parent = make_parent(parent_id="parent_1")
    child = make_child(parent_id="parent_2")
    generator = RecordingContextGenerator()

    with pytest.raises(ValueError, match="IDs do not match"):
        build_contextual_record(
            document_text="Full employee handbook.",
            child=child,
            context_generator=generator,
            parent=parent,
        )

    assert generator.calls == []


def test_build_contextual_record_rejects_mismatched_source():
    parent = make_parent(source="employee_handbook.pdf")
    child = make_child(source="another_document.pdf")
    generator = RecordingContextGenerator()

    with pytest.raises(ValueError, match="source"):
        build_contextual_record(
            document_text="Full employee handbook.",
            child=child,
            context_generator=generator,
            parent=parent,
        )

    assert generator.calls == []


def test_build_contextual_record_rejects_mismatched_page():
    parent = make_parent(page_number=3)
    child = make_child(page_number=2)
    generator = RecordingContextGenerator()

    with pytest.raises(ValueError, match="page"):
        build_contextual_record(
            document_text="Full employee handbook.",
            child=child,
            context_generator=generator,
            parent=parent,
        )

    assert generator.calls == []


def test_embeds_retrieval_text_not_original_text():
    records = [
        {
            "original_text": "20 annual leave days.",
            "retrieval_text": "Annual leave policy.\n\n20 annual leave days.",
        },
        {
            "original_text": "Sick leave is available.",
            "retrieval_text": "Sick leave policy.\n\nSick leave is available.",
        },
    ]
    embedding_service = FakeEmbeddingService()

    embeddings = embed_contextual_records(records, embedding_service)

    assert embedding_service.received_texts == [
        record["retrieval_text"] for record in records
    ]
    assert len(embeddings) == len(records)
    assert records[0]["original_text"] == "20 annual leave days."


def test_empty_records_return_empty_embeddings():
    embedding_service = FakeEmbeddingService()

    assert embed_contextual_records([], embedding_service) == []
    assert embedding_service.received_texts is None


def test_rejects_missing_retrieval_text_before_embedding():
    embedding_service = FakeEmbeddingService()

    with pytest.raises(ValueError, match="retrieval_text"):
        embed_contextual_records(
            [{"original_text": "Some text"}],
            embedding_service,
        )

    assert embedding_service.received_texts is None


def test_rejects_embedding_count_mismatch():
    records = [{"retrieval_text": "Annual leave policy."}]

    with pytest.raises(ValueError, match="count must match"):
        embed_contextual_records(records, IncorrectEmbeddingService())


def test_saves_contextual_records_to_json(tmp_path):
    records = [
        {
            "child_id": "child_1",
            "parent_id": "parent_1",
            "original_text": "20 annual leave days.",
            "context": "Annual leave policy.",
            "retrieval_text": "Annual leave policy.\n\n20 annual leave days.",
            "source": "employee_handbook.pdf",
            "page_number": 2,
        }
    ]

    path = tmp_path / "contextual_chunks.json"
    count = save_contextual_manifest(records, path)
    saved = json.loads(path.read_text(encoding="utf-8"))

    assert count == 1
    assert saved["child_1"] == records[0]


def test_rejects_duplicate_child_ids(tmp_path):
    records = [
        {"child_id": "child_1"},
        {"child_id": "child_1"},
    ]

    with pytest.raises(ValueError, match="Duplicate child_id"):
        save_contextual_manifest(records, tmp_path / "manifest.json")


def test_empty_manifest_is_saved(tmp_path):
    path = tmp_path / "contextual_chunks.json"

    count = save_contextual_manifest([], path)

    assert count == 0
    assert json.loads(path.read_text(encoding="utf-8")) == {}


def test_store_contextual_records_rejects_missing_parent_text(tmp_path):
    record = make_contextual_record(
        child_id="child_1",
        original_text="Child text.",
    )
    del record["parent_text"]

    parent_store = FakeParentStore()
    child_store = FakeChildStore()
    manifest_path = tmp_path / "manifest.json"

    with pytest.raises(ValueError, match="parent_text"):
        store_contextual_records(
            records=[record],
            embeddings=[[0.1, 0.2]],
            parent_store=parent_store,
            child_vector_store=child_store,
            manifest_path=manifest_path,
        )

    assert parent_store.parents == []
    assert child_store.children == []
    assert not manifest_path.exists()


def test_store_contextual_records_rejects_conflicting_parent_text(tmp_path):
    records = [
        make_contextual_record(
            child_id="child_1",
            original_text="First child.",
            parent_text="First parent text.",
        ),
        make_contextual_record(
            child_id="child_2",
            original_text="Second child.",
            parent_text="Different parent text.",
        ),
    ]

    parent_store = FakeParentStore()
    child_store = FakeChildStore()
    manifest_path = tmp_path / "manifest.json"

    with pytest.raises(ValueError, match="(?i)conflicting parent"):
        store_contextual_records(
            records=records,
            embeddings=[[0.1, 0.2], [0.3, 0.4]],
            parent_store=parent_store,
            child_vector_store=child_store,
            manifest_path=manifest_path,
        )

    assert parent_store.parents == []
    assert child_store.children == []
    assert not manifest_path.exists()

def test_child_store_failure_can_leave_partial_persistence(tmp_path):
    record = make_contextual_record(
        child_id="child_1",
        original_text="Child text.",
        parent_text="Parent policy text.",
    )

    parent_store = FakeParentStore()
    child_store = FailingChildStore()
    manifest_path = tmp_path / "manifest.json"

    with pytest.raises(RuntimeError, match="Simulated Chroma write failure"):
        store_contextual_records(
            records=[record],
            embeddings=[[0.1, 0.2]],
            parent_store=parent_store,
            child_vector_store=child_store,
            manifest_path=manifest_path,
        )

    # These assertions document the current partial-write behaviour.
    assert manifest_path.exists()
    assert len(parent_store.parents) == 1