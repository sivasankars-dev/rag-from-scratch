from services.context_builder import ContextBuilder


def test_build_context_from_chroma_results():
    results = {
        "documents": [
            [
                "Employees receive 20 days of annual leave.",
                "Leave requests require manager approval.",
            ]
        ]
    }

    builder = ContextBuilder()

    context = builder.build(results)

    assert context == (
        "Employees receive 20 days of annual leave.\n\n"
        "Leave requests require manager approval."
    )
    
def test_build_context_when_no_documents_are_retrieved():
    results = {
        "documents": [[]]
    }

    builder = ContextBuilder()

    context = builder.build(results)

    assert context == ""