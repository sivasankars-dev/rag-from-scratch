# Step 5 — Cosine similarity

## What is it, and why is it useful?

Cosine similarity measures how closely two nonzero vectors point in the same direction. In RAG, it compares the query embedding with passage embeddings to estimate semantic relatedness. It is useful when direction carries more meaning than vector length.

## Simple analogy

Two arrows may have different lengths but point along the same road. Cosine similarity treats them as aligned. Arrows pointing at right angles have zero alignment; arrows pointing opposite ways have negative alignment.

## Technical explanation and formula

```text
cosine_similarity(A, B) = (A · B) / (||A|| × ||B||)
```

The **dot product** `A · B` multiplies matching coordinates and adds the products. **Magnitude** `||A||` is the vector length: square each coordinate, sum them and take the square root. Dividing by both magnitudes removes length scaling and leaves directional agreement.

**Normalization** divides each coordinate by its vector magnitude so the resulting vector has length one. For two unit vectors, their dot product already equals cosine similarity. Our educational function calculates the full formula and therefore also works with unnormalized vectors.

For finite nonzero vectors, cosine similarity is mathematically between -1 and 1: 1 means identical direction, 0 perpendicular, and -1 opposite. Floating-point rounding can create tiny deviations. A value of 0.7 is not “70% correct” or a probability.

## Small vector example

Let `A = [1, 2]`, `B = [2, 1]`:

```text
Dot product = 1×2 + 2×1 = 4
||A|| = sqrt(1² + 2²) = sqrt(5)
||B|| = sqrt(2² + 1²) = sqrt(5)
Cosine similarity = 4 / (sqrt(5) × sqrt(5)) = 0.8
```

`[1, 0]` and `[3, 0]` score 1 despite different lengths. `[1, 0]` and `[0, 1]` score 0. `[1, 0]` and `[-1, 0]` score -1. A zero vector has no direction, so the formula is undefined.

## Existing implementation and internal steps

[`scripts/run_similarity_demo.py`](../scripts/run_similarity_demo.py) defines `cosine_similarity`. It checks equal dimensions, computes dot product and magnitudes with `sum` and `math.sqrt`, rejects zero vectors, then divides. Its `main()` embeds a refund query and compares it with a money-back sentence and a weather sentence.

```bash
.venv/bin/python -m scripts.run_similarity_demo
```

This is a manual learning experiment. The retrieval script uses Chroma's search instead of calling this Python function across every stored document. The function is also useful as an independent oracle when checking Chroma's returned distances.

## Embedding vs cosine similarity, and how RAG uses it

```text
Embedding:         text → numerical vector
Cosine similarity: two vectors → numerical comparison score
Retrieval:         compare/rank stored passages → return top matches
```

The model creates a useful vector space. The metric measures relationships within it. The same formula on arbitrary unrelated numbers would not magically understand text.

## Common mistakes

- Comparing vectors of different dimensions or from incompatible models.
- Dividing by zero for an empty or zero vector. The existing function rejects these cases.
- Assuming a dot product always equals cosine similarity; that requires normalized vectors.
- Treating a high similarity as proof that a passage answers the question.
- Reading a Chroma distance as if higher were better. With cosine distance, `distance = 1 - similarity`; lower distance is better. This conversion is not valid for L2 distance.

## What we implemented and checked

The manual function is unchanged. Validation checks the 0.8 example, aligned/perpendicular/opposite vectors, unequal dimensions and zero vectors, then runs the real sentence experiment. The search metric itself is verified in Step 6.

## Interview questions

1. Why divide by magnitudes? To remove vector-length effects.
2. Can cosine similarity be negative? Yes, for directions with a negative dot product.
3. Why is a zero vector invalid? Its magnitude is zero and its direction is undefined.
4. How does cosine distance differ? It reverses the ordering: `1 - similarity`.

## What I learned

Embedding and comparison are separate operations. Understanding this small formula makes vector database scores interpretable instead of mysterious.

## Next step

[Step 6 — ChromaDB](06-chromadb.md).
