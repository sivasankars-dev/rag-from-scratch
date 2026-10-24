"""Retrieve and rank source-grounded evidence through Neo4j traversal."""

import re


_STOP_WORDS = {
    "what", "where", "when", "why", "how", "who", "which",
    "should", "would", "could", "can", "do", "does", "did",
    "the", "a", "an", "to", "of", "for", "in", "on", "at",
    "from", "through", "with", "are", "is", "be", "it",
    "tell", "me", "find", "show", "about",
}

_TOKEN_NORMALIZATION = {
    "employees": "employee",
    "left": "leave",
    "leaving": "leave",
    "leaves": "leave",
    "maintains": "maintain",
    "maintaining": "maintain",
    "maintained": "maintain",
    "locations": "location",
}


def _normalize_token(token):
    token = token.casefold()

    if token in _TOKEN_NORMALIZATION:
        return _TOKEN_NORMALIZATION[token]

    if len(token) > 4 and token.endswith("ies"):
        return token[:-3] + "y"

    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]

    return token


def _tokens(text):
    """Tokenize text, retaining meaningful terms such as 'not'."""
    words = re.findall(r"\b[a-z0-9]+\b", text.casefold())

    return {
        normalized
        for word in words
        if (normalized := _normalize_token(word)) not in _STOP_WORDS
    }

def _relevance_score(question, result):
    """Rank graph evidence, prioritizing the actual supporting text."""
    question_tokens = _tokens(question)

    entity_tokens = _tokens(
        f"{result['source_entity']} {result['target_entity']}"
    )
    evidence_tokens = _tokens(result.get("evidence") or "")
    relationship_tokens = _tokens(result.get("relationship") or "")
    section_tokens = _tokens(result.get("section_path") or "")

    entity_overlap = len(question_tokens & entity_tokens)
    evidence_overlap = len(question_tokens & evidence_tokens)
    relationship_overlap = len(question_tokens & relationship_tokens)
    section_overlap = len(question_tokens & section_tokens)

    return (
        0.5 * entity_overlap
        + 4.0 * evidence_overlap
        + 3.0 * relationship_overlap
        + 0.25 * section_overlap
    )

class GraphRetriever:
    """Match question entities, traverse relationships, and rank evidence."""

    def __init__(self, driver, database="neo4j"):
        self.driver = driver
        self.database = database

    def _find_matching_entities(self, question):
        question_tokens = _tokens(question)

        if not question_tokens:
            return []

        records, _, _ = self.driver.execute_query(
            """
            MATCH (entity:Entity)
            RETURN entity.id AS id,
                   entity.name AS name,
                   entity.type AS type
            """,
            database_=self.database,
        )

        matches = []

        for record in records:
            entity_tokens = _tokens(record["name"])

            if entity_tokens and entity_tokens.issubset(question_tokens):
                matches.append({
                    "id": record["id"],
                    "name": record["name"],
                    "type": record["type"],
                })

        # Try more specific multiword entities before shorter entities.
        matches.sort(
            key=lambda item: (
                -len(_tokens(item["name"])),
                item["name"].casefold(),
            )
        )

        return matches

    def retrieve(self, question, top_k=5, max_hops=1):
        """Return the highest-ranked relationship evidence."""
        if not isinstance(question, str) or not question.strip():
            raise ValueError("question must not be empty")

        if top_k <= 0:
            raise ValueError("top_k must be greater than 0")

        if max_hops not in (1, 2, 3):
            raise ValueError("max_hops must be between 1 and 3")

        matched_entities = self._find_matching_entities(question)

        if not matched_entities:
            return []

        entity_ids = [entity["id"] for entity in matched_entities]

        query = f"""
        MATCH path = (start:Entity)-[*1..{max_hops}]-(neighbor:Entity)
        WHERE start.id IN $entity_ids
        UNWIND relationships(path) AS rel
        WITH DISTINCT rel
        MATCH (chunk:DocumentChunk {{id: rel.source_chunk_id}})
        RETURN DISTINCT
               startNode(rel).id AS source_entity_id,
               startNode(rel).name AS source_entity,
               type(rel) AS relationship,
               endNode(rel).id AS target_entity_id,
               endNode(rel).name AS target_entity,
               rel.evidence AS evidence,
               chunk.id AS chunk_id,
               chunk.source AS source,
               chunk.section_id AS section_id,
               chunk.section_path AS section_path,
               chunk.start_page AS start_page,
               chunk.end_page AS end_page
        """

        records, _, _ = self.driver.execute_query(
            query,
            entity_ids=entity_ids,
            database_=self.database,
        )

        results = [
            {
                "source_entity_id": record["source_entity_id"],
                "source_entity": record["source_entity"],
                "relationship": record["relationship"],
                "target_entity_id": record["target_entity_id"],
                "target_entity": record["target_entity"],
                "evidence": record["evidence"],
                "chunk_id": record["chunk_id"],
                "source": record["source"],
                "section_id": record["section_id"],
                "section_path": record["section_path"],
                "start_page": record["start_page"],
                "end_page": record["end_page"],
            }
            for record in records
        ]

        for result in results:
            result["score"] = _relevance_score(question, result)

        results.sort(
            key=lambda result: (
                -result["score"],
                result["source_entity"].casefold(),
                result["relationship"],
                result["target_entity"].casefold(),
            )
        )

        return results[:top_k]
