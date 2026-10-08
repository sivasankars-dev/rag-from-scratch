import pytest
from services.llm_client import OpenAILLMClient
from services.query_rewriter import rewrite_query


class FakeResponses:
    def create(self, model, input):
        return type(
            "FakeResponse",
            (),
            {"output_text": "Rewritten query"},
        )()


class FakeOpenAI:
    def __init__(self):
        self.responses = FakeResponses()


def test_openai_llm_client_requires_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(ValueError, match="OPENAI_API_KEY is not set"):
        OpenAILLMClient()


def test_generate_returns_llm_response(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    llm = OpenAILLMClient()
    llm.client = FakeOpenAI()

    result = llm.generate("How many leave days can I take?")

    assert result == "Rewritten query"
    
def test_query_rewriter_works_with_llm_client(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    llm = OpenAILLMClient()

    class FakeResponses:
        def create(self, model, input):
            return type(
                "FakeResponse",
                (),
                {
                    "output_text": (
                        "How many annual leave days can an employee take?"
                    )
                },
            )()

    llm.client.responses = FakeResponses()

    result = rewrite_query(
        "How many days can I take?",
        conversation_context="User is asking about annual leave.",
        llm_client=llm,
    )

    assert result == "How many annual leave days can an employee take?"