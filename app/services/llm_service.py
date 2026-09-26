from openai import OpenAI
from app.schemas.llm_usage import LLMUsage
from app.services.cost_calculator import CostCalculator


class LLMService:
    def __init__(self):
        self.client = OpenAI()

    def generate(self, prompt):
        model = "gpt-5.6-luna"
        response = self.client.responses.create(model=model, input=prompt)

        usage = LLMUsage(
            provider="openai",
            model=model,
            input_tokens=response.usage.input_tokens,
            cached_input_tokens=response.usage.input_tokens_details.cached_tokens,
            cache_write_tokens=response.usage.input_tokens_details.cache_write_tokens,
            output_tokens=response.usage.output_tokens,
            total_tokens=response.usage.total_tokens,
        )
        
        calculator = CostCalculator()

        cost = calculator.calculate(usage)
        
        print("cost:", cost)
        print("usage", usage)

        return response.output_text
