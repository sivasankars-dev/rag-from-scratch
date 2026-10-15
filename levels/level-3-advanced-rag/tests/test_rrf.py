from services.rrf import reciprocal_rank_fusion


def test_chunk_found_in_multiple_rankings_gets_higher_score():
    rankings = [
        ["A", "B"],
        ["C", "A"],
    ]

    results = reciprocal_rank_fusion(rankings)

    assert results[0][0] == "A"
    assert results[0][1] == (1 / 61) + (1 / 62)


def test_higher_rank_gets_higher_score():
    rankings = [["A", "B", "C"]]

    results = reciprocal_rank_fusion(rankings)

    assert results[0][0] == "A"
    assert results[0][1] > results[1][1] > results[2][1]


def test_empty_rankings_return_empty_results():
    assert reciprocal_rank_fusion([]) == []


def test_custom_k_is_supported():
    rankings = [["A"]]

    results = reciprocal_rank_fusion(rankings, k=1)

    assert results == [("A", 1 / 2)]

def test_duplicate_chunk_in_one_ranking_is_counted_only_once():
    rankings = [
        ["A", "A", "B"],
    ]

    results = reciprocal_rank_fusion(rankings)

    scores = dict(results)

    assert scores["A"] == 1 / 61
    assert scores["B"] == 1 / 63
