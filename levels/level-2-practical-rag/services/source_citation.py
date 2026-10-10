def build_source_citation(metadata):
    source = metadata["source"]
    page_number = metadata["page_number"]
    chunk_index = metadata["chunk_index"]

    return (
        f"Source: {source}, "
        f"Page: {page_number}, "
        f"Chunk: {chunk_index}"
    )
    
def build_source_citations(metadata_list):
    return [
        build_source_citation(metadata)
        for metadata in metadata_list
    ]