from fastapi import FastAPI, UploadFile, HTTPException, Depends

from pathlib import Path
from app.services.document_loader import extract_text_from_pdf
from app.services.chunker import chunk_text
from app.services.embedding_service import EmbeddingService
from app.services.retrieval_controls_vector_store import VectorStore
from app.dependencies import get_embedding_service, get_vector_store
from app.schemas.retrieval import RetrievalRequest, RetrievalResponse

app = FastAPI(
    title="FastAPI RAG PoC",
    version="0.1.0",
)


@app.get("/health")
async def health_check():
    return {"status": "ok"}

@app.post("/documents/upload")
async def document_upload(file: UploadFile):
    if not file.filename:
        raise HTTPException(status_code=400, detail="File upload is mandatory.")

    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="PDF file only allowed.")

    upload_path = Path("docs/uploads")
    upload_path.mkdir(parents=True, exist_ok=True)

    file_path = upload_path / Path(file.filename).name

    contents = await file.read()
    file_path.write_bytes(contents)

    text = extract_text_from_pdf(file_path)

    chunks = chunk_text(
        text,
        chunk_size=100,
        chunk_overlap=10
        )

    return {
        "filename": file.filename,
        "text_length": len(text),
        "chunk_count": len(chunks),
        "chunks": chunks
    }

@app.post("/retrieve", response_model=RetrievalResponse)
async def retrieve(request:RetrievalRequest, embedding_service: EmbeddingService=Depends(get_embedding_service), vector_store:VectorStore=Depends(get_vector_store)):
    query = request.query.strip()
    source = request.source.strip() if request.source else None
    if not query:
        raise HTTPException(status_code=400, detail="Query doesn't be empty.")
    
    query_embedding = embedding_service.embed_text(query)

    results = vector_store.search(query_embedding=query_embedding, top_k=request.top_k, source=source, similarity_threshold=request.similarity_threshold)

    print("Question:")
    print(query)

    print("\nRetrieved results:")
    if not results:
        print("No relevant documents found.")
        return {
            "query": query,
            "results": []
        }

    return {
        "query": query,
        "results": results,
    }
    