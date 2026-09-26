class RAGPromptBuilder:
    def build(self, question, context):
        return f"""Use the following context to answer the question.

            CONTEXT:
            {context}

            QUESTION:
            {question}
            """
