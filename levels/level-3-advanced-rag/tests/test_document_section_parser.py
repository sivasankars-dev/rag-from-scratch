from services.document_section_parser import parse_document_sections


def test_parses_numbered_sections_and_preserves_page_continuation():
    pages = [
        {
            "page_number": 1,
            "text": (
                "Handbook introduction\n"
                "1. Company Overview\n"
                "Company information starts here."
            ),
        },
        {
            "page_number": 2,
            "text": (
                "Company information continues here.\n"
                "1.1 Working Principles\n"
                "Ownership and security are important.\n"
                "1.2 Departments\n"
                "Engineering manages software development."
            ),
        },
    ]

    sections = parse_document_sections(pages, "handbook.pdf")

    assert [section["section_number"] for section in sections] == [
        None, "1", "1.1", "1.2"
    ]

    introduction, overview, principles, departments = sections

    assert introduction["text"] == "Handbook introduction"
    assert "Company information starts here." in overview["text"]
    assert "Company information continues here." in overview["text"]
    assert overview["start_page"] == 1
    assert overview["end_page"] == 2

    assert principles["section_title"] == "Working Principles"
    assert principles["parent_section_id"] == overview["section_id"]
    assert principles["section_path"] == (
        "Company Overview > Working Principles"
    )
    assert principles["start_page"] == 2

    assert departments["parent_section_id"] == overview["section_id"]
    assert departments["section_path"] == (
        "Company Overview > Departments"
    )


def test_sentence_like_numbered_list_item_is_not_treated_as_heading():
    pages = [
        {
            "page_number": 1,
            "text": (
                "1. Benefits\n"
                "Employees may select available options.\n"
                "1. Employees must complete the form.\n"
                "The process is documented."
            ),
        }
    ]

    sections = parse_document_sections(pages, "handbook.pdf")

    assert len(sections) == 1
    assert sections[0]["section_number"] == "1"
    assert "1. Employees must complete the form." in sections[0]["text"]


def test_unheaded_document_text_is_preserved():
    pages = [
        {"page_number": 1, "text": "Title of document\nPurpose of this guide."},
        {"page_number": 2, "text": "Additional introductory information."},
    ]

    sections = parse_document_sections(pages, "guide.pdf")

    assert len(sections) == 1
    assert sections[0]["section_title"] == "Document Introduction"
    assert sections[0]["start_page"] == 1
    assert sections[0]["end_page"] == 2
    assert "Additional introductory information." in sections[0]["text"]


def test_empty_pages_return_no_sections():
    assert parse_document_sections(
        [{"page_number": 1, "text": "  "}],
        "handbook.pdf",
    ) == []


def test_source_is_required():
    try:
        parse_document_sections([], "")
    except ValueError as error:
        assert str(error) == "source is required"
    else:
        raise AssertionError("Expected ValueError for empty source")


def test_faq_questions_are_separate_children_of_faq_section():
    pages = [{
        "page_number": 12,
        "text": (
            "11. Frequently Asked Questions\n"
            "How many annual leave days are provided?\n"
            "Full-time employees generally receive 20 annual leave days.\n"
            "When should planned leave be submitted?\n"
            "Planned leave should use the approved leave system.\n"
            "End of synthetic training document."
        ),
    }]

    sections = parse_document_sections(pages, "handbook.pdf")
    faq_parent = next(
        section for section in sections
        if section["section_number"] == "11"
    )
    faq_items = [
        section for section in sections
        if section.get("section_type") == "faq_item"
    ]

    assert len(faq_items) == 2
    assert faq_parent["text"] == "11. Frequently Asked Questions"

    first, second = faq_items

    assert first["section_title"] == (
        "How many annual leave days are provided?"
    )
    assert "20 annual leave days" in first["text"]
    assert first["parent_section_id"] == faq_parent["section_id"]

    assert second["section_title"] == (
        "When should planned leave be submitted?"
    )
    assert "approved leave system" in second["text"]
    assert second["parent_section_id"] == faq_parent["section_id"]

    assert all(item["start_page"] == 12 for item in faq_items)
    assert all(
        "End of synthetic training document" not in item["text"]
        for item in faq_items
    )


def test_faq_entry_ids_are_unique_and_deterministic():
    pages = [{
        "page_number": 1,
        "text": (
            "11. Frequently Asked Questions\n"
            "Question one?\nAnswer one.\n"
            "Question two?\nAnswer two."
        ),
    }]

    first_run = parse_document_sections(pages, "handbook.pdf")
    second_run = parse_document_sections(pages, "handbook.pdf")

    first_ids = [
        section["section_id"]
        for section in first_run
        if section.get("section_type") == "faq_item"
    ]
    second_ids = [
        section["section_id"]
        for section in second_run
        if section.get("section_type") == "faq_item"
    ]

    assert len(first_ids) == 2
    assert len(set(first_ids)) == 2
    assert first_ids == second_ids
