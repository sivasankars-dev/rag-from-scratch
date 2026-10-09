
from services.grounded_prompt_builder import build_grounded_prompt


class GroundedRAGService:
    def __init__(self, context_builder, llm_service):
        self.context_builder = context_builder
        self.llm_service = llm_service

    def answer(self, question, results):
        context = self.context_builder.build(results)

        if not context.strip():
            return "I don't have enough information to answer that question."

        prompt = build_grounded_prompt(
            question=question,
            context=context,
        )

        return self.llm_service.generate(prompt)
