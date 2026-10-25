
"""Generate text descriptions for diagrams using a vision-capable model."""

import base64
import os
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()


class VisionDescriptionService:
    """Describe a diagram image using a vision-capable language model."""

    def __init__(self, model: str = "gpt-5-mini"):
        api_key = os.getenv("OPENAI_API_KEY")

        if not api_key:
            raise ValueError("OPENAI_API_KEY is not set")

        self.client = OpenAI(api_key=api_key)
        self.model = model

    def describe_image(self, image_path: str | Path) -> str:
        """Return a text description of the supplied image."""
        path = Path(image_path)

        if not path.is_file():
            raise FileNotFoundError(f"Image not found: {path}")

        if path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
            raise ValueError("Unsupported image format")

        image_data = base64.b64encode(path.read_bytes()).decode("utf-8")

        image_format = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".webp": "image/webp",
        }[path.suffix.lower()]

        response = self.client.responses.create(
            model=self.model,
            input=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": (
                                "Describe this technical diagram for a document "
                                "search system. Identify visible components, labels, "
                                "arrows, and relationships. Do not invent details "
                                "that are not visible."
                            ),
                        },
                        {
                            "type": "input_image",
                            "image_url": (
                                f"data:{image_format};base64,{image_data}"
                            ),
                        },
                    ],
                }
            ],
        )

        description = response.output_text.strip()

        if not description:
            raise ValueError("The vision model returned an empty description")

        return description
