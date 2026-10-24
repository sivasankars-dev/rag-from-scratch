import pytest
from services.agentic_rag import (
    INSUFFICIENT_EVIDENCE,
    AgenticRAGService,
)


class FakeRetriever:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def retrieve(self, query, top_k=3):
        self.calls.append({"query": query, "top_k": top_k})
        index = len(self.calls) - 1

        if index >= len(self.responses):
            return []

        return self.responses[index]


class FakeLLMClient:
    def __init__(self, responses):
        self.responses = responses
        self.prompts = []

    def generate(self, prompt):
        self.prompts.append(prompt)
        index = len(self.prompts) - 1

        if index >= len(self.responses):
            raise AssertionError(
                "Unexpected LLM call: no fake response was configured."
            )

        return self.responses[index]


def test_relevant_first_retrieval_generates_answer_without_retry():
    retriever = FakeRetriever([
        [{
            "text": "Full-time employees receive 20 annual leave days.",
            "metadata": {
                "source": "handbook.pdf",
                "section_title": "Annual Leave",
                "section_path": "Leave and Time Off > Annual Leave",
                "page_number": 4,
            },
        }]
    ])
    llm = FakeLLMClient([
        "YES",
        "Full-time employees generally receive 20 annual leave days.",
    ])

    service = AgenticRAGService(retriever, llm)
    result = service.run("How many annual leave days are provided?")

    assert result["status"] == "answered"
    assert result["retrieval_attempts"] == 1
    assert len(retriever.calls) == 1
    assert result["answer"].startswith("Full-time employees")
    assert len(result["queries"]) == 1
    assert "Annual Leave" in llm.prompts[-1]
    assert "page=4" in llm.prompts[-1]


def test_irrelevant_first_result_triggers_query_refinement_and_retry():
    retriever = FakeRetriever([
        [{
            "text": "The company maintains office access badges.",
            "metadata": {"section_title": "Office Access"},
        }],
        [{
            "text": (
                "Remote employees must protect company information. "
                "Company equipment must not be left unattended in public places."
            ),
            "metadata": {
                "section_title": "Remote Work",
                "section_path": "Working Hours > Remote Work",
            },
        }],
    ])
    llm = FakeLLMClient([
        "NO",
        "remote work equipment safety precautions",
        "YES",
        "Remote employees must protect company information and "
        "must not leave equipment unattended in public places.",
    ])

    service = AgenticRAGService(
        retriever,
        llm,
        top_k=3,
        max_attempts=2,
    )
    result = service.run(
        "What should remote employees do to protect company equipment?"
    )

    assert result["status"] == "answered"
    assert result["retrieval_attempts"] == 2
    assert len(retriever.calls) == 2
    assert retriever.calls[1]["query"] == (
        "remote work equipment safety precautions"
    )
    assert result["queries"] == [
        "What should remote employees do to protect company equipment?",
        "remote work equipment safety precautions",
    ]
    assert "Remote Work" in llm.prompts[-1]


def test_empty_results_stop_after_maximum_attempts_without_hallucinating():
    retriever = FakeRetriever([[], []])
    llm = FakeLLMClient([
        "remote laptop equipment policy",
    ])

    service = AgenticRAGService(
        retriever,
        llm,
        max_attempts=2,
    )
    result = service.run("What is the remote-work equipment policy?")

    assert result["status"] == "insufficient_evidence"
    assert result["answer"] == INSUFFICIENT_EVIDENCE
    assert result["retrieval_attempts"] == 2
    assert len(retriever.calls) == 2
    assert len(result["queries"]) == 2

    # Only the rewrite call should occur. Empty results are not graded,
    # and the workflow must not ask the LLM to invent an answer.
    assert len(llm.prompts) == 1
    assert "TASK: QUERY_REWRITE" in llm.prompts[0]


def test_empty_question_is_rejected():
    service = AgenticRAGService(
        FakeRetriever([]),
        FakeLLMClient([]),
    )

    with pytest.raises(ValueError, match="question"):
        service.run("   ")


@pytest.mark.parametrize(
    "top_k, max_attempts",
    [
        (0, 2),
        (3, 0),
        (-1, 2),
        (3, -1),
    ],
)
def test_invalid_configuration_is_rejected(top_k, max_attempts):
    with pytest.raises(ValueError):
        AgenticRAGService(
            FakeRetriever([]),
            FakeLLMClient([]),
            top_k=top_k,
            max_attempts=max_attempts,
        )


def test_refined_query_removes_web_search_syntax():
    retriever = FakeRetriever([[], []])
    llm = FakeLLMClient([
        '"cafeteria menu" "next Friday" '
        'site:sharepoint.com OR site:company.com',
    ])

    service = AgenticRAGService(
        retriever,
        llm,
        max_attempts=2,
    )
    result = service.run(
        "What is the company cafeteria menu for next Friday?"
    )

    assert result["retrieval_attempts"] == 2
    assert result["queries"][1] == "cafeteria menu next Friday"
    assert result["status"] == "insufficient_evidence"
