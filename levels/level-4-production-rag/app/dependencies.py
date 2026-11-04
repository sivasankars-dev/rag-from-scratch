from fastapi import Request


def get_embedding_service(request: Request):
    return request.app.state.embedding_service

def get_db_session(request: Request):
    session_factory = request.app.state.session_factory

    with session_factory() as session:
        yield session