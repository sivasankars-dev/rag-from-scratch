from pathlib import Path

from pypdf import PdfReader

def extract_text_from_pdf(file_path):
    pdf_reader = PdfReader(file_path)

    pages = []

    for page in pdf_reader.pages:
        text = page.extract_text()
        if text:
            pages.append(text)

    return "/n".join(pages)
