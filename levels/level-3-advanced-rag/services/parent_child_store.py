
import json
from pathlib import Path


class ParentChildStore:
    def __init__(self, storage_path="data/parents.json"):
        self.storage_path = Path(storage_path)
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)

        if self.storage_path.exists():
            with self.storage_path.open("r", encoding="utf-8") as file:
                self.parents = json.load(file)
        else:
            self.parents = {}

    def store_parent(self, parent):
        parent_id = parent.get("parent_id")

        if not parent_id:
            raise ValueError("parent_id is required")

        self.parents[parent_id] = parent
        self._save()

    def get_parent(self, parent_id):
        return self.parents.get(parent_id)

    def _save(self):
        with self.storage_path.open("w", encoding="utf-8") as file:
            json.dump(self.parents, file, ensure_ascii=False, indent=2)
