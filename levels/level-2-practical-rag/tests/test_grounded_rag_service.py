from services.context_builder import ContextBuilder
from services.grounded_rag_service import GroundedRAGService

import pytest


@pytest.mark.parametrize(
    "results",
    [
        {"documents": [[]]},
        {"documents": [["", "   \n"]]},
    ],
)
def test_empty_built_context_returns_fallback_without_calling_llm(results):
    class FakeLLM:
        def generate(self, prompt):
            raise AssertionError("LLM should not be called")

    service = GroundedRAGService(
        context_builder=ContextBuilder(),
        llm_service=FakeLLM(),
    )

    answer = service.answer(
        question="What is the bonus policy?",
        results=results,
    )

    assert answer == "I don't have enough information to answer that question."



def test_empty_context_returns_fallback_without_calling_llm():
    class FakeLLM:
        def generate(self, prompt):
            raise AssertionError("LLM should not be called")

    class FakeContextBuilder:
        def build(self, results):
            return ""

    service = GroundedRAGService(
        context_builder=FakeContextBuilder(),
        llm_service=FakeLLM(),
    )

    answer = service.answer(
        question="What is the bonus policy?",
        results={"documents": [[]]},
    )

    assert answer == "I don't have enough information to answer that question."


def test_available_context_is_sent_to_llm():
    class FakeLLM:
        def generate(self, prompt):
            assert "20 days of annual leave" in prompt
            assert "What is the annual leave allowance?" in prompt
            return "Employees receive 20 days of annual leave."

    class FakeContextBuilder:
        def build(self, results):
            return "Employees receive 20 days of annual leave."

    service = GroundedRAGService(
        context_builder=FakeContextBuilder(),
        llm_service=FakeLLM(),
    )

    answer = service.answer(
        question="What is the annual leave allowance?",
        results={"documents": [["unused test document"]]},
    )

    assert answer == "Employees receive 20 days of annual leave."


def test_whitespace_only_context_returns_fallback_without_calling_llm():
    class FakeLLM:
        def generate(self, prompt):
            raise AssertionError("LLM should not be called")

    class FakeContextBuilder:
        def build(self, results):
            return "   \n  "

    service = GroundedRAGService(
        context_builder=FakeContextBuilder(),
        llm_service=FakeLLM(),
    )

    answer = service.answer(
        question="What is the bonus policy?",
        results={"documents": [[]]},
    )

    assert answer == "I don't have enough information to answer that question."
