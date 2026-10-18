
import json
from pathlib import Path


def prepare_contextual_chunk(original_text, context):
    if not isinstance(original_text, str) or not original_text.strip():
        raise ValueError("original_text must be a non-empty string")

    if not isinstance(context, str) or not context.strip():
        raise ValueError("context must be a non-empty string")

    original_text = original_text.strip()
    context = context.strip()

    return {
        "original_text": original_text,
        "context": context,
        "retrieval_text": f"{context}\n\n{original_text}",
    }

def build_contextual_record(document_text, child, context_generator, parent):
    required_child_fields = [
        "child_id",
        "parent_id",
        "text",
        "source",
        "page_number",
    ]

    for field in required_child_fields:
        if field not in child:
            raise ValueError(f"Missing required child field: {field}")

    required_parent_fields = [
        "parent_id",
        "text",
        "source",
        "page_number",
    ]

    for field in required_parent_fields:
        if field not in parent:
            raise ValueError(f"Missing required parent field: {field}")

    if child["parent_id"] != parent["parent_id"]:
        raise ValueError("Child and parent IDs do not match")

    if child["source"] != parent["source"]:
        raise ValueError("Child and parent source values do not match")

    if child["page_number"] != parent["page_number"]:
        raise ValueError("Child and parent page numbers do not match")

    context = context_generator.generate_context(
        document_text=document_text,
        page_number=child["page_number"],
        original_chunk=child["text"],
    )

    prepared = prepare_contextual_chunk(
        original_text=child["text"],
        context=context,
    )

    return {
        "child_id": child["child_id"],
        "parent_id": child["parent_id"],
        **prepared,
        "parent_text": parent["text"],
        "source": child["source"],
        "page_number": child["page_number"],
    }
    
def embed_contextual_records(records, embedding_service):
    if not isinstance(records, list):
        raise ValueError("records must be a list")

    for record in records:
        if (
            not isinstance(record, dict)
            or not isinstance(record.get("retrieval_text"), str)
            or not record["retrieval_text"].strip()
        ):
            raise ValueError("Every record must have non-empty retrieval_text")

    if not records:
        return []

    texts = [record["retrieval_text"] for record in records]
    embeddings = embedding_service.embed_texts(texts)

    if embeddings is None or len(embeddings) != len(records):
        raise ValueError("Embedding count must match record count")

    return embeddings

def save_contextual_manifest(records, manifest_path):
    """Save contextual records to a JSON manifest."""

    if not isinstance(records, list):
        raise ValueError("records must be a list")

    manifest = {}

    for record in records:
        if not isinstance(record, dict):
            raise ValueError("Every record must be a dictionary")

        child_id = record.get("child_id")

        if not isinstance(child_id, str) or not child_id.strip():
            raise ValueError("Every record must have a valid child_id")

        if child_id in manifest:
            raise ValueError(f"Duplicate child_id: {child_id}")

        manifest[child_id] = record

    path = Path(manifest_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    temporary_path = path.with_name(path.name + ".tmp")

    try:
        temporary_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary_path.replace(path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()

    return len(manifest)

def store_contextual_records(
    records,
    embeddings,
    parent_store,
    child_vector_store,
    manifest_path,
):
    if not isinstance(records, list):
        raise ValueError("records must be a list")

    if len(records) != len(embeddings):
        raise ValueError("Record count must match embedding count")

    parent_records = {}
    children = []
    seen_child_ids = set()

    for record in records:
        if not isinstance(record, dict):
            raise ValueError("Every record must be a dictionary")

        child_id = record.get("child_id")
        parent_id = record.get("parent_id")

        if not isinstance(child_id, str) or not child_id.strip():
            raise ValueError("Every record needs a valid child_id")

        if not isinstance(parent_id, str) or not parent_id.strip():
            raise ValueError("Every record needs a valid parent_id")

        if child_id in seen_child_ids:
            raise ValueError(f"Duplicate child_id: {child_id}")

        seen_child_ids.add(child_id)

        required_fields = [
            "original_text",
            "retrieval_text",
            "parent_text",
            "source",
            "page_number",
        ]

        for field in required_fields:
            if field not in record:
                raise ValueError(f"Missing required field: {field}")

        for field in ("original_text", "retrieval_text", "parent_text", "source"):
            value = record[field]
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field} must be a non-empty string")

        parent_text = record["parent_text"]
        source = record["source"]
        page_number = record["page_number"]

        existing_parent = parent_records.get(parent_id)

        if existing_parent is not None:
            if (
                existing_parent["text"] != parent_text
                or existing_parent["source"] != source
                or existing_parent["page_number"] != page_number
            ):
                raise ValueError(
                    f"Conflicting parent records for parent_id: {parent_id}"
                )
        else:
            parent_records[parent_id] = {
                "parent_id": parent_id,
                "text": parent_text,
                "source": source,
                "page_number": page_number,
            }

        children.append(
            {
                "child_id": child_id,
                "text": record["retrieval_text"],
                "parent_id": parent_id,
                "source": source,
                "page_number": page_number,
            }
        )

    # Persist only after validating all records.
    save_contextual_manifest(records, manifest_path)

    for parent in parent_records.values():
        parent_store.store_parent(parent)

    child_vector_store.store_children(children, embeddings)

