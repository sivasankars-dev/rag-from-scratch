"""Extract text and tables from PDFs with page-level provenance."""

from pathlib import Path

import pymupdf

from services.multimodal.table_serializer import serialize_table


def extract_table_rows_from_page(page, table):
    """Recover table cell text from positioned PDF words."""
    words = page.get_text("words")
    extracted_rows = []

    for row in table.rows:
        extracted_row = []

        for cell in row.cells:
            if cell is None:
                extracted_row.append("")
                continue

            x0, y0, x1, y1 = cell
            cell_words = []

            for word in words:
                wx0, wy0, wx1, wy1, word_text = word[:5]
                center_x = (wx0 + wx1) / 2
                center_y = (wy0 + wy1) / 2

                if x0 <= center_x <= x1 and y0 <= center_y <= y1:
                    cell_words.append((center_y, wx0, word_text))

            cell_words.sort(key=lambda item: (item[0], item[1]))
            extracted_row.append(" ".join(item[2] for item in cell_words))

        extracted_rows.append(extracted_row)

    return extracted_rows


def remove_table_regions_from_text(page, tables):
    """Remove words inside detected table bounds from page text."""
    table_bounds = [table.bbox for table in tables]

    lines = page.get_text("dict")["blocks"]
    remaining_lines = []

    for block in lines:
        if "lines" not in block:
            continue

        for line in block["lines"]:
            line_parts = []

            for span in line["spans"]:
                x0, y0, x1, y1 = span["bbox"]
                center_x = (x0 + x1) / 2
                center_y = (y0 + y1) / 2

                inside_table = any(
                    tx0 <= center_x <= tx1 and ty0 <= center_y <= ty1
                    for tx0, ty0, tx1, ty1 in table_bounds
                )

                if not inside_table:
                    line_parts.append(span["text"])

            text = "".join(line_parts).strip()
            if text:
                remaining_lines.append(text)

    return "\n".join(remaining_lines).strip()


def load_pdf_records(pdf_path):
    """Return deduplicated text and structured table records."""
    path = Path(pdf_path)

    if not path.is_file():
        raise FileNotFoundError(f"PDF not found: {path}")

    records = []

    with pymupdf.open(path) as pdf:
        for page_number, page in enumerate(pdf, start=1):
            source = path.name
            tables = page.find_tables().tables

            # Extract table records first so we can remove their text
            # from the page-level record.
            for table_number, table in enumerate(tables, start=1):
                table_rows = extract_table_rows_from_page(page, table)
                table_text = serialize_table(table_rows)

                table_id = f"{source}:page:{page_number}:table:{table_number}"

                records.append(
                    {
                        "record_id": table_id,
                        "source": source,
                        "page_number": page_number,
                        "content_type": "table",
                        "text": table_text,
                        "table_id": table_id,
                    }
                )

                # Create one retrieval record for each data row.
                # The first extracted row contains the column headers.
                if table_rows:
                    headers = table_rows[0]

                    for row_number, row in enumerate(table_rows[1:], start=1):
                        row_text = serialize_table([headers, row])

                        if not row_text:
                            continue

                        records.append(
                            {
                                "record_id": (f"{table_id}:row:{row_number}"),
                                "source": source,
                                "page_number": page_number,
                                "content_type": "table_row",
                                "text": row_text,
                                "table_id": table_id,
                                "row_number": row_number,
                            }
                        )
                        
            page_text = remove_table_regions_from_text(page, tables)

            if page_text:
                records.append(
                    {
                        "record_id": f"{source}:page:{page_number}:text",
                        "source": source,
                        "page_number": page_number,
                        "content_type": "text",
                        "text": page_text,
                    }
                )

    return records
