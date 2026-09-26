from app.services.rag_prompt_builder import RAGPromptBuilder


def main():
    context = (
        "Employees get 20 days annual leave.\n\n"
        "Leave requests must be submitted through the HR portal."
    )

    question = "How many annual leave days do I get?"

    builder = RAGPromptBuilder()

    prompt = builder.build(
        question=question,
        context=context,
    )

    print(prompt)


if __name__ == "__main__":
    main()