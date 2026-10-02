
import pytest

from services.overlap_chunker import chunk_text_with_overlap


def test_chunk_text_with_overlap():
    text = "A B C D E F G H I J"

    chunks = chunk_text_with_overlap(
        text,
        chunk_limit=5,
        overlap=2,
    )

    assert chunks == [
        "A B C D E",
        "D E F G H",
        "G H I J",
    ]


def test_chunk_text_without_overlap():
    text = "A B C D E F G H I J"

    chunks = chunk_text_with_overlap(
        text,
        chunk_limit=5,
        overlap=0,
    )

    assert chunks == [
        "A B C D E",
        "F G H I J",
    ]


def test_overlap_must_be_less_than_chunk_limit():
    with pytest.raises(ValueError):
        chunk_text_with_overlap(
            "A B C D E",
            chunk_limit=5,
            overlap=5,
        )

def test_chunk_text_with_multiple_paragraphs():
    text = "A B C D E F G H\n\nI J K L M N O P"

    chunks = chunk_text_with_overlap(
        text,
        chunk_limit=5,
        overlap=2,
    )

    assert chunks == [
        "A B C D E",
        "D E F G H",
        "G H I J K",
        "J K L M N",
        "M N O P",
    ]
    
def test_chunk_text_with_empty_input():
    assert chunk_text_with_overlap("", 5, 2) == []
    assert chunk_text_with_overlap("   ", 5, 2) == []
    
def test_chunk_text_exact_chunk_limit():
    text = "A B C D E"

    chunks = chunk_text_with_overlap(
        text,
        chunk_limit=5,
        overlap=2,
    )

    assert chunks == [
        "A B C D E",
    ]
    
def test_chunk_text_with_small_final_chunk():
    text = "A B C D E F G"

    chunks = chunk_text_with_overlap(
        text,
        chunk_limit=5,
        overlap=2,
    )

    assert chunks == [
        "A B C D E",
        "D E F G",
    ]
    
def test_chunks_respect_limit_and_overlap():
    text = "A B C D E F G H I J K L"

    chunks = chunk_text_with_overlap(
        text,
        chunk_limit=5,
        overlap=2,
    )

    for chunk in chunks:
        assert len(chunk.split()) <= 5

    for previous, current in zip(chunks, chunks[1:]):
        previous_words = previous.split()
        current_words = current.split()

        assert previous_words[-2:] == current_words[:2]
        
def test_chunk_text_with_one_word_overlap():
    text = "A B C D E F G H"

    chunks = chunk_text_with_overlap(
        text,
        chunk_limit=4,
        overlap=1,
    )

    assert chunks == [
        "A B C D",
        "D E F G",
        "G H",
    ]
    
def test_chunk_limit_must_be_positive():
    with pytest.raises(ValueError):
        chunk_text_with_overlap("A B C", chunk_limit=0, overlap=0)

    with pytest.raises(ValueError):
        chunk_text_with_overlap("A B C", chunk_limit=-1, overlap=0)


def test_overlap_cannot_be_negative():
    with pytest.raises(ValueError):
        chunk_text_with_overlap("A B C", chunk_limit=5, overlap=-1)


def test_overlap_must_be_smaller_than_chunk_limit():
    with pytest.raises(ValueError):
        chunk_text_with_overlap("A B C", chunk_limit=5, overlap=5)

    with pytest.raises(ValueError):
        chunk_text_with_overlap("A B C", chunk_limit=5, overlap=6)