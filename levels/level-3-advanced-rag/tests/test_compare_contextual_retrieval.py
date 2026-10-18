"""Comparison tests use evaluator-shaped data, without Chroma or models."""

from copy import deepcopy
from unittest.mock import Mock

import pytest

from scripts import compare_contextual_retrieval as comparison


def inputs(left=(None, 1, 1, None, 2), right=(1, None, 3, None, 2)):
    cases = [{"question": f"question {i}", "expected_answer": "answer",
              "expected_source": "handbook.pdf"} for i in range(len(left))]

    def report(ranks, latency):
        return {"top_k": 3, "results": [
            {"question": cases[i]["question"], "expected_answer": "answer",
             "first_relevant_rank": rank, "hit": rank is not None, "latency_ms": latency}
            for i, rank in enumerate(ranks)]}

    return cases, report(left, 10), report(right, 15)


def test_outcomes_and_order_independent_matching():
    cases, left, right = inputs()
    expected = comparison.compare_reports(cases, left, right)
    right["results"].reverse()
    assert comparison.compare_reports(cases, left, right) == expected
    assert [row["outcome"] for row in expected["rows"]] == [
        "improved", "regressed", "rank_changed", "unchanged", "unchanged"]


def test_aggregate_differences_and_output():
    result = comparison.compare_reports(*inputs((None, 3), (2, 1)))
    assert result["difference"]["hit_rate_pp"] == 50
    assert result["difference"]["mrr"] == pytest.approx(.75 - 1 / 6)
    assert result["difference"]["average_latency_ms"] == 5
    output = comparison.format_comparison(result)
    assert "+50.00 pp" in output
    assert "substring/source relevance proxies" in output
    assert "not a controlled benchmark" in output


@pytest.mark.parametrize("problem", ["duplicate", "missing", "unexpected", "answer",
                                     "empty", "invalid_rank", "invalid_hit", "latency", "cutoff"])
def test_invalid_reports(problem):
    cases, left, right = inputs()
    if problem == "duplicate":
        right["results"].append(deepcopy(right["results"][0]))
    elif problem == "missing":
        right["results"].pop()
    elif problem == "unexpected":
        right["results"][0]["question"] = "unknown"
    elif problem == "answer":
        right["results"][0]["expected_answer"] = "different"
    elif problem == "empty":
        right["results"] = []
    elif problem == "invalid_rank":
        right["results"][0]["first_relevant_rank"] = 4
    elif problem == "invalid_hit":
        right["results"][0]["hit"] = False
    elif problem == "latency":
        right["results"][0]["latency_ms"] = float("nan")
    else:
        right["top_k"] = 2
    with pytest.raises(ValueError):
        comparison.compare_reports(cases, left, right)


@pytest.mark.parametrize("cases", [[], None, [{}], [{"question": " "}]])
def test_invalid_dataset(cases):
    _, left, right = inputs()
    with pytest.raises(ValueError):
        comparison.compare_reports(cases, left, right)


def test_duplicate_dataset_questions():
    cases, left, right = inputs()
    cases.append(deepcopy(cases[0]))
    with pytest.raises(ValueError, match="duplicate question"):
        comparison.compare_reports(cases, left, right)


def test_display_truncation_does_not_change_matching():
    cases, left, right = inputs((None, None), (1, None))
    for i in range(2):
        question = "x" * 100 + str(i)
        cases[i]["question"] = question
        left["results"][i]["question"] = question
        right["results"][i]["question"] = question
    result = comparison.compare_reports(cases, left, right)
    assert result["rows"][0]["question"] != result["rows"][1]["question"]
    assert "x" * 57 + "..." in comparison.format_comparison(result)


def test_dataset_path_mismatch_fails_before_loading(monkeypatch, tmp_path):
    monkeypatch.setattr(comparison.contextual, "DATASET_PATH", tmp_path / "different.json")
    loader = Mock()
    monkeypatch.setattr(comparison, "load_cases", loader)
    with pytest.raises(ValueError, match="dataset paths"):
        comparison.main([])
    loader.assert_not_called()


def test_duplicate_questions_fail_before_loading_dependencies(monkeypatch):
    cases, _, _ = inputs()
    monkeypatch.setattr(comparison, "load_cases", Mock(return_value=[cases[0]] * 20))
    with pytest.raises(ValueError, match="duplicate question"):
        comparison.main([])
