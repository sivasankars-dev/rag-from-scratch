from services.query_rewriter import rewrite_query
from services.query_rewriter import build_rewrite_prompt

class FakeLLM:
    def __init__(self, response):
        self.response = response
        self.received_prompt = None

    def generate(self, prompt):
        self.received_prompt = prompt
        return self.response


def test_rewrite_query_without_context_returns_clean_query():
    result = rewrite_query("  What is the annual leave policy?  ")

    assert result == "What is the annual leave policy?"
    
def test_rewrite_query_with_context_returns_clean_query():
    result = rewrite_query(
        "  How many days can I take?  ",
        conversation_context="User is asking about annual leave.",
    )

    assert result == "How many days can I take?"
    
def test_build_rewrite_prompt_includes_query_and_context():
    prompt = build_rewrite_prompt(
        "How many days can I take?",
        "User is asking about annual leave.",
    )

    assert "How many days can I take?" in prompt
    assert "User is asking about annual leave." in prompt
    assert "Do not answer the user's question." in prompt
    
def test_rewrite_query_uses_llm_response():
    llm = FakeLLM(
        "How many annual leave days can an employee take?"
    )

    result = rewrite_query(
        "How many days can I take?",
        conversation_context="User is asking about annual leave.",
        llm_client=llm,
    )

    assert result == "How many annual leave days can an employee take?"
    
def test_rewrite_query_sends_context_and_query_to_llm():
    llm = FakeLLM(
        "How many annual leave days can an employee take?"
    )

    rewrite_query(
        "How many days can I take?",
        conversation_context="User is asking about annual leave.",
        llm_client=llm,
    )

    assert "How many days can I take?" in llm.received_prompt
    assert "User is asking about annual leave." in llm.received_prompt
