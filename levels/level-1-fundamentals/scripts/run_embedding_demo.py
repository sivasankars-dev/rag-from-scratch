from services.embedding_service import EmbeddingService

def main():
    embedding = EmbeddingService()

    texts = [
        "I want to get a refund.",
        "How can I get my money back?",
        "The weather is very hot today.",
    ]

    embeddings = embedding.embed_texts(texts)

    for text, embed in zip(texts, embeddings):
        print("=" * 60)
        print("TEXT:", text)
        print("VECTOR LENGTH:", len(embed))
        print("FIRST 10 VALUES:", embed[:10])


if __name__ == "__main__":
    main()
