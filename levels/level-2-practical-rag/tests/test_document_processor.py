from services.document_processor import process_document


def test_document_processor():
    pages = [{"text": "Employees get annual leave.", "page_number": 1}]

    chunk = process_document(pages, 10, 0)

    assert chunk[0]["chunk"] == "Employees get annual leave."
    assert chunk[0]["page_number"] == 1
    assert chunk[0]["chunk_index"] == 0


def test_document_process_single_page_multiple_chunks_without_overlap():
    pages = [
        {
            "text": "Employees get annual leave. Employees can carry forward unused leave.",
            "page_number": 1,
        }
    ]

    chunk = process_document(pages, 5, 0)
    
    assert chunk[0]["chunk"] == "Employees get annual leave. Employees"
    assert chunk[0]["page_number"] == 1
    assert chunk[0]["chunk_index"] == 0
    assert chunk[1]["chunk"] == "can carry forward unused leave."
    assert chunk[1]["page_number"] == 1
    assert chunk[1]["chunk_index"] == 1
    
def test_document_process_multiple_pages():
    pages = [
        {
            "text": "Employees get annual leave.",
            "page_number": 1,
        },
        {
            "text": "Employees get sick leave.",
            "page_number": 2,
        },
    ]

    chunk = process_document(pages, 10, 0)

    assert chunk[0]["chunk"] == "Employees get annual leave."
    assert chunk[0]["page_number"] == 1
    assert chunk[0]["chunk_index"] == 0
    assert chunk[1]["chunk"] == "Employees get sick leave."
    assert chunk[1]["page_number"] == 2
    assert chunk[1]["chunk_index"] == 1
    
def test_document_process_multiple_pages_multiple_chunks():
    pages = [
        {
            "text": "One two three four five six.",
            "page_number": 1,
        },
        {
            "text": "Seven eight nine ten eleven twelve.",
            "page_number": 2,
        },
    ]

    chunk = process_document(pages, 3, 0)

    assert chunk[0]["chunk"] == "One two three"
    assert chunk[0]["page_number"] == 1
    assert chunk[0]["chunk_index"] == 0
    assert chunk[1]["chunk"] == "four five six."
    assert chunk[1]["page_number"] == 1
    assert chunk[1]["chunk_index"] == 1
    assert chunk[2]["chunk"] == "Seven eight nine"
    assert chunk[2]["page_number"] == 2
    assert chunk[2]["chunk_index"] == 2
    assert chunk[3]["chunk"] == "ten eleven twelve."
    assert chunk[3]["page_number"] == 2
    assert chunk[3]["chunk_index"] == 3
    
def test_document_process_empty_page():
    pages = [
        {
            "text": "",
            "page_number": 1,
        },
        {
            "text": "Employees get sick leave.",
            "page_number": 2,
        },
    ]

    chunk = process_document(pages, 10, 0)

    assert chunk[0]["chunk"] == "Employees get sick leave."
    assert chunk[0]["page_number"] == 2
    assert chunk[0]["chunk_index"] == 0
    
def test_document_process_with_overlap():
    pages = [
        {
            "text": "one two three four five six seven eight",
            "page_number": 1,
        }
    ]

    chunk = process_document(pages, 4, 2)

    assert chunk[0]["chunk"] == "one two three four"
    assert chunk[0]["page_number"] == 1
    assert chunk[0]["chunk_index"] == 0
    assert chunk[1]["chunk"] == "three four five six"
    assert chunk[1]["page_number"] == 1
    assert chunk[1]["chunk_index"] == 1
    assert chunk[2]["chunk"] == "five six seven eight"
    assert chunk[2]["page_number"] == 1
    assert chunk[2]["chunk_index"] == 2