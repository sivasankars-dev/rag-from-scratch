from services.document_processor_with_source_policy import process_document


def test_document_processor_with_source_policy():
    pages = [{"text": "Employees get annual leave.", "page_number": 1}]

    chunk = process_document(pages, 10, 0, "employee_handbook.pdf", "hr_policy")

    assert chunk[0]["chunk"] == "Employees get annual leave."
    assert chunk[0]["page_number"] == 1
    assert chunk[0]["chunk_index"] == 0
    assert chunk[0]["source"] == "employee_handbook.pdf"
    assert chunk[0]["document_type"] == "hr_policy"

def test_document_processor_multiple_chunks_without_overlap():
    pages = [
        {
            "text": "Employees get annual leave. Employees can carry forward unused leave.",
            "page_number": 1,
        }
    ]

    chunk = process_document(pages, 5, 0, "employee_handbook.pdf", "hr_policy")
    
    assert chunk[0]["chunk"] == "Employees get annual leave. Employees"
    assert chunk[0]["page_number"] == 1
    assert chunk[0]["chunk_index"] == 0
    assert chunk[0]["source"] == "employee_handbook.pdf"
    assert chunk[0]["document_type"] == "hr_policy"
    assert chunk[1]["chunk"] == "can carry forward unused leave."
    assert chunk[1]["page_number"] == 1
    assert chunk[1]["chunk_index"] == 1
    assert chunk[1]["source"] == "employee_handbook.pdf"
    assert chunk[1]["document_type"] == "hr_policy"
    