from pydantic import BaseModel, Field

class RetrievalRequest(BaseModel):
    query: str
    top_k: int = Field(
        default=5,
        ge=1,
        le=20
    ) 
    source: str | None = None
    similarity_threshold: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0
    )
    
class RetrievalResult(BaseModel):
    document: str
    metadata: dict
    distance: float
    similarity: float
    
class RetrievalResponse(BaseModel):
    query: str
    results: list[RetrievalResult]
    