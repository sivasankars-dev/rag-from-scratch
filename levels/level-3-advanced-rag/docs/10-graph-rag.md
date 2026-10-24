# Graph RAG with Neo4j

## 1. Objective

Traditional vector RAG retrieves text chunks based on semantic similarity. Hybrid RAG combines vector retrieval with keyword-based retrieval.

Graph RAG represents entities and their relationships as a knowledge graph. Instead of relying only on matching text chunks, it can retrieve evidence through connections between entities.

For example, an employee handbook may contain the statement:

> Company equipment must not be left unattended in public locations.

A graph representation can express this information as:

```text
Company Equipment
    |
    | MUST_NOT_BE_LEFT_UNATTENDED_IN
    v
Public Locations
```

This Level 3 implementation adds a basic Graph RAG workflow using an LLM for entity and relationship extraction and Neo4j for graph storage and retrieval.

The implementation uses the existing employee handbook and Level 2 PDF loader. It is an initial working implementation, not a claim that Graph RAG is better than vector or hybrid RAG.

## 2. High-Level Architecture

```text
Employee Handbook PDF
         |
         v
Level 2 PDF Text Loader
         |
         v
Document Section Parser
         |
         v
Selected Handbook Sections
         |
         v
LLM Graph Extractor
         |
         +----------------------+
         |                      |
         v                      v
      Entities             Relationships
         |                      |
         +----------+-----------+
                    |
                    v
             Neo4j Graph Store
                    |
                    v
              Knowledge Graph

User Question
      |
      v
Graph Retrieval Service
      |
      v
Ranked Graph Evidence
      |
      v
Graph RAG Service
      |
      v
Grounded Answer + Source Information
```

The ingestion and question-answering workflows are separate:

- **Ingestion:** parses selected document sections, extracts entities and relationships, and stores them in Neo4j.
- **Querying:** matches question terms to graph entities, traverses relationships, ranks evidence, and asks the LLM to generate an answer from the retrieved evidence.

## 3. Graph Data Model

### 3.1 Nodes

File: `services/graph_store.py`

The graph uses two main node labels.

| Label | Purpose |
|---|---|
| `Entity` | Stores a person, role, organization, policy, system, process, benefit, time period, location, or other extracted concept. |
| `DocumentChunk` | Stores the source text and document metadata associated with an extracted section. |

Entity nodes contain fields such as:

- `id`: normalized entity identifier.
- `name`: readable entity name.
- `type`: entity category.

Document chunk nodes contain fields such as:

- `id`: stable identifier for the source section.
- `text`: original section text.
- `source`: source document name.
- `section_id`: document section identifier.
- `section_title`: section heading.
- `section_path`: hierarchical section path.
- `start_page` and `end_page`: source page range.

### 3.2 Relationships

The graph uses two relationship patterns:

- `MENTIONS`: connects a `DocumentChunk` to an entity mentioned in its text.
- Extracted relationship types: connect one entity to another entity.

An extracted relationship stores its predicate and evidence, along with identifiers linking it to the source chunk.

Example:

```text
(DocumentChunk)
       |
       | MENTIONS
       v
(Company Equipment)
       |
       | MUST_NOT_BE_LEFT_UNATTENDED_IN
       v
(Public Locations)
```

The relationship predicate describes the connection between the two entities. The evidence records the source text supporting that connection.

The predicate is validated before being used to construct a Cypher query. This helps prevent arbitrary relationship names from being inserted into the query.

### 3.3 Why Preserve Evidence?

A graph relationship alone may not contain enough information to answer a question reliably.

For example, a relationship between an employee and a policy is more useful when the system also retains the sentence supporting that relationship.

This implementation validates extracted evidence against the original section text and stores source metadata so that retrieved evidence can be traced back to the handbook.

## 4. Components

### 4.1 Graph Extractor

File: `services/graph_extractor.py`

`GraphExtractor` uses the existing LLM client to extract entities and relationships from a text section.

The extractor:

1. Sends the section text to the LLM with extraction instructions.
2. Parses the returned JSON, including JSON enclosed in Markdown code fences.
3. Validates entity names and entity types.
4. Validates that relationship endpoints refer to extracted entities.
5. Checks that relationship evidence appears in the original text after normalization.
6. Removes duplicate entities and relationships.
7. Builds normalized entity identifiers.

Supported entity categories include `PERSON`, `ROLE`, `ORGANIZATION`, `POLICY`, `SYSTEM`, `PROCESS`, `BENEFIT`, `TIME_PERIOD`, `LOCATION`, and `OTHER`.

The extractor returns entities, relationships, and the supplied source metadata.

The LLM can still misclassify an entity or extract a semantically awkward relationship. Validation reduces some structural errors but does not guarantee that every extracted fact is correct.

### 4.2 Neo4j Graph Store

File: `services/graph_store.py`

`Neo4jGraphStore` persists the extracted graph in Neo4j.

Its responsibilities include:

1. Creating uniqueness constraints for entity and document-chunk identifiers.
2. Validating extraction data before writing.
3. Generating a stable chunk identifier from the source and section identity, or from the source and text when a section identity is unavailable.
4. Creating or updating the source `DocumentChunk`.
5. Merging entity nodes.
6. Creating `MENTIONS` and extracted entity-to-entity relationships.
7. Replacing the existing relationships associated with a chunk during re-ingestion.

The store uses a Neo4j transaction for its graph write operations. Re-ingestion is designed to update the selected source chunk rather than create a new chunk on every run.

Entity nodes that are no longer referenced can remain in the graph. Removing all obsolete or orphaned entities is not currently a separate cleanup operation.

### 4.3 Graph Retrieval

File: `services/graph_retrieval.py`

The graph retriever performs the following steps:

1. Normalizes the question into tokens.
2. Loads entity information from Neo4j.
3. Matches question terms against entity names.
4. Traverses relationships from matched entities up to the configured hop limit.
5. Collects relationship evidence and source metadata.
6. Scores and ranks the collected evidence.
7. Returns the top results.

The current scoring function combines several lexical signals:

- Entity overlap.
- Evidence-text overlap.
- Relationship overlap.
- Section-title overlap.

The implementation also uses lightweight token normalization for selected word forms and preserves negation terms such as `not`.

This is a baseline lexical graph retriever. It is not a learned graph-ranking model, and it does not perform general-purpose semantic entity linking.

### 4.4 Graph RAG Service

File: `services/graph_rag_service.py`

`GraphRAGService` connects graph retrieval to answer generation.

The service:

1. Retrieves ranked graph evidence.
2. Formats the evidence with source, section, page, relationship, and supporting text information.
3. Returns an insufficient-evidence response if no evidence is retrieved.
4. Otherwise, asks the LLM to answer using the supplied evidence.

The final answer can include a citation identifying the source document, section, and page.

A grounded-answer prompt and source metadata improve traceability, but they do not independently guarantee that every generated claim is correct.

### 4.5 Command-Line Scripts

| File | Purpose |
|---|---|
| `scripts/run_graph_ingestion.py` | Parses the handbook and ingests selected sections into Neo4j. |
| `scripts/run_graph_rag.py` | Runs a question against the stored knowledge graph and generates an answer. |

The ingestion script reuses the existing Level 2 PDF loader and Level 3 document section parser. It does not duplicate PDF extraction or section parsing logic.

The query script loads Neo4j connection settings from the project's `.env` file and reuses the existing Level 2 LLM client.

### 4.6 Dependency and Configuration

Neo4j Python driver dependency:

```toml
"neo4j>=6.4.1"
```

The application reads these environment variables from `.env`:

- `NEO4J_URI`
- `NEO4J_USERNAME`
- `NEO4J_PASSWORD`
- `OPENAI_API_KEY` for the configured LLM client.

Do not commit `.env` or expose its credentials in logs or documentation.

The Neo4j instance must be running and reachable before ingestion or question-answering commands are executed.

## 5. Running Graph RAG

Run commands from the repository root.

### 5.1 Inspect Ingestion Options

```bash
PYTHONPATH=levels/level-3-advanced-rag uv run python \
  levels/level-3-advanced-rag/scripts/run_graph_ingestion.py \
  --help
```

### 5.2 Preview a Section Without Writing

```bash
PYTHONPATH=levels/level-3-advanced-rag uv run python \
  levels/level-3-advanced-rag/scripts/run_graph_ingestion.py \
  --section-number 2.2 \
  --dry-run
```

The dry run parses the document and lists the selected section. It does not call the LLM or write graph data.

Observed output:

```text
Parsed sections: 65
Selected sections: 1
- rag_practice_employee_handbook.pdf::section::2_2 | Remote Work | pages 3-3

Dry run complete. No LLM calls or Neo4j writes performed.
```

### 5.3 Ingest One Section

```bash
PYTHONPATH=levels/level-3-advanced-rag uv run python \
  levels/level-3-advanced-rag/scripts/run_graph_ingestion.py \
  --section-number 2.2
```

This command makes an LLM call and writes the extracted graph data to Neo4j.

Observed output:

```text
Parsed sections: 65
Selected sections: 1
- rag_practice_employee_handbook.pdf::section::2_2 | Remote Work | pages 3-3
[1/1] OK rag_practice_employee_handbook.pdf::section::2_2: 6 entities, 4 relationships

Ingestion summary
Successful sections: 1
Failed sections: 0
```

This run successfully processed one section and stored six entities and four extracted relationships.

The counts describe this ingestion run, not the total number of nodes and relationships across the entire Neo4j database.

### 5.4 Run a Graph RAG Question

```bash
PYTHONPATH=levels/level-3-advanced-rag uv run python \
  levels/level-3-advanced-rag/scripts/run_graph_rag.py \
  --question "Where should remote employees not leave company equipment?" \
  --top-k 5 \
  --max-hops 1
```

The `--top-k` argument controls the maximum number of graph evidence records returned. The `--max-hops` argument controls the relationship traversal depth and currently accepts values from 1 to 3.

The query command initializes the configured LLM client and may incur API usage.

## 6. Manual Smoke-Test Results

### Question

`Where should remote employees not leave company equipment?`

### Observed Result

The command returned:

- Status: `answered`.
- Four graph evidence records.
- The most relevant relationship was `Company Equipment --MUST_NOT_BE_LEFT_UNATTENDED_IN--> Public Locations`.
- Source: `rag_practice_employee_handbook.pdf`.
- Section: `Working Hours, Attendance, and Remote Work > Remote Work`.
- Page: 3.

The final answer was:

> Company equipment must not be left unattended in public locations.

The answer included the handbook document, section path, and page number.

This demonstrates that the selected section was ingested, graph evidence was retrieved, and the answer-generation flow worked for this example. It does not establish overall Graph RAG accuracy or superiority over vector and hybrid retrieval.

## 7. Tests

### Graph extractor tests

```bash
PYTHONPATH=levels/level-3-advanced-rag uv run pytest \
  levels/level-3-advanced-rag/tests/test_graph_extractor.py -q
```

### Graph store tests

```bash
PYTHONPATH=levels/level-3-advanced-rag uv run pytest \
  levels/level-3-advanced-rag/tests/test_graph_store.py -q
```

### Graph retrieval tests

```bash
PYTHONPATH=levels/level-3-advanced-rag uv run pytest \
  levels/level-3-advanced-rag/tests/test_graph_retrieval.py -q
```

### Graph RAG service tests

```bash
PYTHONPATH=levels/level-3-advanced-rag uv run pytest \
  levels/level-3-advanced-rag/tests/test_graph_rag_service.py -q
```

### Graph ingestion script tests

```bash
PYTHONPATH=levels/level-3-advanced-rag uv run pytest \
  levels/level-3-advanced-rag/tests/test_graph_ingestion.py -q
```

### Full Level 3 suite

```bash
PYTHONPATH=levels/level-3-advanced-rag uv run pytest \
  levels/level-3-advanced-rag/tests -q
```

At documentation time, the full Level 3 suite passed:

```text
245 passed in 3.91s
```

The unit tests cover extraction validation, graph-store behavior, retrieval, answer generation, section selection, and ingestion metadata.

The unit tests use controlled test dependencies where appropriate. The successful Neo4j ingestion and question-answering runs described above provide separate manual integration smoke-test evidence.

## 8. Current Limitations

1. **Extraction quality:** the LLM can misclassify entities or generate relationships that are structurally valid but semantically awkward.
2. **Limited corpus ingestion:** only the Remote Work section, section 2.2, has been ingested and manually verified through this workflow. The entire handbook has not been ingested into the Graph RAG graph.
3. **Lexical entity matching:** entity matching relies on normalized question tokens and entity names. Paraphrases, aliases, and implicit entities may not match.
4. **Basic ranking:** evidence ranking uses lexical overlap and section metadata rather than a learned graph-ranking model.
5. **Potentially unnecessary evidence:** a query can retrieve related relationships that do not directly answer the question.
6. **Graph traversal limits:** the implementation supports a bounded number of relationship hops. Increasing the hop count can retrieve more evidence, including irrelevant evidence.
7. **Negation and semantics:** preserving `not` in tokenization helps avoid discarding negation, but lexical matching does not fully understand sentence meaning or logical scope.
8. **Orphan entities:** re-ingestion replaces relationships for the source chunk, but obsolete entity nodes may remain if they are no longer referenced.
9. **Grounded generation is not guaranteed:** the LLM is instructed to use retrieved evidence, but the answer is not independently verified claim by claim.
10. **Operational readiness:** this implementation has not yet been validated for large graphs, concurrent ingestion, production access control, graph maintenance, or performance under production workloads.
11. **Cost and latency:** entity and relationship extraction requires LLM calls during ingestion. Answer generation also uses an LLM. Larger-scale ingestion and queries can increase cost and latency.
12. **Limited integration coverage:** the current manual smoke test covers one ingested section and one successful question. More integration tests are needed.

## 9. Evaluation Status

**Status: Deferred until the planned Level 3 topics are complete.**

Formal comparative evaluation remains pending, consistent with the Level 3 roadmap.

The final evaluation should use the same representative questions and comparable source information to assess the existing vector, hybrid, and Graph RAG approaches where appropriate.

Useful measurements include:

- Hit Rate@K.
- MRR@K.
- Retrieval relevance.
- Answer correctness and groundedness.
- Retrieval and end-to-end latency.
- LLM usage and cost.

The current test suite and smoke test establish basic implementation behavior. They do not demonstrate that Graph RAG improves retrieval quality, answer quality, latency, or cost compared with the existing approaches.

## 10. Summary

This implementation adds an initial Graph RAG workflow to Level 3 using an LLM for entity and relationship extraction, Neo4j for graph storage, lexical graph retrieval for evidence selection, and an LLM for grounded answer generation.

The Remote Work section was successfully ingested with six entities and four relationships. A question about company equipment retrieved the expected relationship and produced an answer with source information. The full Level 3 test suite passed with 245 tests.

Full-handbook ingestion, stronger entity matching and evidence ranking, broader integration coverage, and formal comparative evaluation remain future work.
