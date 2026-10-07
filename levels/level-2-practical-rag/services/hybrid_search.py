def _get_chunk_id(chunk):
    return f"{chunk['source']}_chunk_{chunk['chunk_index']}"

def merge_search_results(semantic_results, keyword_results):
    merged = {}
    
    for result in semantic_results:
        chunk = result["chunk"]
        chunk_id = _get_chunk_id(chunk)
        
        merged[chunk_id] = {
            "chunk": chunk,
            "semantic_score": result["score"],
            "keyword_score": 0
        }
        
    for result in keyword_results:
        chunk = result["chunk"]
        chunk_id = _get_chunk_id(chunk)
        
        if chunk_id in merged:
            merged[chunk_id]["keyword_score"] = result["score"]
        else:
            merged[chunk_id] = {
                "chunk": chunk,
                "semantic_score": 0,
                "keyword_score": result["score"]
            }
            
    return list(merged.values())

def normalize_keyword_scores(results):
    if not results:
        return []
    
    max_score = max(result["keyword_score"] for result in results)
    
    if max_score == 0:
        return results
    
    normalized_results = []
    
    for result in results:
        normalized_result = result.copy()
        normalized_result["keyword_score"] = (result["keyword_score"]/max_score)
        
        normalized_results.append(normalized_result)
        
    return normalized_results

def convert_distance_to_similarity(results):
    converted_results = []
    
    for result in results:
        converted_result = result.copy()
        converted_result["semantic_score"] = 1 - result["semantic_score"]
        
        converted_results.append(converted_result)
        
    return converted_results

def calculate_hybrid_scores(
    results,
    semantic_weight=0.5,
    keyword_weight=0.5,
):
    scored_results = []
    
    for result in results:
        scored_result = result.copy()
        
        hybrid_score = semantic_weight*scored_result["semantic_score"]+keyword_weight*scored_result["keyword_score"]
        
        scored_result["hybrid_score"] = hybrid_score
        
        scored_results.append(scored_result)
        
    scored_results.sort(key=lambda result: result["hybrid_score"], reverse=True)
        
    return scored_results

def hybrid_search(
    semantic_results,
    keyword_results,
    top_k=2,
    semantic_weight=0.5,
    keyword_weight=0.5,
):
    merged_results = merge_search_results(
        semantic_results,
        keyword_results,
    )

    converted_results = convert_distance_to_similarity(
        merged_results
    )

    normalized_results = normalize_keyword_scores(
        converted_results
    )

    scored_results = calculate_hybrid_scores(
        normalized_results,
        semantic_weight=semantic_weight,
        keyword_weight=keyword_weight,
    )

    return scored_results[:top_k]