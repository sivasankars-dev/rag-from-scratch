class RAGService:
    def __init__(
        self,
        embedding_service,
        vector_store,
        context_builder,
        prompt_builder,
        llm_service,
    ):
        self.embedding_service = embedding_service
        self.vector_store = vector_store
        self.context_builder = context_builder
        self.prompt_builder = prompt_builder
        self.llm_service = llm_service

    def answer(self, question):
        query_embedding = self.embedding_service.embed_text(question)

        results = self.vector_store.search(
            query_embedding=query_embedding
        )

        context = self.context_builder.build(results)

        prompt = self.prompt_builder.build(
            question=question,
            context=context,
        )

        return self.llm_service.generate(prompt)