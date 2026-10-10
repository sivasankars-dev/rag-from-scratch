
from fastapi import FastAPI

from app.routers.health import router as health_router
from app.routers.answer import router as answer_router


app = FastAPI(
    title="Level 2 Practical RAG API",
    version="0.1.0",
)

app.include_router(health_router)
app.include_router(answer_router)
