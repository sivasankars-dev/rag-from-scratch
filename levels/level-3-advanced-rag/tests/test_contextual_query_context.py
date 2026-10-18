
import pytest

from services.contextual_query_context import ContextualQueryContext


class FakeLLMClient:
    def __init__(self, response="This section explains the annual leave policy."):
        self.response = response
        self.last_prompt = None

    def generate(self, prompt):
        self.last_prompt = prompt
        return self.response


def test_generate_context_returns_llm_response():
    client = FakeLLMClient()
    service = ContextualQueryContext(client)

    context = service.generate_context(
        document_text="Full-time employees receive 20 annual leave days.",
        page_number=2,
        original_chunk="Employees receive 20 annual leave days.",
    )

    assert context == "This section explains the annual leave policy."
    assert "20 annual leave days" in client.last_prompt
    assert "CHUNK PAGE" in client.last_prompt


def test_original_chunk_is_not_modified():
    client = FakeLLMClient()
    service = ContextualQueryContext(client)
    original_chunk = "Employees receive 20 annual leave days."

    service.generate_context(
        document_text="Full-time employees receive 20 annual leave days.",
        page_number=2,
        original_chunk=original_chunk,
    )

    assert original_chunk == "Employees receive 20 annual leave days."


@pytest.mark.parametrize(
    ("document_text", "original_chunk", "page_number"),
    [
        ("", "Some chunk", 1),
        ("Some document", "", 1),
        ("Some document", "Some chunk", 0),
    ],
)
def test_invalid_input_is_rejected(document_text, original_chunk, page_number):
    service = ContextualQueryContext(FakeLLMClient())

    with pytest.raises(ValueError):
        service.generate_context(
            document_text=document_text,
            page_number=page_number,
            original_chunk=original_chunk,
        )


def test_empty_llm_response_is_rejected():
    service = ContextualQueryContext(FakeLLMClient(response=""))

    with pytest.raises(ValueError, match="empty or invalid"):
        service.generate_context(
            document_text="A company policy document.",
            page_number=1,
            original_chunk="A policy statement.",
        )


def test_oversized_document_is_rejected():
    service = ContextualQueryContext(
        FakeLLMClient(),
        max_document_chars=10,
    )

    with pytest.raises(ValueError, match="character limit"):
        service.generate_context(
            document_text="This document is too long.",
            page_number=1,
            original_chunk="A chunk.",
        )


def test_oversized_generated_context_is_rejected():
    service = ContextualQueryContext(
        FakeLLMClient(response="x" * 20),
        max_context_chars=10,
    )

    with pytest.raises(ValueError, match="character limit"):
        service.generate_context(
            document_text="A short document.",
            page_number=1,
            original_chunk="A short chunk.",
        )

def test_prompt_prioritizes_specific_topic_and_key_procedures():
    client = FakeLLMClient()
    service = ContextualQueryContext(client)

    service.generate_context(
        document_text=(
            "Section 3.4 Leave Approval. Planned leave should normally "
            "be submitted through the approved leave system."
        ),
        page_number=4,
        original_chunk=(
            "Planned leave should normally be submitted "
            "through the approved leave system."
        ),
    )

    prompt = client.last_prompt.lower()

    assert "specific topic" in prompt
    assert "procedures" in prompt
    assert "do not invent facts" in prompt
    assert "section number" in prompt
