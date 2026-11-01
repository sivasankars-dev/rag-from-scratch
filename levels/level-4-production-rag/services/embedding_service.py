from sentence_transformers import SentenceTransformer


class EmbeddingService:
    def __init__(self, model="all-MiniLM-L6-v2"):
        self.model = SentenceTransformer(model)

    def embed_text(self, text):
        return self.model.encode(text).tolist()

    def embed_texts(self, texts):
        return self.model.encode(texts).tolist()
