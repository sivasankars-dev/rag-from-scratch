import pytest

from services.graph_store import Neo4jGraphStore


class FakeResult:
    def consume(self):
        return None


class FakeTransaction:
    def __init__(self):
        self.calls = []

    def run(self, query, **parameters):
        self.calls.append((query, parameters))
        return FakeResult()


class FakeSession:
    def __init__(self, transaction):
        self.transaction = transaction

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute_write(self, callback, *args):
        return callback(self.transaction, *args)


class FakeDriver:
    def __init__(self):
        self.transaction = FakeTransaction()
        self.constraint_queries = []

    def session(self, database):
        assert database == "neo4j"
        return FakeSession(self.transaction)

    def execute_query(self, query, **kwargs):
        self.constraint_queries.append((query, kwargs))
        return [], None, None


@pytest.fixture
def extraction():
    return {
        "metadata": {
            "source": "handbook.pdf",
            "section_id": "section_3_1",
            "section_path": "Leave > Annual Leave",
            "start_page": 4,
            "end_page": 4,
        },
        "entities": [
            {
                "entity_id": "role::employee",
                "name": "Employee",
                "type": "ROLE",
            },
            {
                "entity_id": "benefit::annual leave",
                "name": "Annual Leave",
                "type": "BENEFIT",
            },
        ],
        "relationships": [
            {
                "source": "Employee",
                "source_entity_id": "role::employee",
                "predicate": "RECEIVES",
                "target": "Annual Leave",
                "target_entity_id": "benefit::annual leave",
                "evidence": "Employees receive annual leave.",
            },
        ],
    }


def test_store_extraction_preserves_nodes_edges_and_source_evidence(extraction):
    driver = FakeDriver()
    store = Neo4jGraphStore(driver)

    result = store.store_extraction(
        "Employees receive annual leave.",
        extraction,
    )

    assert result["entities_stored"] == 2
    assert result["relationships_stored"] == 1
    assert len(result["chunk_id"]) == 64

    queries = [query for query, _ in driver.transaction.calls]
    parameters = [params for _, params in driver.transaction.calls]

    assert any("DocumentChunk" in query for query in queries)
    assert any("MENTIONS" in query for query in queries)
    assert any("RECEIVES" in query for query in queries)

    relationship_write = next(
        params for query, params in driver.transaction.calls
        if "RECEIVES" in query
    )
    assert relationship_write["evidence"] == (
        "Employees receive annual leave."
    )
    assert relationship_write["chunk_id"] == result["chunk_id"]

    assert any(
        params.get("section_path") == "Leave > Annual Leave"
        for params in parameters
    )


def test_same_section_uses_deterministic_chunk_id(extraction):
    driver = FakeDriver()
    store = Neo4jGraphStore(driver)

    first = store.store_extraction(
        "Employees receive annual leave.",
        extraction,
    )
    second = store.store_extraction(
        "Employees receive annual leave.",
        extraction,
    )

    assert first["chunk_id"] == second["chunk_id"]


def test_store_requires_source_metadata(extraction):
    driver = FakeDriver()
    store = Neo4jGraphStore(driver)
    extraction["metadata"].pop("source")

    with pytest.raises(ValueError, match="Source metadata"):
        store.store_extraction(
            "Employees receive annual leave.",
            extraction,
        )

    assert driver.transaction.calls == []


@pytest.mark.parametrize(
    "predicate",
    [
        "MATCH",
        "RELATES TO",
        "X`]->(:Hacked",
        "",
    ],
)
def test_store_rejects_invalid_relationship_identifiers(extraction, predicate):
    driver = FakeDriver()
    store = Neo4jGraphStore(driver)
    extraction["relationships"][0]["predicate"] = predicate

    with pytest.raises(ValueError, match="Invalid relationship predicate"):
        store.store_extraction(
            "Employees receive annual leave.",
            extraction,
        )

    assert driver.transaction.calls == []


def test_store_rejects_evidence_not_present_in_source(extraction):
    driver = FakeDriver()
    store = Neo4jGraphStore(driver)
    extraction["relationships"][0]["evidence"] = (
        "Managers approve every annual leave request."
    )

    with pytest.raises(ValueError, match="not present in source"):
        store.store_extraction(
            "Employees receive annual leave.",
            extraction,
        )

    assert driver.transaction.calls == []
