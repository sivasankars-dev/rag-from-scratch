from pathlib import Path

from services.document_loader import extract_text_from_pdf
from services.chunker import chunk_text
from services.embedding_service import EmbeddingService
from services.vector_store import VectorStore


def main():
    file_path = Path("data/documents/company_policy.pdf")

    # extract text from file path
    text_extracts = extract_text_from_pdf(file_path)
    print("Extracted characters:", len(text_extracts))

    # split texts into chunks
    chunks = chunk_text(text_extracts, chunk_size=100, chunk_overlap=20)
    print("Number of chunks:", len(chunks))

    for index, chunk in enumerate(chunks):
        print("\n" + "=" * 60)
        print(f"Chunk {index}")
        print(chunk)

    # generate embeddings
    embedding_service = EmbeddingService()

    embeddings = embedding_service.embed_texts(chunks)

    print("\nEmbedding dimension:", len(embeddings[0]))

    # Store to vector store
    vector_store = VectorStore()

    vector_store.upsert_chunks(
        chunks=chunks,
        embeddings=embeddings,
        source=file_path.name
    )

    print("\nStored successfully in ChromaDB.")

if __name__ == "__main__":
    main()
