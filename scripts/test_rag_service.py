from dotenv import load_dotenv
load_dotenv()
from app.services.context_builder import ContextBuilder
from app.services.embedding_service import EmbeddingService
from app.services.llm_service import LLMService
from app.services.rag_prompt_builder import RAGPromptBuilder
from app.services.rag_service import RAGService
from app.services.retrieval_controls_vector_store import VectorStore


def main():
    rag_service = RAGService(
        embedding_service=EmbeddingService(),
        vector_store=VectorStore(),
        context_builder=ContextBuilder(),
        prompt_builder=RAGPromptBuilder(),
        llm_service=LLMService(),
    )

    question = "How many annual leave days do I get?"

    answer = rag_service.answer(question)

    print("\nQuestion:")
    print(question)

    print("\nAnswer:")
    print(answer)


if __name__ == "__main__":
    main()