from pathlib import Path
from services.document_loader import extract_text_from_pdf

pdf_path = Path("../../data/documents/company_policy.pdf")

pages = extract_text_from_pdf(pdf_path)

print(f"Extracted pages: {len(pages)}")

for page in pages:
    print(f"\n--- Page {page['page_number']} ---")
    print(page["text"][:300])