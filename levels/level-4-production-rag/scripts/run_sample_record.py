from services.embedding_service import EmbeddingService


def main():
    service = EmbeddingService()

    text = "Remote work requires manager approval."
    vector = service.embed_text(text)

    record = {
        "chunk_id": "handbook-page3-chunk0",
        "text": text,
        "embedding": vector,
        "source": "handbook.pdf",
        "page_number": 3,
    }

    print("Chunk ID:", record["chunk_id"])
    print("Text:", record["text"])
    print("Source:", record["source"])
    print("Page:", record["page_number"])
    print("Dimensions:", len(record["embedding"]))

if __name__ == "__main__":
    main()