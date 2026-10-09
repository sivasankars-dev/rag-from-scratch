def build_grounded_prompt(question, context):
    return f"""Answer the question using only the provided context.

If the context does not contain enough information to answer,
clearly say "not enough information" when the context is insufficient.
Do not invent facts or use unsupported information.

CONTEXT:
{context}

QUESTION:
{question}"""