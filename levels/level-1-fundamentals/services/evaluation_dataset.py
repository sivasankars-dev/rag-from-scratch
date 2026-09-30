import json
from pathlib import Path


class EvaluationDataset:
    def __init__(self, file_path: str):
        self.file_path = Path(file_path)

    def load(self):
        with self.file_path.open("r", encoding="utf-8") as file:
            return json.load(file)