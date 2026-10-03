from pypdf import PdfReader

def extract_text_from_pdf(filepath):
    pdf_reader = PdfReader(filepath)
    
    results = []
    for page_number, page in enumerate(pdf_reader.pages, start=1):
        text = page.extract_text()
        
        if text:
            results.append({
             "text": text,
             "page_number": page_number,
            })
            
    return results