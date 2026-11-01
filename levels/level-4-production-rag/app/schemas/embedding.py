from pydantic import BaseModel, Field

class EmbeddingRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000)

class EmbeddingResponse(BaseModel):
    dimensions: int
    preview: list[float]
    embedding_ms: float