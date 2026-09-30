from services.vector_store import VectorStore


def main():
    vector_store = VectorStore()

    result = vector_store.collection.get(
        include=["documents", "metadatas"],
    )

    print("Number of stored records:", len(result["ids"]))

    for record_id, document, metadata in zip(
        result["ids"],
        result["documents"],
        result["metadatas"],
    ):
        print("\n" + "=" * 60)
        print("ID:", record_id)
        print("DOCUMENT:", document)
        print("METADATA:", metadata)


if __name__ == "__main__":
    main()
