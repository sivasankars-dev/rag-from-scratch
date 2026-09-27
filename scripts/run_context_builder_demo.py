from app.services.context_builder import ContextBuilder


def main():
    results = [
        {
            "document": "Employees get 20 days annual leave.",
            "metadata": {
                "source": "company_policy.pdf",
                "chunk_index": 0,
            },
        },
        {
            "document": "Leave requests must be submitted through the HR portal.",
            "metadata": {
                "source": "company_policy.pdf",
                "chunk_index": 1,
            },
        },
    ]

    context_builder = ContextBuilder()

    context = context_builder.build(results)

    print("Generated Context:")
    print("------------------")
    print(context)


if __name__ == "__main__":
    main()