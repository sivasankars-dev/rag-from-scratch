from services.llm_client import OpenAILLMClient
from services.query_rewriter import rewrite_query


def main():
    llm = OpenAILLMClient()

    query = "How many days can I take?"
    context = "The user is asking about annual leave."

    rewritten_query = rewrite_query(
        query,
        conversation_context=context,
        llm_client=llm,
    )

    print("Original query:")
    print(query)

    print("\nRewritten query:")
    print(rewritten_query)


if __name__ == "__main__":
    main()