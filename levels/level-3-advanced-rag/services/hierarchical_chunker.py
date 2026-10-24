"""Build bounded parent-child chunks from parsed document sections."""

from services.parent_child_chunker import chunk_text_with_overlap


def build_document_aware_chunks(
    sections,
    source,
    parent_chunk_size=100,
    child_chunk_size=30,
    child_chunk_overlap=10,
):
    """Chunk parsed sections without crossing section boundaries.

    Each parent and child retains its source section metadata. Long sections
    are split into bounded parent chunks rather than returned as one
    unbounded context.
    """
    if not source:
        raise ValueError("source is required")

    if parent_chunk_size <= 0:
        raise ValueError("parent_chunk_size must be greater than 0")

    if child_chunk_size <= 0:
        raise ValueError("child_chunk_size must be greater than 0")

    if child_chunk_size > parent_chunk_size:
        raise ValueError("child_chunk_size cannot exceed parent_chunk_size")

    if child_chunk_overlap < 0:
        raise ValueError("child_chunk_overlap cannot be negative")

    if child_chunk_overlap >= child_chunk_size:
        raise ValueError("child_chunk_overlap must be less than child_chunk_size")

    parents = []
    children = []
    seen_section_ids = set()

    for section in sections:
        text = (section.get("text") or "").strip()

        if not text:
            continue

        section_id = section.get("section_id")
        if not section_id:
            raise ValueError("Each nonempty section must have a section_id")

        # Section IDs identify a structural section. Multiple bounded
        # parents from that section intentionally share the same section_id.
        seen_section_ids.add(section_id)

        words = text.split()

        for start in range(0, len(words), parent_chunk_size):
            parent_index = start // parent_chunk_size
            parent_text = " ".join(words[start:start + parent_chunk_size])
            parent_id = f"{section_id}::parent::{parent_index}"

            start_page = int(section.get("start_page", 1))
            end_page = int(section.get("end_page", start_page))

            shared_metadata = {
                "source": source,
                "document_id": section.get("document_id") or source,
                "section_id": section_id,
                "section_number": section.get("section_number"),
                "section_title": section.get("section_title", ""),
                "section_type": section.get("section_type", "section"),
                "parent_section_id": section.get("parent_section_id"),
                "section_path": section.get("section_path", ""),
                "section_start_page": start_page,
                "section_end_page": end_page,
                # Retained for compatibility with the existing store API.
                "page_number": start_page,
            }

            parent = {
                **shared_metadata,
                "text": parent_text,
                "parent_id": parent_id,
                "chunk_index": parent_index,
            }
            parents.append(parent)

            child_chunks = chunk_text_with_overlap(
                parent_text,
                chunk_limit=child_chunk_size,
                overlap=child_chunk_overlap,
            )

            for child_index, child_text in enumerate(child_chunks):
                children.append({
                    **shared_metadata,
                    "child_id": f"{parent_id}::child::{child_index}",
                    "parent_id": parent_id,
                    "text": child_text,
                })

    return {"parents": parents, "children": children}
