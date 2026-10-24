import json

import pytest

from services.graph_extractor import GraphExtractor


class FakeLLMClient:
    def __init__(self, response):
        self.response = response
        self.calls = 0

    def generate(self, prompt):
        self.calls += 1
        return self.response


def test_extracts_entities_and_grounded_relationships():
    source = "Employees submit leave requests through the HR system."

    response = {
        "entities": [
            {"name": "Employees", "type": "ROLE"},
            {"name": "Leave Requests", "type": "PROCESS"},
            {"name": "HR System", "type": "SYSTEM"},
        ],
        "relationships": [
            {
                "source": "Employees",
                "predicate": "SUBMITS",
                "target": "Leave Requests",
                "evidence": "Employees submit leave requests",
            },
            {
                "source": "Leave Requests",
                "predicate": "SUBMITTED THROUGH",
                "target": "HR System",
                "evidence": "through the HR system",
            },
        ],
    }

    llm = FakeLLMClient(json.dumps(response))
    result = GraphExtractor(llm).extract(
        source,
        metadata={"section_title": "Leave Requests"},
    )

    assert len(result["entities"]) == 3
    assert len(result["relationships"]) == 2
    assert result["relationships"][0]["predicate"] == "SUBMITS"
    assert result["relationships"][1]["predicate"] == "SUBMITTED_THROUGH"
    assert result["metadata"]["section_title"] == "Leave Requests"
    assert llm.calls == 1


def test_accepts_json_inside_markdown_fence():
    llm = FakeLLMClient(
        '```json\n{"entities": [], "relationships": []}\n```'
    )

    result = GraphExtractor(llm).extract("Some source text.")

    assert result["entities"] == []
    assert result["relationships"] == []


def test_empty_source_does_not_call_llm():
    llm = FakeLLMClient("should not be called")

    result = GraphExtractor(llm).extract("   ")

    assert result["entities"] == []
    assert result["relationships"] == []
    assert llm.calls == 0


def test_rejects_invalid_json():
    llm = FakeLLMClient("not valid JSON")

    with pytest.raises(ValueError, match="valid JSON"):
        GraphExtractor(llm).extract("Employees submit leave requests.")


def test_rejects_relationship_with_unknown_entity():
    llm = FakeLLMClient(json.dumps({
        "entities": [{"name": "Employee", "type": "ROLE"}],
        "relationships": [{
            "source": "Employee",
            "predicate": "USES",
            "target": "HR System",
            "evidence": "Employee uses the HR system",
        }],
    }))

    with pytest.raises(ValueError, match="target is not a known entity"):
        GraphExtractor(llm).extract(
            "Employee uses the HR system."
        )


def test_rejects_unsupported_relationship_evidence():
    llm = FakeLLMClient(json.dumps({
        "entities": [
            {"name": "Employee", "type": "ROLE"},
            {"name": "HR System", "type": "SYSTEM"},
        ],
        "relationships": [{
            "source": "Employee",
            "predicate": "USES",
            "target": "HR System",
            "evidence": "The employee has administrator access.",
        }],
    }))

    with pytest.raises(ValueError, match="not found in source text"):
        GraphExtractor(llm).extract(
            "Employee uses the HR system."
        )


def test_duplicate_entities_and_relationships_are_deduplicated():
    llm = FakeLLMClient(json.dumps({
        "entities": [
            {"name": "Employee", "type": "ROLE"},
            {"name": " employee ", "type": "ROLE"},
            {"name": "HR System", "type": "SYSTEM"},
        ],
        "relationships": [
            {
                "source": "Employee",
                "predicate": "USES",
                "target": "HR System",
                "evidence": "Employee uses the HR system",
            },
            {
                "source": "employee",
                "predicate": "uses",
                "target": "hr system",
                "evidence": "Employee uses the HR system",
            },
        ],
    }))

    result = GraphExtractor(llm).extract(
        "Employee uses the HR system."
    )

    assert len(result["entities"]) == 2
    assert len(result["relationships"]) == 1


def test_rejects_unknown_entity_types():
    llm = FakeLLMClient(json.dumps({
        "entities": [{"name": "Employee", "type": "MAGICAL_ROLE"}],
        "relationships": [],
    }))

    with pytest.raises(ValueError, match="Unsupported entity type"):
        GraphExtractor(llm).extract("Employee works here.")
