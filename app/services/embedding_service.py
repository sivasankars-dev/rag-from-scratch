from sentence_transformers import SentenceTransformer

class EmbeddingService:
    def __init__(self, model="all-MiniLM-L6-v2"):
        self.model = SentenceTransformer(model)

    def embed_text(self,text):
        embedding = self.model.encode(text)

        return embedding.tolist()

    def embed_texts(self, texts):
        embeddings = self.model.encode(texts)

        return embeddings.tolist()
