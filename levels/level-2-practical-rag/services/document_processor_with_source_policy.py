from services.overlap_chunker import chunk_text_with_overlap


def process_document(pages, chunk_limit, overlap=0, source="", document_type=""):
    """Process page-level records into chunks with page and chunk metadata."""
    results = []
    chunk_index = 0
    
    for page in pages:
        chunks = chunk_text_with_overlap(page["text"], chunk_limit, overlap)
        
        for chunk in chunks:
            results.append({
                "chunk": chunk,
                "page_number": page["page_number"],
                "chunk_index": chunk_index, 
                "source":source,
                "document_type": document_type
            })
            
            chunk_index += 1
            
    return results