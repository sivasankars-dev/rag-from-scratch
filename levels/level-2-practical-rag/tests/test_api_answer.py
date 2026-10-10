import pytest
from fastapi.testclient import TestClient
from unittest.mock import Mock
from app.main import app
from app.routers.answer import AnswerRequest, AnswerResponse
from pydantic import ValidationError
from app.dependencies import (
    get_embedding_service,
    get_grounded_rag_service,
    get_retrieval_service,
)

def test_answer_request_requires_question():
    with pytest.raises(ValidationError):
        AnswerRequest()


def test_answer_request_rejects_empty_question():
    with pytest.raises(ValidationError):
        AnswerRequest(question="")

def test_answer_response_contains_answer_and_citations():
    response = AnswerResponse(
        answer="Annual leave is 12 days.",
        citations=[
            "Source: company_policy.pdf, Page: 1, Chunk: 0"
        ],
    )

    assert response.answer == "Annual leave is 12 days."
    assert len(response.citations) == 1

def test_answer_endpoint_is_registered():
    override_answer_dependencies()

    try:
        response = TestClient(app).post(
            "/answer",
            json={"question": "What is the leave policy?"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {
        "answer": "I don't have enough information to answer that question.",
        "citations": [],
    }

def test_answer_endpoint_uses_embedding_dependency():
    mock_embedding_service, _, _ = override_answer_dependencies()

    try:
        response = TestClient(app).post(
            "/answer",
            json={"question": "What is the leave policy?"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    mock_embedding_service.embed_text.assert_called_once_with(
        "What is the leave policy?"
    )

def test_answer_endpoint_uses_retrieval_dependency():
    _, mock_retrieval_service, _ = override_answer_dependencies()

    try:
        response = TestClient(app).post(
            "/answer",
            json={"question": "How many annual leave days?"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    mock_retrieval_service.retrieve.assert_called_once_with(
        query_embedding=[0.1, 0.2, 0.3],
    )

def test_answer_endpoint_uses_grounded_rag_dependency():
    _, mock_retrieval_service, mock_grounded_rag_service = (
        override_answer_dependencies()
    )

    retrieval_results = {
        "documents": [["Annual leave is 12 days."]],
        "metadatas": [[
            {
                "source": "company_policy.pdf",
                "page_number": 1,
                "chunk_index": 0,
            }
        ]],
        "distances": [[0.1]],
    }

    mock_retrieval_service.retrieve.return_value = retrieval_results
    mock_grounded_rag_service.answer.return_value = {
        "answer": "Annual leave is 12 days.",
        "citations": [
            "Source: company_policy.pdf, Page: 1, Chunk: 0"
        ],
    }

    try:
        response = TestClient(app).post(
            "/answer",
            json={"question": "How many annual leave days?"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    mock_grounded_rag_service.answer.assert_called_once_with(
        question="How many annual leave days?",
        results=retrieval_results,
    )
    assert response.json()["answer"] == "Annual leave is 12 days."

def override_answer_dependencies():
    mock_embedding_service = Mock()
    mock_embedding_service.embed_text.return_value = [0.1, 0.2, 0.3]

    mock_retrieval_service = Mock()
    mock_retrieval_service.retrieve.return_value = {
        "documents": [[]],
        "metadatas": [[]],
        "distances": [[]],
    }

    mock_grounded_rag_service = Mock()
    mock_grounded_rag_service.answer.return_value = {
        "answer": "I don't have enough information to answer that question.",
        "citations": [],
    }

    app.dependency_overrides[get_embedding_service] = (
        lambda: mock_embedding_service
    )
    app.dependency_overrides[get_retrieval_service] = (
        lambda: mock_retrieval_service
    )
    app.dependency_overrides[get_grounded_rag_service] = (
        lambda: mock_grounded_rag_service
    )

    return (
        mock_embedding_service,
        mock_retrieval_service,
        mock_grounded_rag_service,
    )
