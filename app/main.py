from fastapi import FastAPI, UploadFile, HTTPException

from pathlib import Path
from app.services.document_loader import extract_text_from_pdf
from app.services.chunker import chunk_text

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

    file_path = upload_path / file.filename

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
