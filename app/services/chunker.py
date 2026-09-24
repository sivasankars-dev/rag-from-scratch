

def chunk_text(text: str, chunk_size=500, chunk_overlap=50):
    if chunk_size < 0:
        raise ValueError("Chunk size shoudn't be less than 0")
    if chunk_overlap < 0:
        raise ValueError("Chunk overlap size can't be negative.")
    if chunk_size <= chunk_overlap:
        raise ValueError("Chunkoverlap size must be less than chunk_size")

    chunks = []
    start = 0

    while start < len(text):
        end = start + chunk_size

        chunk = text[start:end]
        if chunk.strip():
            chunks.append(chunk.strip())

        start = end - chunk_overlap

    return chunks
