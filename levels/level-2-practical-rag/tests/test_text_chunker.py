from services.chunker import split_into_paragraphs, split_long_paragraph, chunk_text


def test_split_chunks():
    paragraphs = """paragraph one

paragraph two

paragraph three"""

    split_paragraph = split_into_paragraphs(paragraphs)

    assert len(split_paragraph) == 3
    assert split_paragraph[0] == "paragraph one"


def test_split_single_line_paragraph():
    paragraph = "This is a single paragraph."

    split_single_paragraph = split_into_paragraphs(paragraph)

    assert len(split_single_paragraph) == 1
    assert split_single_paragraph[0] == "This is a single paragraph."


def test_split_paragraph_is_empty():
    paragraph = ""
    split_paragraph = split_into_paragraphs(paragraph)

    assert len(split_paragraph) == 0


def test_split_messy_paragraph():
    paragraph = """paragraph one


paragraph two



paragraph three"""

    split_paragraph = split_into_paragraphs(paragraph)

    assert len(split_paragraph) == 3


def test_split_long_paragraph():
    paragraph = (
        "Python is easy to learn. "
        "FastAPI is used to build APIs. "
        "PostgreSQL stores application data."
    )

    chunks = split_long_paragraph(paragraph, chunk_limit=10)
    print(chunks)  # See the returned chunks

    assert len(chunks) == 2


def test_chunk_text_with_small_paragraph():
    text = "Python is easy to learn."

    chunks = chunk_text(text, 10)

    assert len(chunks) == 1
    assert chunks == ["Python is easy to learn."]


def test_chunk_text_with_long_paragraph():
    text = """Python is easy to learn. 
FastAPI is used to build APIs. 
PostgreSQL stores application data.
    """
    
    chunks = chunk_text(text, 10)
    
    assert len(chunks) == 2
    assert chunks == ["Python is easy to learn", "FastAPI is used to build APIs PostgreSQL stores application data"]
    
def test_chunk_test_with_mixed_paragraph():
    text = """Python is easy to learn.

FastAPI is used to build APIs. PostgreSQL stores application data.

Docker packages applications."""

    chunks = chunk_text(text, 10)
    
    assert len(chunks) == 3
    assert chunks == ["Python is easy to learn.", "FastAPI is used to build APIs. PostgreSQL stores application data.", "Docker packages applications."]
    
def test_chunk_text_empty_paragraph():
    text = """ """
    chunks = chunk_text(text, 10)
    
    assert len(chunks) == 0
    assert chunks == []
    
def test_chunk_text_only_white_space_paragraph():
    text = """   
    
""" 
    chunks = chunk_text(text, 10)
    assert len(chunks) == 0
    assert chunks == []
        
def test_long_single_sentence():
    text = "Python is a very powerful programming language"

    chunks = split_long_paragraph(text, 5)

    assert chunks == [
        "Python is a very powerful",
        "programming language"
    ]
    
    for chunk in chunks:
        assert len(chunk.split()) <= 5
        
def test_chunk_text_with_oversized_sentence():
    text = (
        "Python is easy to learn. "
        "Python is a very powerful programming language. "
        "FastAPI is used to build APIs."
    )

    chunks = chunk_text(text, 5)
    
    assert len(chunks) == 5
    assert chunks == ["Python is easy to learn", "Python is a very powerful", "programming language", "FastAPI is used to build", "APIs"]