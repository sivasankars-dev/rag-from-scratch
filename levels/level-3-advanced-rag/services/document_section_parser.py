"""Parse numbered document headings and FAQ entries."""

import re


_NUMBERED_HEADING = re.compile(
    r"^\s*(?P<number>\d+(?:\.\d+)*\.?)\s+(?P<title>\S.*?)\s*$"
)
_FAQ_TITLE = re.compile(
    r"\b(?:frequently asked questions|faqs?)\b",
    re.IGNORECASE,
)


def _parse_heading(line):
    """Recognize likely numbered headings."""
    match = _NUMBERED_HEADING.match(line)

    if not match:
        return None

    number = match.group("number").rstrip(".")
    title = match.group("title").strip()

    if not title or len(title) > 120:
        return None

    # Avoid treating sentence-like numbered list items as headings.
    if title.endswith((".", "?", "!", ";")):
        return None

    return number, title


def _finish_section(section, sections):
    """Convert an in-progress section to a plain record."""
    if section is None:
        return

    record = {
        key: value
        for key, value in section.items()
        if key != "_lines"
    }
    record["text"] = "\n".join(section["_lines"]).strip()

    if record["text"]:
        sections.append(record)


def _is_document_footer(line):
    return bool(
        re.match(
            r"^end of .+ document\.?$",
            line.strip(),
            re.IGNORECASE,
        )
    )


def parse_document_sections(pages, source):
    """Parse ordered page records into heading-aware sections and FAQ entries.

    Pages must contain ``text`` and ``page_number`` fields.

    Sections continue across page boundaries until another recognized
    numbered heading appears. In a FAQ section, each question ending in '?'
    starts a distinct entry; subsequent lines are its answer until the next
    question or section heading.
    """
    if not source:
        raise ValueError("source is required")

    sections = []
    current = None
    faq_item = None
    faq_items = []
    faq_counter = 0
    heading_stack = {}

    def flush_current():
        """Finalize the current section and its optional FAQ entries."""
        nonlocal current, faq_item, faq_items, faq_counter

        if current is None:
            return

        if faq_item is not None:
            _finish_section(faq_item, faq_items)

        _finish_section(current, sections)

        # Keep the FAQ parent before its question-answer entries.
        sections.extend(faq_items)

        current = None
        faq_item = None
        faq_items = []
        faq_counter = 0

    for page in pages:
        page_text = page.get("text") or ""
        page_number = page["page_number"]

        for raw_line in page_text.splitlines():
            line = raw_line.strip()

            if not line:
                continue

            heading = _parse_heading(line)

            if heading:
                flush_current()

                number, title = heading
                parts = number.split(".")
                ancestor_records = []

                for depth in range(1, len(parts)):
                    ancestor_number = ".".join(parts[:depth])
                    ancestor = heading_stack.get(ancestor_number)

                    if ancestor:
                        ancestor_records.append(ancestor)

                parent_number = (
                    ".".join(parts[:-1]) if len(parts) > 1 else None
                )
                parent_record = (
                    heading_stack.get(parent_number)
                    if parent_number
                    else None
                )

                section_id = (
                    f"{source}::section::{number.replace('.', '_')}"
                )
                section_path = " > ".join(
                    [item["title"] for item in ancestor_records] + [title]
                )

                is_faq = bool(_FAQ_TITLE.search(title))

                current = {
                    "section_id": section_id,
                    "document_id": source,
                    "section_number": number,
                    "section_title": title,
                    "section_type": "faq" if is_faq else "section",
                    "parent_section_id": (
                        parent_record["section_id"]
                        if parent_record
                        else None
                    ),
                    "section_path": section_path,
                    "start_page": page_number,
                    "end_page": page_number,
                    "_lines": [line],
                }

                # Preserve heading ancestors and discard old siblings
                # and descendants.
                depth = len(parts)
                heading_stack = {
                    key: value
                    for key, value in heading_stack.items()
                    if len(key.split(".")) < depth
                }
                heading_stack[number] = {
                    "section_id": section_id,
                    "title": title,
                }
                continue

            if _is_document_footer(line):
                continue

            if current is None:
                current = {
                    "section_id": f"{source}::preamble",
                    "document_id": source,
                    "section_number": None,
                    "section_title": "Document Introduction",
                    "section_type": "preamble",
                    "parent_section_id": None,
                    "section_path": "Document Introduction",
                    "start_page": page_number,
                    "end_page": page_number,
                    "_lines": [],
                }

            if current["section_type"] == "faq":
                current["end_page"] = page_number

                if line.endswith("?"):
                    if faq_item is not None:
                        _finish_section(faq_item, faq_items)

                    faq_counter += 1
                    question_id = (
                        f"{current['section_id']}::faq::{faq_counter}"
                    )

                    faq_item = {
                        "section_id": question_id,
                        "document_id": source,
                        "section_number": None,
                        "section_title": line,
                        "section_type": "faq_item",
                        "parent_section_id": current["section_id"],
                        "section_path": (
                            f"{current['section_path']} > {line}"
                        ),
                        "start_page": page_number,
                        "end_page": page_number,
                        "_lines": [line],
                    }
                elif faq_item is not None:
                    faq_item["_lines"].append(line)
                    faq_item["end_page"] = page_number
                else:
                    # Preserve any introductory text before the first FAQ.
                    current["_lines"].append(line)
                continue

            current["_lines"].append(line)
            current["end_page"] = page_number

    flush_current()
    return sections
