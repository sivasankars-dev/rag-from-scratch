import re

class MultiQueryGenerator:
    def __init__(self, llm_client, num_queries=3):
        self.llm_client = llm_client
        self.num_queries = num_queries

    def generate_queries(self, question):
        prompt = f"""
You are a search query generation assistant.

Generate exactly {self.num_queries} alternative search queries
for the user's question.

Rules:
- Preserve the original intent.
- Explore different wording or search perspectives.
- Do not answer the question.
- Return only the queries, one per line.
- Do not number the queries.

Original question:
{question}
""".strip()

        response = self.llm_client.generate(prompt)

        queries = []

        for line in response.splitlines():
            line = line.strip()

            if not line:
                continue

            line = re.sub(r"^(?:[-•*]\s*|\d+[.)]\s*)", "", line).strip()

            if line:
                queries.append(line)

        return queries
