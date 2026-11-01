import pytest
from pydantic import ValidationError
from app.schemas.embedding import EmbeddingRequest


def test_accepts_valid_input():
    request = EmbeddingRequest(text="Hello")

    assert request.text == "Hello"

def test_rejects_empty_text():
    with pytest.raises(ValidationError):
        EmbeddingRequest(text="")

def test_rejects_more_than_2000_characters():
    data = {"text": "a"*2001}
    with pytest.raises(ValidationError):
        EmbeddingRequest(text=data['text'])

def test_accepts_boundary_of_2000_characters():
    request = EmbeddingRequest(text="a"*2000)

    assert len(request.text) == 2000