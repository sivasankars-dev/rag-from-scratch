from pathlib import Path

from services.document_loader import extract_text_from_pdf
from services.document_processor_with_source_policy import process_document
from services.embedding_service import EmbeddingService
from services.vector_store import VectorStore


BASE_DIR = Path(__file__).resolve().parents[1]

PDF_PATH = (
    BASE_DIR.parent.parent
    / "data"
    / "documents"
    / "rag_practice_employee_handbook.pdf"
)

CHROMA_PATH = BASE_DIR / "data" / "chroma_employee_handbook"

SOURCE = "rag_practice_employee_handbook.pdf"
DOCUMENT_TYPE = "employee_handbook"


def main():
    # 1. Extract text from the PDF.
    pages = extract_text_from_pdf(PDF_PATH)
    print(f"Pages extracted: {len(pages)}")

    # 2. Convert pages into chunks with metadata.
    chunks = process_document(
        pages=pages,
        chunk_limit=100,
        overlap=20,
        source=SOURCE,
        document_type=DOCUMENT_TYPE,
    )
    print(f"Chunks created: {len(chunks)}")

    if not chunks:
        raise ValueError("No text chunks were extracted from the PDF.")

    # 3. Generate embeddings for all chunks.
    embedding_service = EmbeddingService()
    embeddings = embedding_service.embed_texts(
        [chunk["chunk"] for chunk in chunks]
    )
    print(f"Embeddings created: {len(embeddings)}")

    # 4. Store chunks in a separate Chroma collection.
    vector_store = VectorStore(
        persist_directory=str(CHROMA_PATH),
        collection_name="employee_handbook_evaluation",
    )
    vector_store.upsert_processed_chunks(chunks, embeddings)

    # 5. Verify the stored data.
    stored_count = vector_store.collection.count()
    print(f"Chunks stored in Chroma: {stored_count}")

    if stored_count != len(chunks):
        raise RuntimeError(
            f"Expected {len(chunks)} chunks, but found {stored_count}."
        )

    print("Handbook ingestion completed successfully.")


if __name__ == "__main__":
    main()
