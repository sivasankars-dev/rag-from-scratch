def rewrite_query(query, conversation_context=None, llm_client=None):
    if llm_client is None:
        return query.strip()

    prompt = build_rewrite_prompt(
        query,
        conversation_context,
    )

    rewritten_query = llm_client.generate(prompt)

    return rewritten_query.strip()

def build_rewrite_prompt(query, conversation_context=None):
    context = conversation_context or "None"

    return f"""
You are a query rewriting assistant.

Your task is to rewrite the user's query
into a clear, retrieval-friendly query.

Rules:
- Preserve the user's original intent.
- Use conversation context when it helps clarify the query.
- Do not answer the user's question.
- Do not invent missing information.
- Return only the rewritten query.

Conversation context:
{context}

Current query:
{query}
""".strip()