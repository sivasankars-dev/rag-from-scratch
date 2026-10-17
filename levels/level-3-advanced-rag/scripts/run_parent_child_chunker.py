from pprint import pprint
from services.parent_child_chunker import build_parent_child_chunks


result = build_parent_child_chunks(
    text="one two three four five six seven eight",
    source="handbook.pdf",
    parent_chunk_size=8,
    child_chunk_size=3,
    child_chunk_overlap=1,
)

pprint(result)
