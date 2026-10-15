from services.multi_query_generator import MultiQueryGenerator


class FakeLLMClient:
    def __init__(self, response):
        self.response = response
        self.last_prompt = None

    def generate(self, prompt):
        self.last_prompt = prompt
        return self.response


def test_generates_multiple_queries():
    llm_client = FakeLLMClient(
        "annual leave entitlement\n"
        "paid vacation policy\n"
        "employee leave benefits"
    )
    generator = MultiQueryGenerator(llm_client, num_queries=3)

    queries = generator.generate_queries("How many annual leave days?")

    assert queries == [
        "annual leave entitlement",
        "paid vacation policy",
        "employee leave benefits",
    ]


def test_prompt_contains_original_question():
    llm_client = FakeLLMClient("annual leave entitlement")
    generator = MultiQueryGenerator(llm_client)

    generator.generate_queries("How many annual leave days?")

    assert "How many annual leave days?" in llm_client.last_prompt


def test_removes_numbering_and_bullet_prefixes():
    llm_client = FakeLLMClient(
        "1. annual leave policy\n"
        "2) paid vacation days\n"
        "- employee leave benefits"
    )
    generator = MultiQueryGenerator(llm_client)

    queries = generator.generate_queries("Annual leave?")

    assert queries == [
        "annual leave policy",
        "paid vacation days",
        "employee leave benefits",
    ]


def test_ignores_blank_lines():
    llm_client = FakeLLMClient(
        "annual leave policy\n\npaid vacation days\n"
    )
    generator = MultiQueryGenerator(llm_client)

    queries = generator.generate_queries("Annual leave?")

    assert queries == [
        "annual leave policy",
        "paid vacation days",
    ]
