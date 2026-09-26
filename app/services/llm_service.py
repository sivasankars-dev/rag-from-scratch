from openai import OpenAI


class LLMService:
    def __init__(self):
        self.client = OpenAI()

    def generate(self, prompt):
        model = "gpt-5.6-luna"
        response = self.client.responses.create(model=model, input=prompt)

        return response.output_text
