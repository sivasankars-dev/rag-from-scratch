# Step 1 — Project setup and FastAPI foundation

> Level 1 learning note: this chapter preserves its original checkpoint. Steps 1–17 are now complete; see the [learning index](../../../README.md#level-1-learning-sequence). Commands below run from the repository root and select Level 1 with `PYTHONPATH`. Shared data remains under root `data/`.

## What are we learning, and why?

We are building the retrieval part of RAG from Python building blocks. A working environment lets us run small experiments and understand each transformation before adding more behavior.

## Simple explanation

Think of a project as a workshop. A virtual environment is its own toolbox: changing tools here does not change another workshop. `uv` installs and organizes those tools. FastAPI is the reception desk that accepts HTTP requests and sends responses.

## Technical explanation

`.venv` contains a Python interpreter link and project-specific packages. `pyenv` selects the underlying Python installation; it does not replace dependency management. `pyproject.toml` declares project metadata, the Python requirement and direct dependencies. `uv.lock` records resolved versions, platform conditions and artifact hashes, including indirect dependencies. Exact pins constrain selected packages; the lock also fixes packages declared with minimum versions. Commit both files, not the virtual environment.

FastAPI creates an ASGI application in `levels/level-1-fundamentals/app/main.py`; Uvicorn runs it. Route decorators associate HTTP methods and paths with Python functions. `UploadFile` represents an uploaded multipart file, and `HTTPException` creates an HTTP error response. Python dictionaries become JSON responses.

## Project structure

```text
levels/level-1-fundamentals/app/main.py                    FastAPI health and PDF upload routes
levels/level-1-fundamentals/services/document_loader.py PDF text extraction
levels/level-1-fundamentals/services/chunker.py         Character-based windows
levels/level-1-fundamentals/services/embedding_service.py Sentence Transformer wrapper
levels/level-1-fundamentals/services/vector_store.py    Persistent Chroma wrapper
levels/level-1-fundamentals/scripts/ Runnable learning experiments
levels/level-1-fundamentals/tests/test_embedding.py        Original empty placeholder (under tests/)
data/documents/                 Two sample PDF inputs
data/chroma/                    Generated local database, ignored
data/uploads/                  Generated uploads, ignored
levels/level-1-fundamentals/docs/    Learning notes
pyproject.toml                  Dependency declarations
uv.lock                         Resolved dependency graph
```

## Dependencies and environment setup

Verified environment: macOS arm64, Python 3.12.3 (pyenv), uv 0.7.20. Project metadata says `fastapi-rag-poc` version 0.1.0 and Python `>=3.12`; that range does not guarantee every newer Python supports these older binary dependencies. Use the verified 3.12.3 environment for this exercise.

| Dependency | Installed and locked version | Purpose |
| --- | --- | --- |
| FastAPI | 0.141.1 | HTTP application |
| Uvicorn | 0.53.0 | ASGI server, indirect dependency |
| pypdf | 6.19.0 | PDF parsing |
| python-multipart | 0.0.32 | Upload parsing |
| sentence-transformers | 5.2.3 | Text embeddings |
| transformers | 4.47.1 | Model/tokenizer components |
| torch | 2.4.1 | Tensor/model execution |
| chromadb | 1.5.9 | Persistent vector search |
| onnxruntime | 1.22.0 | Chroma dependency compatibility |

The learning journey included macOS ARM, Torch and ONNX Runtime/Chroma compatibility problems. These versions now import and run together locally. The original error logs are unavailable; no specific failed versions are inferred. Keep the working pins and lock rather than blindly upgrading.

From the repository root, for a fresh environment with Python 3.12.3 already installed:

```bash
uv sync --locked --python 3.12.3
```

For the existing environment:

```bash
source .venv/bin/activate
python --version
PYTHONPATH=levels/level-1-fundamentals python -m uvicorn app.main:app --reload
```

Visit `http://127.0.0.1:8000/docs` for the existing upload interface, or `http://127.0.0.1:8000/health`. The health response is `{"status":"ok"}`. Stop the server with Ctrl+C. These commands use the root as the working directory because data paths are relative.

## What we implemented

`GET /health` checks the app is responding. `POST /documents/upload` saves a PDF, extracts text and returns character chunks. It does not embed or ingest the upload into Chroma. Ingestion and retrieval run separately through scripts.

There were no local commits or remote branch heads at inspection. The first commit records the already-existing Step 1–7 code as a baseline, rather than pretending it was implemented anew in seven stages. Later commits document each learning step and the small corrections discovered during validation.

## Common beginner mistakes

- Installing packages into a different interpreter instead of `.venv`.
- Assuming `requires-python >=3.12` proves all newer interpreters work.
- Forgetting to select Level 1 on the Python import path. Use `PYTHONPATH=levels/level-1-fundamentals uv run python -m scripts.run_retrieve` from the repository root so the level’s packages and shared data resolve correctly.
- Committing secrets, `.venv`, upload copies or generated vector databases. `.gitignore` excludes the actual generated directories.
- Treating the empty original test file as a passing test suite. The scripts are experiments, not assertions.

## What I learned

A reproducible environment and a small HTTP app provide a foundation. Framework setup does not implement retrieval automatically; the services and scripts do that work explicitly.

## Interview questions

1. Why use a virtual environment? To isolate project packages from other Python environments.
2. Why keep both dependency files? One declares intent; the other records the resolved environment.
3. What serves FastAPI? An ASGI server such as Uvicorn.
4. Why run a script as a module? It preserves package imports from the project root.

## Next step

[Step 2 — PDF to text](02-pdf-to-text.md).
