import pytest

from services.long_context_builder import LongContextBuilder


def fake_token_counter(text: str) -> int:
    """Deterministic counter for unit tests."""
    return len(text.split())


def test_build_includes_documents_within_token_budget():
    builder = LongContextBuilder(
        max_tokens=100,
        token_counter=fake_token_counter,
    )

    documents = [
        {
            "document": "Remote work is allowed",
            "metadata": {"source": "handbook.pdf", "page_number": 2},
        },
        {
            "document": "Manager approval is required",
            "metadata": {"source": "handbook.pdf", "page_number": 3},
        },
    ]

    result = builder.build(documents)

    assert result.included_documents == 2
    assert result.skipped_documents == 0
    assert result.estimated_tokens == fake_token_counter(result.context)


def test_build_preserves_source_and_page_citations():
    builder = LongContextBuilder(
        max_tokens=100,
        token_counter=fake_token_counter,
    )

    result = builder.build(
        [
            {
                "document": "Employees can work remotely.",
                "metadata": {"source": "handbook.pdf", "page_number": 4},
            }
        ]
    )

    assert "Source: handbook.pdf" in result.context
    assert "Page: 4" in result.context


def test_build_skips_duplicate_documents():
    builder = LongContextBuilder(
        max_tokens=100,
        token_counter=fake_token_counter,
    )

    documents = [
        {"document": "Remote work policy", "metadata": {}},
        {"document": "Remote work policy", "metadata": {}},
    ]

    result = builder.build(documents)

    assert result.included_documents == 1
    assert result.skipped_documents == 1


def test_build_skips_empty_documents():
    builder = LongContextBuilder(
        max_tokens=100,
        token_counter=fake_token_counter,
    )

    result = builder.build(
        [
            {"document": "", "metadata": {}},
            {"document": "   ", "metadata": {}},
            {"document": "Valid document", "metadata": {}},
        ]
    )

    assert result.included_documents == 1
    assert result.skipped_documents == 2


def test_build_returns_empty_context_for_no_documents():
    builder = LongContextBuilder(
        max_tokens=100,
        token_counter=fake_token_counter,
    )

    result = builder.build([])

    assert result.context == ""
    assert result.included_documents == 0
    assert result.skipped_documents == 0
    assert result.estimated_words == 0
    assert result.estimated_tokens == 0


@pytest.mark.parametrize("max_tokens", [0, -1])
def test_builder_rejects_invalid_token_budget(max_tokens):
    with pytest.raises(ValueError, match="max_tokens"):
        LongContextBuilder(max_tokens=max_tokens)


def test_build_skips_oversized_document_and_includes_later_smaller_one():
    builder = LongContextBuilder(
        max_tokens=7,
        token_counter=fake_token_counter,
    )

    documents = [
        {
            "document": "This document has six words total",
            "metadata": {"source": "large.pdf"},
        },
        {
            "document": "Small document fits",
            "metadata": {"source": "small.pdf"},
        },
    ]

    result = builder.build(documents)

    assert result.included_documents == 1
    assert result.skipped_documents == 1
    assert "Small document fits" in result.context
    assert "This document has six words total" not in result.context
    assert result.estimated_tokens == fake_token_counter(result.context)


def test_actual_tokenizer_counts_tokens():
    builder = LongContextBuilder()

    count = builder.token_counter("Remote work requires manager approval.")

    assert count > 0


def test_token_budget_includes_citation_text():
    builder = LongContextBuilder(
        max_tokens=3,
        token_counter=fake_token_counter,
    )

    result = builder.build(
        [
            {
                "document": "Remote work allowed",
                "metadata": {"source": "handbook.pdf"},
            }
        ]
    )

    # Citation plus document exceeds the three-token test budget.
    assert result.included_documents == 0
    assert result.skipped_documents == 1
    assert result.context == ""
    assert result.estimated_tokens == 0

def test_build_handles_invalid_metadata():
    builder = LongContextBuilder(
        max_tokens=100,
        token_counter=fake_token_counter,
    )

    result = builder.build([
        {"document": "Remote work policy", "metadata": ["invalid"]},
    ])

    assert result.included_documents == 1
    assert "Source: Unknown source" in result.context
