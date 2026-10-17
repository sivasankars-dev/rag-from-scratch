
import pytest
from services.parent_child_chunker import build_parent_child_chunks


def test_builds_parent_and_child_chunks():
    result = build_parent_child_chunks(
        text="one two three four five six seven eight",
        source="handbook.pdf",
        page_number=1,
        parent_chunk_size=8,
        child_chunk_size=3,
        child_chunk_overlap=1,
    )

    assert len(result["parents"]) == 1
    assert len(result["children"]) == 4

    parent = result["parents"][0]
    assert parent["text"] == "one two three four five six seven eight"
    assert parent["parent_id"] == "handbook.pdf_parent_0"

    children = result["children"]

    assert [child["text"] for child in children] == [
        "one two three",
        "three four five",
        "five six seven",
        "seven eight",
    ]

    assert all(
        child["parent_id"] == parent["parent_id"]
        for child in children
    )


def test_child_chunks_include_source_and_page_metadata():
    result = build_parent_child_chunks(
        text="one two three four",
        source="handbook.pdf",
        page_number=2,
        parent_chunk_size=10,
        child_chunk_size=2,
        child_chunk_overlap=0,
    )

    for child in result["children"]:
        assert child["source"] == "handbook.pdf"
        assert child["page_number"] == 2
        assert child["parent_id"] == result["parents"][0]["parent_id"]
        assert "child_id" in child


def test_empty_text_returns_empty_parent_and_child_lists():
    result = build_parent_child_chunks(
        text="   ",
        source="handbook.pdf",
        page_number=1,
        parent_chunk_size=8,
        child_chunk_size=3,
        child_chunk_overlap=1,
    )

    assert result == {"parents": [], "children": []}


@pytest.mark.parametrize(
    "parent_size, child_size, overlap",
    [
        (0, 3, 0),
        (8, 0, 0),
        (8, 3, -1),
        (8, 3, 3),
        (2, 3, 0),
    ],
)
def test_invalid_chunk_configuration_raises_value_error(
    parent_size, child_size, overlap
):
    with pytest.raises(ValueError):
        build_parent_child_chunks(
            text="one two three four",
            source="handbook.pdf",
            page_number=1,
            parent_chunk_size=parent_size,
            child_chunk_size=child_size,
            child_chunk_overlap=overlap,
        )
