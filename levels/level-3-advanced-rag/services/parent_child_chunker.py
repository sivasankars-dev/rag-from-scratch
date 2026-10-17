import importlib.util
from pathlib import Path

LEVEL_2_CHUNKER_PATH = (
    Path(__file__).resolve().parents[2]
    / "level-2-practical-rag"
    / "services"
    / "overlap_chunker.py"
)

spec = importlib.util.spec_from_file_location(
    "level_2_chunker",
    LEVEL_2_CHUNKER_PATH,
)

level_2_chunker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(level_2_chunker)

chunk_text_with_overlap = level_2_chunker.chunk_text_with_overlap

def build_parent_child_chunks(
    text,
    source,
    page_number=1,
    parent_chunk_size=8,
    child_chunk_size=3,
    child_chunk_overlap=1,
):
    text = text.strip()
    if not text or not source:
        return {"parents": [], "children": []}

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

    words = text.split()
    parent_step = parent_chunk_size
    parents = []
    children = []

    for start in range(0, len(words), parent_step):
        parent_words = words[start:start+parent_chunk_size]
        parent_text = " ".join(parent_words)

        parent_id = f"{source}_page_{page_number}_parent_{len(parents)}"

        parents.append({
            "text": parent_text,
            "parent_id": parent_id,
            "source": source,
            "page_number": page_number
        })

        child_chunks = chunk_text_with_overlap(
            parent_text,
            chunk_limit=child_chunk_size,
            overlap=child_chunk_overlap,
        )

        for child_index, child_text in enumerate(child_chunks):
            children.append({
                "child_id": f"{parent_id}_child_{child_index}",
                "parent_id": parent_id,
                "text": child_text,
                "source": source,
                "page_number": page_number,
            })

    return {
        "parents": parents,
        "children": children
    }
