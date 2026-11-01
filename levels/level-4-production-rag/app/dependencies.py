from fastapi import Request


def get_embedding_service(request: Request):
    return request.app.state.embedding_service