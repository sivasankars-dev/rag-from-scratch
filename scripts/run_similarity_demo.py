import math

from app.services.embedding_service import EmbeddingService

def cosine_similarity(vector_a, vector_b):
    if len(vector_a) != len(vector_b):
        raise ValueError("Vectors must be same dimentions")

    dot_product =sum(a*b for a, b in zip(vector_a, vector_b))

    magnitude_a = math.sqrt(
        sum(a*a for a in vector_a)
    )

    magnitude_b = math.sqrt(
        sum(b*b for b in vector_b)
    )

    if magnitude_a == 0 or magnitude_b == 0:
        raise ValueError("Cannot calculate similarity for a zero vector")

    return dot_product / (magnitude_a * magnitude_b)

def main():
    embedding_service = EmbeddingService()

    query = "I want to get a refund."

    chunks = [
        "How can I get my money back?",
        "The weather is very hot today.",
    ]

    query_vector = embedding_service.embed_text(query)
    chunks_vectors = embedding_service.embed_texts(chunks)

    for chunk, vector in zip(chunks, chunks_vectors):
        score = cosine_similarity(query_vector, vector)

        print("=" * 60)
        print("Chunk:", chunk)
        print("Similarity:", score)


if __name__ == "__main__":
    main()
