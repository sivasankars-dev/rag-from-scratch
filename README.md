# RAG From Scratch

Learn retrieval-augmented generation (RAG) by building its core pieces in Python. This repository starts with explicit parsing, chunking, embeddings and vector search so we can understand what happens internally before learning higher-level frameworks.

**Current milestone: Level 1, Steps 1–12 documented.** Basic end-to-end RAG now connects retrieval, context building, prompt construction and LLM generation through a Python service. The Python project is named `fastapi-rag-poc` (0.1.0); the GitHub repository is `rag-from-scratch`.

## Current architecture

```text
PDF → Text Extraction → Character Chunking → Embeddings → ChromaDB
                                                           ↑
User Query → Query Embedding ───────────────────────────────┘
                                                           ↓
                                      Top-K Candidates → Similarity Threshold → Results or []
```

For Step 8, an optional source filter is passed into Chroma using `where` before Top-K candidates are selected. The similarity threshold is applied to the returned candidates. See [Step 8](docs/08-retrieval-controls.md).

Ingestion uses 100-character chunks with 20-character overlap. The sample PDF produces 343 characters and five chunks. `all-MiniLM-L6-v2` produces 384-dimensional vectors; Chroma stores them in the persistent `documents_cosine` collection using cosine distance.

The FastAPI app has health, PDF-upload and `POST /retrieve` routes. Uploads only extract/chunk text (overlap 10); ingestion runs through a script. Retrieval is available through the API or the existing learning scripts. See the [architecture walkthrough](docs/architecture.md).

Separate generation building block (Steps 10–11):

```text
Manual prompt → LLMService → OpenAI Responses API → generated text
                                                → usage → cost estimate → console
```

Step 12 now connects retrieval to generation through `RAGService`; see [RAG Orchestration and Integration](docs/12-rag-orchestration.md). The [Step 11 notes](docs/11-llm-usage-and-cost-monitoring.md) explain the current estimate limitations and the outdated cost-demo call.

## Current progress and learning notes

| Step | Topic | Status |
| --- | --- | --- |
| 1 | [Project Setup](docs/01-project-setup.md) | Complete |
| 2 | [PDF → Text](docs/02-pdf-to-text.md) | Complete |
| 3 | [Chunking](docs/03-chunking.md) | Complete |
| 4 | [Embeddings](docs/04-embeddings.md) | Complete |
| 5 | [Cosine Similarity](docs/05-cosine-similarity.md) | Complete |
| 6 | [ChromaDB](docs/06-chromadb.md) | Complete |
| 7 | [Semantic Retrieval](docs/07-retrieval.md) | Complete |
| 8 | [Retrieval Controls](docs/08-retrieval-controls.md) | Complete |
| 9 | [Retrieval API](docs/09-retrieval-api.md) | Complete |
| 10 | [LLM Generation](docs/10-llm-generation.md) | Complete / documented (standalone) |
| 11 | [LLM Usage & Cost Monitoring](docs/11-llm-usage-and-cost-monitoring.md) | Complete / documented (basic estimate; limitations noted) |
| 12 | [RAG Orchestration and Integration](docs/12-rag-orchestration.md) | Complete (happy-path integration verified) |

Each note explains the idea, a simple analogy, the actual code, trade-offs, mistakes and interview questions. The history begins by recording the already-existing implementation, followed by step-specific documentation and small verified corrections. It does not claim the original implementation was written during this documentation pass.

## Technology stack

Versions below were checked against the local environment and `uv.lock`; dependencies were not upgraded.

| Technology | Verified version | Role |
| --- | --- | --- |
| Python (pyenv) | 3.12.3 | Runtime on macOS arm64 / M2 |
| uv | 0.7.20 | Environment and dependency management |
| FastAPI | 0.141.1 | Existing HTTP routes |
| Uvicorn | 0.53.0 | HTTP/ASGI server |
| pypdf | 6.19.0 | PDF text extraction |
| python-multipart | 0.0.32 | File upload parsing |
| sentence-transformers | 5.2.3 | Embedding model wrapper |
| transformers | 4.47.1 | Model/tokenizer support |
| torch | 2.4.1 | Model execution |
| ChromaDB | 1.5.9 | Persistent vector storage/search |
| ONNX Runtime | 1.22.0 | Chroma dependency compatibility |
| OpenAI SDK | 3.19.2 | Standalone Responses API generation |

`pyproject.toml` declares Python `>=3.12`, but this environment was validated with 3.12.3. The macOS ARM compatibility journey is described in [Step 1](docs/01-project-setup.md). LangChain and LangGraph are not used.

## How to run

Run every command from the repository root. Python 3.12.3 and uv should already be installed. To reproduce the locked environment:

```bash
uv sync --locked --python 3.12.3
source .venv/bin/activate
```

The existing environment was checked with a sync dry run; it required no changes. First-time setup and the first model load may need network access. The public embedding model downloads to the Hugging Face cache. Local embedding/retrieval needs no API key. The separate LLM scripts require `OPENAI_API_KEY` and make paid network calls.

Start FastAPI:

```bash
python -m uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000/health` or the interactive `http://127.0.0.1:8000/docs` page. `POST /documents/upload` accepts a PDF and returns text length and chunks. It saves uploaded files in ignored `docs/uploads/`. Stop the server with Ctrl+C.

Ingest the sample and run the original Step 7 retrieval:

```bash
python -m scripts.ingest_document
python -m scripts.inspect_chroma
python -m scripts.retrieve
```

Ingestion creates the ignored `data/chroma/` database. Run it before retrieval. The fixed sample question is **“How many annual leave days do I get?”**. Step 7 results:

| Rank | Chunk index | Cosine distance ↓ | Cosine similarity ↑ |
| --- | --- | --- | --- |
| 1 | 0 | 0.284997 | 0.715003 |
| 2 | 2 | 0.323565 | 0.676435 |

Both come from `company_policy.pdf`; the first includes “20 days of annual leave per year.” Distances and similarities are related by `similarity = 1 - distance`. They are not probabilities. See [the measured experiment](docs/07-retrieval.md) for the full chunks and limitations.

Step 8 keeps a separate implementation for learning: `app/services/retrieval_controls_vector_store.py` and `scripts/retrieval_control_retrieve.py`. Step 7 still uses `app/services/vector_store.py` and `scripts/retrieve.py`.

Run Step 8:

```bash
python -m scripts.retrieval_control_retrieve
```

It requests `top_k=5`, restricts the source to `company_policy.pdf`, and uses the default similarity threshold of `0.50`. The search method returns a list of accepted passages, or `[]` if none pass the current settings; the script prints the results or a no-results message. An empty result does not prove the knowledge base has no answer. See [Step 8's recorded experiments](docs/08-retrieval-controls.md).

Step 9 exposes the Step 8 logic through `POST /retrieve`. After ingestion, start FastAPI as above and use **POST /retrieve → Try it out** at `/docs`, or send:

```bash
curl -X POST http://127.0.0.1:8000/retrieve \
  -H 'Content-Type: application/json' \
  -d '{"query":"How many annual leave days do I get?","top_k":5,"source":"company_policy.pdf","similarity_threshold":0.5}'
```

The API accepts Top-K from **1 to 20** and thresholds from **0 to 1**, inclusive. Defaults are `5` and `0.5`; source is optional. Invalid ranges and non-finite thresholds return HTTP **422** when dependencies initialize successfully. Blank queries return **400**. A completed search returns **200** with the trimmed query and `results`, which may be empty. This returns passages, not an LLM answer. See [Step 9](docs/09-retrieval-api.md) for schemas, examples and known limitations.

Optional learning experiments:

```bash
python -m scripts.test_embedding
python -m scripts.test_similarity
python -m scripts.test_chroma
```

The Chroma demo now uses temporary storage, so it does not overwrite ingested PDF chunks. Use module syntax (`-m`) to avoid the import problems encountered when running script file paths directly.

For the new standalone generation experiments, configure `OPENAI_API_KEY` in your environment or ignored local `.env` file, then run:

```bash
python -m scripts.test_llm
python -m scripts.llm_cache_test
```

These are manual, paid API experiments, not offline unit tests. See [Step 10](docs/10-llm-generation.md) for setup and scope. No saved live result transcript is available. The separate `scripts/test_cost_calculator.py` currently uses an outdated method signature and fails; the working calculator interface and its limitations are documented in [Step 11](docs/11-llm-usage-and-cost-monitoring.md).

## Tests and validation

```bash
python -m unittest discover -s tests -v
```

The existing eight tests exercise the Step 7 implementation; they do not cover the separate Step 8 controls or `/retrieve`. Temporary review checks of Step 8 and the API, including the validation fixes, passed; these are documented in [Step 9](docs/09-retrieval-api.md). They cover chunking, PDF extraction, the existing upload route, cosine storage and the complete real-model retrieval path. Tests use standard-library `unittest` and the already-installed FastAPI test client; no test framework was added. After the model is cached, an offline run is available:

```bash
HF_HUB_OFFLINE=1 python -m unittest discover -s tests -v
```

See [validation and small fixes](docs/validation.md). The important correction was `hsnw` → `hnsw`: the old collection used L2 despite its name. The old local database was preserved in ignored `data/chroma-backup-before-cosine/`, and the current cosine database was rebuilt from the PDF. Fresh clones need only run ingestion.

## Repository layout

```text
app/                 FastAPI app and small RAG services
scripts/             Ingestion, inspection, retrieval and learning experiments
tests/               Focused regression/integration checks
data/documents/      Sample PDFs (company_policy.pdf is the ingestion input)
docs/                Steps 1–12, architecture and validation
pyproject.toml       Project metadata and dependency requirements
uv.lock              Resolved dependency versions
```

`.venv/`, caches, `.env` files, uploaded copies, `.DS_Store` and local Chroma databases are ignored. The original empty `tests/test_embedding.py` is retained as a placeholder; the integration test exercises embeddings.

## Learning roadmap and stop point

```text
LEVEL 1 — RAG Fundamentals
  Steps 1–9 complete
  Step 10 — LLM Generation: complete / documented (standalone)
  Step 11 — LLM Usage & Cost Monitoring: complete / documented (basic estimate)
  Step 12 — Context, Prompt Building & RAG Orchestration: complete
  Later features remain outside this checkpoint

LEVEL 2 — Practical RAG Engineering
LEVEL 3 — Advanced RAG
LEVEL 4 — Production RAG Engineering
```

The basic answer path now runs through `RAGService`: question → embedding → retrieval controls → context → prompt → LLM → answer. The reported happy-path answer was “You get 20 days of annual leave per year.” This is one successful example, not a guarantee for all questions.

With the sample already ingested and the local environment configured, run the paid integration smoke test:

```bash
uv run python -m scripts.test_rag_service
```

Use `TOKENIZERS_PARALLELISM=false` in the ignored local `.env` to explicitly disable tokenizer parallelism. `/chat`, source/citation responses and advanced RAG features remain unimplemented. See [Step 12](docs/12-rag-orchestration.md) for setup, the tokenizer warning and current limitations.
