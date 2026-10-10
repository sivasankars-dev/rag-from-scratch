
from services.grounded_prompt_builder import build_grounded_prompt
from services.source_citation import build_source_citations

class GroundedRAGService:
    def __init__(self, context_builder, llm_service):
        self.context_builder = context_builder
        self.llm_service = llm_service

    def answer(self, question, results):
        context = self.context_builder.build(results)

        if not context.strip():
            return {
                "answer": "I don't have enough information to answer that question.",
                "citations": [],
            }

        prompt = build_grounded_prompt(
            question=question,
            context=context,
        )

        answer = self.llm_service.generate(prompt)
        citations = build_source_citations(results["metadatas"][0])

        return {
            "answer": answer,
            "citations": citations,
        }
