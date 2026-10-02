def chunk_text_with_overlap(text, chunk_limit, overlap=0):
    if chunk_limit <= 0:
        raise ValueError("chunk_limit must be greater than 0")

    if overlap < 0:
        raise ValueError("overlap cannot be negative")

    if overlap >= chunk_limit:
        raise ValueError("overlap must be less than chunk_limit")

    words = text.split()

    if not words:
        return []
    
    chunks = []
    step = chunk_limit - overlap
    
    for start in range(0, len(words), step):
        chunk = words[start: start+chunk_limit]
        
        chunks.append(" ".join(chunk))
        if start + chunk_limit >= len(words):
            break
        
    return chunks

