import os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()


class OpenAILLMClient:
    def __init__(self):
        api_key = os.getenv("OPENAI_API_KEY")

        if not api_key:
            raise ValueError("OPENAI_API_KEY is not set")

        self.client = OpenAI(api_key=api_key)

    def generate(self, prompt):
        response = self.client.responses.create(
            model="gpt-5-mini",
            input=prompt,
        )

        return response.output_text