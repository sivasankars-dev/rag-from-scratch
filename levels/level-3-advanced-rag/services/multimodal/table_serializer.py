"""Convert extracted PDF tables into readable, retrieval-friendly text."""

import re


def normalize_cell(value):
    if value is None:
        return ""

    text = str(value).replace("\u00a0", " ")
    text = re.sub(r"\s+", " ", text).strip()

    # Repair cells such as "SEV1 -" and "SEV1-".
    text = re.sub(
        r"\b(SEV)\s*[- ]?\s*(\d)\s*-?\s*$",
        r"\1-\2",
        text,
        flags=re.IGNORECASE,
    )

    return text


def serialize_table(rows):
    """Serialize table rows into labeled, readable text."""
    if not isinstance(rows, (list, tuple)) or not rows:
        return ""

    normalized_rows = []

    for row in rows:
        if not isinstance(row, (list, tuple)):
            raise ValueError("Every table row must be a list or tuple")

        normalized_rows.append([normalize_cell(cell) for cell in row])

    headers = normalized_rows[0]

    if not any(headers):
        raise ValueError("Table header row must contain at least one value")

    lines = ["Table"]

    for row_number, row in enumerate(normalized_rows[1:], start=1):
        cells = []

        for column_number, value in enumerate(row):
            header = headers[column_number] if column_number < len(headers) else ""
            label = header or f"Column {column_number + 1}"
            cells.append(f"{label}: {value or 'Not specified'}")

        lines.append(f"Row {row_number}: " + "; ".join(cells))

    return "\n".join(lines)