import pytest

from services.graph_rag_service import (
    INSUFFICIENT_EVIDENCE,
    GraphRAGService,
)


class FakeGraphRetriever:
    def __init__(self, results):
        self.results = results
        self.calls = []

    def retrieve(self, question, top_k=5, max_hops=1):
        self.calls.append({
            "question": question,
            "top_k": top_k,
            "max_hops": max_hops,
        })
        return self.results


class FakeLLMClient:
    def __init__(self, response="The answer is supported by the evidence."):
        self.response = response
        self.prompts = []

    def generate(self, prompt):
        self.prompts.append(prompt)
        return self.response


@pytest.fixture
def graph_evidence():
    return [{
        "source_entity": "Company Equipment",
        "relationship": "MUST_NOT_BE_LEFT_UNATTENDED_IN",
        "target_entity": "Public Location",
        "evidence": (
            "Company equipment must not be left unattended "
            "in public locations."
        ),
        "source": "rag_practice_employee_handbook.pdf",
        "section_path": (
            "Working Hours, Attendance, and Remote Work > Remote Work"
        ),
        "start_page": 3,
        "end_page": 3,
    }]


def test_generates_answer_from_graph_evidence(graph_evidence):
    retriever = FakeGraphRetriever(graph_evidence)
    llm = FakeLLMClient(
        "Company equipment must not be left unattended in public "
        "locations (rag_practice_employee_handbook.pdf, page 3)."
    )

    service = GraphRAGService(retriever, llm)
    result = service.run(
        "Where should employees not leave company equipment?"
    )

    assert result["status"] == "answered"
    assert "public locations" in result["answer"].lower()
    assert len(result["evidence"]) == 1
    assert "page=3" not in result["answer"]  # Citation uses the readable page format.
    assert "page 3" in result["answer"]
    assert len(llm.prompts) == 1
    assert "Company equipment must not be left unattended" in llm.prompts[0]
    assert "Remote Work" in llm.prompts[0]


def test_no_graph_evidence_returns_fallback_without_llm_call():
    retriever = FakeGraphRetriever([])
    llm = FakeLLMClient()

    service = GraphRAGService(retriever, llm)
    result = service.run("What is the cafeteria menu?")

    assert result["status"] == "insufficient_evidence"
    assert result["answer"] == INSUFFICIENT_EVIDENCE
    assert result["evidence"] == []
    assert llm.prompts == []


def test_empty_question_is_rejected():
    service = GraphRAGService(
        FakeGraphRetriever([]),
        FakeLLMClient(),
    )

    with pytest.raises(ValueError, match="question"):
        service.run("  ")


@pytest.mark.parametrize(
    "top_k, max_hops",
    [
        (0, 1),
        (3, 0),
        (3, 4),
    ],
)
def test_invalid_configuration_is_rejected(top_k, max_hops):
    with pytest.raises(ValueError):
        GraphRAGService(
            FakeGraphRetriever([]),
            FakeLLMClient(),
            top_k=top_k,
            max_hops=max_hops,
        )


def test_empty_llm_answer_returns_insufficient_evidence(graph_evidence):
    retriever = FakeGraphRetriever(graph_evidence)
    llm = FakeLLMClient("  ")

    service = GraphRAGService(retriever, llm)
    result = service.run("Where should equipment not be left?")

    assert result["status"] == "insufficient_evidence"
    assert result["answer"] == INSUFFICIENT_EVIDENCE
    assert len(result["evidence"]) == 1
