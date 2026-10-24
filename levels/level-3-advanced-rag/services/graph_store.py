"""Persist source-grounded entities and relationships in Neo4j."""

import hashlib
import re


CYPHER_RESERVED_WORDS = {
    "MATCH", "WHERE", "RETURN", "WITH", "CREATE", "MERGE",
    "DELETE", "DETACH", "SET", "REMOVE", "CALL", "UNWIND",
    "OPTIONAL", "ORDER", "BY", "LIMIT", "SKIP", "UNION",
    "AND", "OR", "NOT", "AS", "ON", "IN", "IS", "NULL",
    "TRUE", "FALSE", "CASE", "WHEN", "THEN", "ELSE", "END",
}


def normalize_text(text):
    return re.sub(r"\s+", " ", text).strip()


def make_chunk_id(source, section_id, text):
    """Create a stable document-chunk identity."""
    identity = (
        f"{source}\0{section_id}"
        if section_id
        else f"{source}\0{normalize_text(text)}"
    )
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


class Neo4jGraphStore:
    """Store document chunks, entity nodes, and evidence-backed edges."""

    def __init__(self, driver, database="neo4j"):
        self.driver = driver
        self.database = database

    def ensure_constraints(self):
        """Make entity and document-chunk IDs unique."""
        self.driver.execute_query(
            """
            CREATE CONSTRAINT entity_id_unique IF NOT EXISTS
            FOR (entity:Entity)
            REQUIRE entity.id IS UNIQUE
            """,
            database_=self.database,
        )
        self.driver.execute_query(
            """
            CREATE CONSTRAINT document_chunk_id_unique IF NOT EXISTS
            FOR (chunk:DocumentChunk)
            REQUIRE chunk.id IS UNIQUE
            """,
            database_=self.database,
        )

    def _validate(self, text, extraction):
        if not isinstance(text, str) or not text.strip():
            raise ValueError("Source text must be nonempty")

        if not isinstance(extraction, dict):
            raise ValueError("Extraction must be a dictionary")

        metadata = extraction.get("metadata")
        entities = extraction.get("entities")
        relationships = extraction.get("relationships")

        if not isinstance(metadata, dict):
            raise ValueError("Extraction metadata must be a dictionary")

        if not metadata.get("source"):
            raise ValueError("Source metadata is required")

        if not isinstance(entities, list):
            raise ValueError("Entities must be a list")

        if not isinstance(relationships, list):
            raise ValueError("Relationships must be a list")

        entities_by_id = {}

        for entity in entities:
            if not isinstance(entity, dict):
                raise ValueError("Each entity must be a dictionary")

            entity_id = entity.get("entity_id")
            name = entity.get("name")
            entity_type = entity.get("type")

            if not all(
                isinstance(value, str) and value.strip()
                for value in (entity_id, name, entity_type)
            ):
                raise ValueError(
                    "Each entity requires an ID, name, and type"
                )

            if entity_id in entities_by_id:
                raise ValueError(f"Duplicate entity ID: {entity_id}")

            entities_by_id[entity_id] = entity

        source_text = normalize_text(text).casefold()

        for relationship in relationships:
            if not isinstance(relationship, dict):
                raise ValueError("Each relationship must be a dictionary")

            source_id = relationship.get("source_entity_id")
            target_id = relationship.get("target_entity_id")
            predicate = relationship.get("predicate")
            evidence = relationship.get("evidence")

            if source_id not in entities_by_id:
                raise ValueError("Relationship source is not a known entity")

            if target_id not in entities_by_id:
                raise ValueError("Relationship target is not a known entity")

            # Only allow safe relationship-type identifiers before using
            # the predicate as a Cypher identifier.
            if (
                not isinstance(predicate, str)
                or not re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", predicate)
                or predicate in CYPHER_RESERVED_WORDS
            ):
                raise ValueError("Invalid relationship predicate")

            if not isinstance(evidence, str) or not evidence.strip():
                raise ValueError("Relationship evidence is required")

            evidence = normalize_text(evidence)

            if evidence.casefold() not in source_text:
                raise ValueError(
                    "Relationship evidence is not present in source text"
                )

        return metadata, entities, relationships

    @staticmethod
    def _write_transaction(
        tx,
        chunk_id,
        text,
        metadata,
        entities,
        relationships,
    ):
        # Replace relationships supported by this chunk so an updated
        # extraction does not retain stale facts for the same section.
        tx.run(
            """
            MATCH (chunk:DocumentChunk {id: $chunk_id})
                  -[mention:MENTIONS]->()
            DELETE mention
            """,
            chunk_id=chunk_id,
        )

        tx.run(
            """
            MATCH ()-[relationship]->()
            WHERE relationship.source_chunk_id = $chunk_id
            DELETE relationship
            """,
            chunk_id=chunk_id,
        )

        tx.run(
            """
            MERGE (chunk:DocumentChunk {id: $chunk_id})
            SET chunk.text = $text,
                chunk.source = $source,
                chunk.section_id = $section_id,
                chunk.section_path = $section_path,
                chunk.start_page = $start_page,
                chunk.end_page = $end_page
            """,
            chunk_id=chunk_id,
            text=text,
            source=metadata["source"],
            section_id=metadata.get("section_id"),
            section_path=metadata.get("section_path"),
            start_page=metadata.get("start_page"),
            end_page=metadata.get("end_page"),
        )

        for entity in entities:
            tx.run(
                """
                MERGE (entity:Entity {id: $entity_id})
                SET entity.name = $name,
                    entity.type = $entity_type
                WITH entity
                MATCH (chunk:DocumentChunk {id: $chunk_id})
                MERGE (chunk)-[:MENTIONS]->(entity)
                """,
                entity_id=entity["entity_id"],
                name=entity["name"],
                entity_type=entity["type"],
                chunk_id=chunk_id,
            )

        for relationship in relationships:
            predicate = relationship["predicate"]

            evidence = normalize_text(relationship["evidence"])
            evidence_id = hashlib.sha256(
                (
                    f"{chunk_id}\0"
                    f"{relationship['source_entity_id']}\0"
                    f"{predicate}\0"
                    f"{relationship['target_entity_id']}\0"
                    f"{evidence}"
                ).encode("utf-8")
            ).hexdigest()

            # predicate has already passed a strict identifier whitelist.
            query = f"""
                MATCH (source:Entity {{id: $source_id}})
                MATCH (target:Entity {{id: $target_id}})
                MERGE (source)-[edge:`{predicate}` {{
                    source_chunk_id: $chunk_id,
                    evidence_id: $evidence_id
                }}]->(target)
                SET edge.predicate = $predicate,
                    edge.evidence = $evidence
            """

            tx.run(
                query,
                source_id=relationship["source_entity_id"],
                target_id=relationship["target_entity_id"],
                chunk_id=chunk_id,
                evidence_id=evidence_id,
                predicate=predicate,
                evidence=evidence,
            )

    def store_extraction(self, text, extraction):
        """Validate and persist one extracted document section."""
        metadata, entities, relationships = self._validate(
            text,
            extraction,
        )

        chunk_id = make_chunk_id(
            metadata["source"],
            metadata.get("section_id"),
            text,
        )

        with self.driver.session(database=self.database) as session:
            session.execute_write(
                self._write_transaction,
                chunk_id,
                text,
                metadata,
                entities,
                relationships,
            )

        return {
            "chunk_id": chunk_id,
            "entities_stored": len(entities),
            "relationships_stored": len(relationships),
        }
