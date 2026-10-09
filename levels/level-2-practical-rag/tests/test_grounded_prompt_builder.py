from services.grounded_prompt_builder import build_grounded_prompt


def test_grounded_prompt_includes_question_and_context():
    question = "What is the annual leave allowance?"
    context = "Employees receive 20 days of annual leave per year."

    prompt = build_grounded_prompt(question, context)

    assert question in prompt
    assert context in prompt
    
def test_grounded_prompt_tells_llm_not_to_invent_facts():
    prompt = build_grounded_prompt(
        "What is the annual leave allowance?",
        "Employees receive 20 days of annual leave per year.",
    )

    assert "Do not invent facts" in prompt
    assert "unsupported information" in prompt


def test_grounded_prompt_handles_insufficient_information():
    prompt = build_grounded_prompt(
        "What is the company's bonus policy?",
        "Employees receive 20 days of annual leave per year.",
    )

    assert "not enough information" in prompt