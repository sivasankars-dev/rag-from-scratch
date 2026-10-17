"""Offline evaluator tests; no Chroma client or embedding model is imported."""
import importlib.util
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from services.parent_child_evaluator import (
    evaluate, first_matching_rank, format_report, load_cases,
    normalize_text, reciprocal_rank, summarize, validate_cases,
)
from services.parent_child_retrieval import ParentChildRetrievalService

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/run_evaluate_parent_child_retrieval.py"
spec = importlib.util.spec_from_file_location("parent_child_eval_runner", SCRIPT)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def case(question="question", answer="annual leave"):
    return {"question": question, "expected_answer": answer,
            "expected_source": "handbook.pdf", "expected_chunk": 999}


def parent(text, source="handbook.pdf", parent_id="p1"):
    return {"parent_id": parent_id, "text": text, "source": source}


def test_normalization_and_source_matching():
    assert normalize_text("  ANNUAL\n Leave\t") == "annual leave"
    results = [parent("Annual leave", "other.pdf"), parent("Get ANNUAL\nleave now")]
    assert first_matching_rank(results, "annual   LEAVE", "handbook.pdf") == 2
    assert first_matching_rank(results, "paid time off", "handbook.pdf") is None


def test_empty_results_and_parent_cutoff():
    assert first_matching_rank([], "annual leave", "handbook.pdf") is None
    results = [parent("other")] * 3 + [parent("annual leave")]
    assert first_matching_rank(results, "annual leave", "handbook.pdf", 3) is None
    with pytest.raises(ValueError, match="blank"):
        first_matching_rank([], " ", "handbook.pdf")


@pytest.mark.parametrize("rank, expected", [(None, 0), (1, 1), (2, .5), (3, 1 / 3)])
def test_reciprocal_rank(rank, expected):
    assert reciprocal_rank(rank) == expected


@pytest.mark.parametrize("rank", [0, -1, True, 1.5])
def test_invalid_reciprocal_rank(rank):
    with pytest.raises(ValueError):
        reciprocal_rank(rank)


def test_aggregate_metrics_latency_and_formatting():
    retrieval = Mock()
    retrieval.retrieve.side_effect = [
        [parent("Annual leave")],
        [parent("other"), parent("Annual leave")],
        [],
    ]
    ticks = iter([0, .01, 1, 1.02, 2, 2.03])
    report = evaluate([case("a"), case("b"), case("c")], retrieval,
                      clock=lambda: next(ticks))
    assert report["summary"]["questions"] == 3
    assert report["summary"]["hit_rate"] == pytest.approx(2 / 3)
    assert report["summary"]["mrr"] == .5
    assert report["summary"]["average_latency_ms"] == pytest.approx(20)
    assert [r["first_relevant_rank"] for r in report["results"]] == [1, 2, None]
    assert [r["hit"] for r in report["results"]] == [True, True, False]
    assert all(call.kwargs == {"top_k": 3} for call in retrieval.retrieve.call_args_list)
    output = format_report(report)
    for text in ["RELEVANCE PROXY ONLY", "Question: a", "Expected answer: annual leave",
                 "First relevant parent rank (proxy): None", "Hit: False",
                 "Hit Rate@3 (proxy): 66.67%", "MRR@3 (proxy): 0.5000",
                 "Average retrieval latency: 20.00 ms"]:
        assert text in output
    assert summarize([]) == {"questions": 0, "hit_rate": 0.0,
                             "mrr": 0.0, "average_latency_ms": 0.0}


def test_real_retrieval_service_with_fake_embedding_and_parent_data():
    embeddings = Mock()
    embeddings.embed_text.return_value = [1.0, 0.0]
    children = Mock()
    children.search.return_value = [
        {"metadata": {"parent_id": "p1"}},
        {"metadata": {"parent_id": "p1"}},
        {"metadata": {"parent_id": "p2"}},
    ]
    parents = Mock()
    parents.get_parent.side_effect = lambda key: {
        "p1": parent("other"), "p2": parent("annual leave", parent_id="p2")
    }[key]
    retrieval = ParentChildRetrievalService(embeddings, children, parents)
    report = evaluate([case()], retrieval, clock=lambda: 0)
    assert report["results"][0]["first_relevant_rank"] == 2  # child rank was 3
    assert report["summary"]["mrr"] == .5
    embeddings.embed_text.assert_called_once_with("question")
    children.search.assert_called_once_with(query_embedding=[1.0, 0.0], top_k=3)


@pytest.mark.parametrize("cases", [[], {}, [None], [case(answer=" ")],
                                   [{"question": "q", "expected_answer": "a"}],
                                   [dict(case(), question=42)]])
def test_invalid_dataset(cases):
    with pytest.raises(ValueError, match="Dataset"):
        validate_cases(cases)


def test_dataset_file_errors_and_twenty_case_requirement(tmp_path):
    path = tmp_path / "cases.json"
    with pytest.raises(ValueError, match="Cannot read evaluation dataset"):
        load_cases(path)
    path.write_text("invalid JSON")
    with pytest.raises(ValueError, match="Cannot read evaluation dataset"):
        load_cases(path)
    path.write_text(json.dumps([case()]))
    with pytest.raises(ValueError, match="Expected 20"):
        load_cases(path)
    path.write_text(json.dumps([case()] * 20))
    assert len(load_cases(path)) == 20


def test_default_latency_clock_is_perf_counter(monkeypatch):
    ticks = iter([100, 100.25])
    monkeypatch.setattr("services.parent_child_evaluator.time.perf_counter",
                        lambda: next(ticks))
    report = evaluate([case()], Mock(retrieve=Mock(return_value=[])))
    assert report["summary"]["average_latency_ms"] == 250


@pytest.fixture
def stores(tmp_path):
    parent_path = tmp_path / "parents.json"
    parent_path.write_text("{}")  # Existence marker only; factory supplies fake data.
    chroma_path = tmp_path / "chroma"
    chroma_path.mkdir()
    (chroma_path / "chroma.sqlite3").touch()  # Not a real database; never opened.
    parent_store = Mock()
    parent_store.parents = {"p1": parent("annual leave")}
    parent_store.get_parent.side_effect = parent_store.parents.get
    collection = Mock()
    collection.count.return_value = 1
    collection.get.return_value = {
        "metadatas": [{"parent_id": "p1", "source": "handbook.pdf"}]
    }
    client = Mock(get_collection=Mock(return_value=collection))
    return dict(parent_factory=Mock(return_value=parent_store), child_factory=Mock(),
                client_factory=Mock(return_value=client), parent_path=parent_path,
                chroma_path=chroma_path)


def test_valid_store_preflight_and_constructor_arguments(stores):
    parents, children = runner.load_stores([case()], **stores)
    assert parents is stores["parent_factory"].return_value
    assert children is stores["child_factory"].return_value
    stores["child_factory"].assert_called_once_with(
        persist_directory=str(stores["chroma_path"]), collection_name=runner.COLLECTION_NAME)
    stores["client_factory"].return_value.get_collection.assert_called_once_with(
        name=runner.COLLECTION_NAME)


@pytest.mark.parametrize("missing", ["parents", "database", "collection", "empty",
                                     "orphan", "source", "bad_parent"])
def test_missing_or_inconsistent_store_fails_before_child_wrapper(stores, missing):
    client = stores["client_factory"].return_value
    collection = client.get_collection.return_value
    if missing == "parents":
        stores["parent_path"].unlink()
    elif missing == "database":
        (stores["chroma_path"] / "chroma.sqlite3").unlink()
    elif missing == "collection":
        client.get_collection.side_effect = ValueError("collection missing")
    elif missing == "empty":
        collection.count.return_value = 0
    elif missing == "orphan":
        collection.get.return_value = {"metadatas": [{"parent_id": "absent"}]}
    elif missing == "source":
        collection.get.return_value = {"metadatas": [{"parent_id": "p1", "source": "wrong"}]}
    else:
        stores["parent_factory"].return_value.parents = {"p1": {"text": "bad"}}
    with pytest.raises(ValueError, match="ingestion"):
        runner.load_stores([case()], **stores)
    stores["child_factory"].assert_not_called()


def test_diagnostic_flag_defaults_off():
    assert runner.parse_args([]).show_context is False
    assert runner.parse_args(["--show-context"]).show_context is True


def test_context_preserves_metrics_and_default_output_without_extra_retrieval():
    data = [parent("Paid time off", parent_id="miss"), parent("different policy", parent_id="p2")]
    data[0]["page_number"] = 7
    cases = [case("miss"), case("hit")]
    default_retrieval = Mock()
    default_retrieval.retrieve.side_effect = [data, [parent("annual leave")]]
    diagnostic_retrieval = Mock()
    diagnostic_retrieval.retrieve.side_effect = [data, [parent("annual leave")]]
    default = evaluate(cases, default_retrieval, clock=lambda: 0)
    diagnostic = evaluate(cases, diagnostic_retrieval, clock=lambda: 0, show_context=True)
    assert diagnostic["summary"] == default["summary"]
    assert diagnostic_retrieval.retrieve.call_args_list == default_retrieval.retrieve.call_args_list
    assert diagnostic_retrieval.retrieve.call_count == 2
    assert "failed_context" not in diagnostic["results"][1]
    output = format_report(diagnostic)
    for value in ["Question: miss", "Expected answer: annual leave", "Parent rank: 1",
                  "Parent rank: 2", "Source: handbook.pdf", "Page number: 7",
                  "Page number: Unknown", "Parent ID: miss", "Text preview: Paid time off",
                  "not a confirmed semantic retrieval failure"]:
        assert value in output
    assert "Diagnostic:" not in format_report(default)
    diagnostic["results"][0].pop("failed_context")
    assert diagnostic == default
    assert format_report(diagnostic) == format_report(default)


def test_empty_diagnostic_context():
    report = evaluate([case()], Mock(retrieve=Mock(return_value=[])),
                      clock=lambda: 0, show_context=True)
    assert "No parent chunks returned." in format_report(report)
    assert report["summary"]["hit_rate"] == 0


def test_preview_truncation_and_case_preservation():
    from services.parent_child_evaluator import text_preview
    assert text_preview("  Keep\nMy\tCase ") == "Keep My Case"
    assert text_preview("X" * 500) == "X" * 500
    preview = text_preview("X" * 501)
    assert len(preview) == 500
    assert preview == "X" * 497 + "..."
