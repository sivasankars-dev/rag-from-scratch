from pathlib import Path
from services.document_loader import extract_text_from_pdf
import pytest

def test_text_extract_from_pdf():
    pdf_path = Path("../../data/documents/company_policy.pdf")
    
    pages = extract_text_from_pdf(pdf_path)
    
    assert isinstance(pages, list)
    assert len(pages) > 0
    
    for page in pages:
        assert "text" in page
        assert "page_number" in page 

def test_text_extract_from_pdf_file_path_not_found():
    pdf_path = Path("../../data/documents/missing.pdf")
    
    with pytest.raises(FileNotFoundError):
        extract_text_from_pdf(pdf_path)
            
def test_text_extract_from_pdf_page_is_not_empty():
    pdf_path = Path("../../data/documents/company_policy.pdf")
    
    pages = extract_text_from_pdf(pdf_path)
    
    for page in pages:
        assert len(page["text"]) > 0
    
    