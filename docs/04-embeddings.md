# Step 4 — Text embeddings

## What is an embedding, and why do we need it?

An embedding is a numerical vector: an ordered list of numbers representing learned features of text. It allows us to compare a question with passages even when their exact words differ. For example, “How many vacation days am I allowed?” can relate to “I can take 20 days of annual leave.” This is learned similarity, not a guarantee of factual equivalence.

## Simple analogy

Imagine a map where related ideas tend to sit near one another. An embedding gives a passage coordinates on that map. Real embedding coordinates are learned numerical features, not named axes such as “leave” or “refund.”

## Technical explanation

`SentenceTransformer("all-MiniLM-L6-v2")` loads a pretrained model and its tokenizer. The tokenizer turns words/word pieces into token IDs and masks. Transformer layers compute contextual representations; pooling combines token representations into one sentence vector. This model includes normalization. The model is used for inference here, not trained on the policy PDF.

The [model card](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2) describes 384-dimensional embeddings and a default limit of 256 word pieces, beyond which input is truncated. The local experiment confirms 384 output numbers. Input token count and output vector dimension are different quantities.

## Existing implementation and model loading

[`EmbeddingService`](../app/services/embedding_service.py) creates one model per service instance. `embed_text(text)` encodes one string and returns a flat Python list. `embed_texts(texts)` encodes a list of strings and returns a list of vectors. `.tolist()` converts the model's NumPy result into ordinary lists accepted by Chroma.

```python
service = EmbeddingService()
query_vector = service.embed_text("How many vacation days am I allowed?")
chunk_vectors = service.embed_texts(["Employees receive 20 days of annual leave."])
# len(query_vector) == 384
# len(chunk_vectors) == 1; len(chunk_vectors[0]) == 384
```

The first load may download model files to the Hugging Face cache. Later runs can reuse cached files. No API key or hosted embedding call is needed for this public model. Each separate script process loads its own model. The dependency lock fixes libraries, but the short model name is not a pinned model revision.

## Chunking, tokenization, embedding and similarity

```text
PDF → extracted text → character-based application chunks
    → model tokenizer → token IDs → model → embedding vector
```

Tokenization converts text into model input pieces. Embedding computes a fixed-length meaning representation from those inputs. Our chunker is not token-aware merely because the model later tokenizes its input. A production chunker could use the model tokenizer before splitting; that is outside this implementation.

```text
Embedding:         text → vector
Cosine similarity: vector + vector → comparison score
```

Creating vectors does not rank them. Step 5 supplies a comparison function; Steps 6–7 use a vector store to search.

## What we implemented and verified

The existing service is unchanged. Run from the root:

```bash
.venv/bin/python -m scripts.run_embedding_demo
```

It encodes three strings about refunds, getting money back and hot weather. All three print `VECTOR LENGTH: 384` and the first ten coordinates. Coordinates are not individually meaningful labels. To reproduce an offline check after the model has been cached:

```bash
HF_HUB_OFFLINE=1 .venv/bin/python -m scripts.run_embedding_demo
```

Verified library versions: sentence-transformers 5.2.3, transformers 4.47.1, torch 2.4.1. The macOS ARM compatibility work is recorded in [Step 1](01-project-setup.md); no versions were changed during documentation.

## Common beginner mistakes

- Confusing token IDs with the final sentence embedding.
- Comparing vectors produced by different models merely because their dimensions match. Use the same model for queries and documents.
- Assuming longer text produces a longer vector. This model always returns 384 dimensions per input.
- Treating similarity as truth: semantically related statements can contradict one another.
- Loading a new service for every chunk. The ingestion script loads once and encodes the batch.
- Forgetting the model's token limit or assuming character chunking measures it.

## Interview questions

1. What does an embedding represent? Learned numerical features useful for comparing text meaning.
2. Does tokenization itself produce sentence similarity? No; it prepares model inputs.
3. Why embed the query with the same model? It must inhabit the same learned vector space.
4. Is embedding the same as cosine similarity? No; one creates vectors and the other compares them.

## What I learned

Text becomes something searchable numerically, but the model and the comparison measure have separate jobs. Package compatibility and application imports must work before experimenting with that representation.

## Next step

[Step 5 — Cosine similarity](05-cosine-similarity.md).
