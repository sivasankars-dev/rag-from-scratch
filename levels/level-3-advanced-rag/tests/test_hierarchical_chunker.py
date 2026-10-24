import pytest

from services.hierarchical_chunker import build_document_aware_chunks


def make_section(
    text,
    section_id="handbook.pdf::section::2_2",
    section_title="Remote Work",
    parent_section_id="handbook.pdf::section::2",
):
    return {
        "section_id": section_id,
        "document_id": "handbook.pdf",
        "section_number": "2.2",
        "section_title": section_title,
        "section_type": "section",
        "parent_section_id": parent_section_id,
        "section_path": "Working Hours > Remote Work",
        "start_page": 3,
        "end_page": 4,
        "text": text,
    }


def test_chunks_preserve_hierarchy_metadata_and_parent_relationships():
    sections = [
        make_section(
            "2.2 Remote Work employees must protect devices and "
            "report security incidents promptly"
        ),
        make_section(
            "How many annual leave days are provided? "
            "Employees receive twenty days annually.",
            section_id="handbook.pdf::section::11::faq::1",
            section_title="How many annual leave days are provided?",
            parent_section_id="handbook.pdf::section::11",
        ),
    ]

    result = build_document_aware_chunks(
        sections,
        source="handbook.pdf",
        parent_chunk_size=6,
        child_chunk_size=3,
        child_chunk_overlap=1,
    )

    parents = result["parents"]
    children = result["children"]

    assert len(parents) == 4
    assert len({p["parent_id"] for p in parents}) == len(parents)
    assert len({c["child_id"] for c in children}) == len(children)

    parent_ids = {parent["parent_id"] for parent in parents}
    assert all(child["parent_id"] in parent_ids for child in children)

    remote_parent = next(
        parent for parent in parents
        if parent["section_id"] == "handbook.pdf::section::2_2"
    )
    assert remote_parent["section_title"] == "Remote Work"
    assert remote_parent["section_path"] == (
        "Working Hours > Remote Work"
    )
    assert remote_parent["parent_section_id"] == (
        "handbook.pdf::section::2"
    )
    assert remote_parent["page_number"] == 3
    assert remote_parent["section_start_page"] == 3
    assert remote_parent["section_end_page"] == 4

    faq_child = next(
        child for child in children
        if child["section_type"] == "section"
        and child["section_title"] == "Remote Work"
    )
    assert faq_child["section_id"] == remote_parent["section_id"]


def test_long_section_is_split_into_bounded_parents():
    section = make_section(" ".join(f"word{i}" for i in range(17)))

    result = build_document_aware_chunks(
        [section],
        source="handbook.pdf",
        parent_chunk_size=6,
        child_chunk_size=3,
        child_chunk_overlap=1,
    )

    assert len(result["parents"]) == 3
    assert [len(parent["text"].split()) for parent in result["parents"]] == [
        6, 6, 5
    ]
    assert all(
        parent["section_id"] == section["section_id"]
        for parent in result["parents"]
    )


def test_empty_sections_are_skipped():
    result = build_document_aware_chunks(
        [make_section("   ")],
        source="handbook.pdf",
    )

    assert result == {"parents": [], "children": []}


@pytest.mark.parametrize(
    "parent_size, child_size, overlap",
    [
        (0, 3, 0),
        (8, 0, 0),
        (2, 3, 0),
        (8, 3, -1),
        (8, 3, 3),
    ],
)
def test_invalid_chunk_settings_raise_value_error(
    parent_size, child_size, overlap
):
    with pytest.raises(ValueError):
        build_document_aware_chunks(
            [make_section("one two three four")],
            source="handbook.pdf",
            parent_chunk_size=parent_size,
            child_chunk_size=child_size,
            child_chunk_overlap=overlap,
        )


def test_nonempty_section_requires_an_id():
    section = make_section("some useful content")
    section.pop("section_id")

    with pytest.raises(ValueError, match="section_id"):
        build_document_aware_chunks([section], "handbook.pdf")


def test_source_is_required():
    with pytest.raises(ValueError, match="source"):
        build_document_aware_chunks([make_section("some content")], "")
