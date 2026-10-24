import pytest

from services.graph_retrieval import GraphRetriever


class FakeDriver:
    def __init__(self, entities, relationships):
        self.entities = entities
        self.relationships = relationships
        self.calls = []

    def execute_query(self, query, **kwargs):
        self.calls.append((query, kwargs))

        if "MATCH (entity:Entity)" in query:
            return self.entities, None, None

        return self.relationships, None, None


@pytest.fixture
def graph_entities():
    return [
        {
            "id": "role::remote employee",
            "name": "Remote Employee",
            "type": "ROLE",
        },
        {
            "id": "other::company equipment",
            "name": "Company Equipment",
            "type": "OTHER",
        },
        {
            "id": "policy::company information",
            "name": "Company Information",
            "type": "POLICY",
        },
    ]


@pytest.fixture
def graph_relationships():
    return [{
        "source_entity_id": "other::company equipment",
        "source_entity": "Company Equipment",
        "relationship": "MUST_NOT_BE_LEFT_UNATTENDED_IN",
        "target_entity_id": "location::public locations",
        "target_entity": "Public Locations",
        "evidence": (
            "Company equipment must not be left unattended "
            "in public locations."
        ),
        "chunk_id": "chunk-123",
        "source": "handbook.pdf",
        "section_id": "section-2-2",
        "section_path": "Working Hours > Remote Work",
        "start_page": 3,
        "end_page": 3,
    }]


def test_retrieves_matching_entity_relationships_and_source_evidence(
    graph_entities,
    graph_relationships,
):
    driver = FakeDriver(graph_entities, graph_relationships)
    retriever = GraphRetriever(driver)

    results = retriever.retrieve(
        "Where should remote employees not leave company equipment?",
        top_k=3,
    )

    assert len(results) == 1
    assert results[0]["source_entity"] == "Company Equipment"
    assert results[0]["relationship"] == (
        "MUST_NOT_BE_LEFT_UNATTENDED_IN"
    )
    assert results[0]["target_entity"] == "Public Locations"
    assert results[0]["source"] == "handbook.pdf"
    assert results[0]["section_path"] == (
        "Working Hours > Remote Work"
    )
    assert results[0]["start_page"] == 3

    # One entity lookup and one relationship traversal.
    assert len(driver.calls) == 2
    assert set(driver.calls[1][1]["entity_ids"]) == {
        "role::remote employee",
        "other::company equipment",
    }


def test_does_not_retrieve_relationships_without_entity_matches(
    graph_relationships,
):
    driver = FakeDriver(
        entities=[{
            "id": "other::company equipment",
            "name": "Company Equipment",
            "type": "OTHER",
        }],
        relationships=graph_relationships,
    )
    retriever = GraphRetriever(driver)

    results = retriever.retrieve("What is the cafeteria menu?")

    assert results == []
    assert len(driver.calls) == 1


def test_rejects_empty_question(graph_entities):
    retriever = GraphRetriever(FakeDriver(graph_entities, []))

    with pytest.raises(ValueError, match="question"):
        retriever.retrieve("  ")


@pytest.mark.parametrize(
    "top_k, max_hops",
    [
        (0, 1),
        (3, 0),
        (3, 4),
    ],
)
def test_rejects_invalid_retrieval_limits(
    graph_entities,
    top_k,
    max_hops,
):
    retriever = GraphRetriever(FakeDriver(graph_entities, []))

    with pytest.raises(ValueError):
        retriever.retrieve(
            "remote employees",
            top_k=top_k,
            max_hops=max_hops,
        )


def test_plural_query_matches_singular_entity_name(graph_entities):
    driver = FakeDriver(graph_entities, [])
    retriever = GraphRetriever(driver)

    matches = retriever._find_matching_entities(
        "What must remote employees protect?"
    )

    assert [entity["name"] for entity in matches] == [
        "Remote Employee"
    ]


def test_directly_relevant_relationship_ranks_above_related_noise():
    entities = [
        {
            "id": "role::remote employee",
            "name": "Remote Employee",
            "type": "ROLE",
        },
        {
            "id": "other::company equipment",
            "name": "Company Equipment",
            "type": "OTHER",
        },
    ]

    # Deliberately return the unrelated relationship first to prove
    # that ranking, rather than database ordering, determines priority.
    relationships = [
        {
            "source_entity_id": "role::remote employee",
            "source_entity": "Remote Employee",
            "relationship": "RESPONSIBLE_FOR_MAINTAINING",
            "target_entity_id": "system::reliable connectivity",
            "target_entity": "Reliable Connectivity",
            "evidence": (
                "Remote employees are responsible for maintaining "
                "reliable connectivity."
            ),
            "chunk_id": "chunk-remote",
            "source": "handbook.pdf",
            "section_id": "remote-work",
            "section_path": "Remote Work",
            "start_page": 3,
            "end_page": 3,
        },
        {
            "source_entity_id": "other::company equipment",
            "source_entity": "Company Equipment",
            "relationship": "MUST_NOT_BE_LEFT_UNATTENDED_IN",
            "target_entity_id": "location::public locations",
            "target_entity": "Public Locations",
            "evidence": (
                "Company equipment must not be left unattended "
                "in public locations."
            ),
            "chunk_id": "chunk-equipment",
            "source": "handbook.pdf",
            "section_id": "remote-work",
            "section_path": "Remote Work",
            "start_page": 3,
            "end_page": 3,
        },
    ]

    driver = FakeDriver(entities, relationships)
    retriever = GraphRetriever(driver)

    results = retriever.retrieve(
        "Where should remote employees not leave company equipment?",
        top_k=2,
    )

    assert results[0]["relationship"] == (
        "MUST_NOT_BE_LEFT_UNATTENDED_IN"
    )
    assert results[0]["target_entity"] == "Public Locations"
    assert results[0]["score"] > results[1]["score"]
