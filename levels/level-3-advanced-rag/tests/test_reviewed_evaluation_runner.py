import importlib.util
from pathlib import Path
from types import SimpleNamespace
import json
import pytest


RUNNER_PATH = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "run_evaluate_hybrid_retrieval.py"
)

spec = importlib.util.spec_from_file_location(
    "reviewed_evaluation_runner",
    RUNNER_PATH,
)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def find_expected_rank(metadata, expected_chunk, expected_source):
    for rank, item in enumerate(metadata, start=1):
        if (
            item["source"] == expected_source
            and item["chunk_index"] == expected_chunk
        ):
            return rank
    return None


evaluator = SimpleNamespace(
    find_expected_chunk_rank=find_expected_rank,
    calculate_reciprocal_rank=lambda rank: 0.0 if rank is None else 1 / rank,
    calculate_hit_rate=lambda hits: sum(hits) / len(hits),
    calculate_mrr=lambda ranks: sum(ranks) / len(ranks),
)


def results(*indices):
    return [
        {
            "document": f"Chunk {index}",
            "metadata": {
                "source": "handbook.pdf",
                "chunk_index": index,
            },
        }
        for index in indices
    ]


def test_reviewed_runner_accepts_alternative_and_enforces_cutoff():
    cases = [
        {
            "question": "Lost laptop?",
            "expected_source": "handbook.pdf",
            "expected_chunk": 25,
            "relevant_chunks": [13, 25],
        },
        {
            "question": "Planned leave?",
            "expected_source": "handbook.pdf",
            "expected_chunk": 7,
            "relevant_chunks": [7, 25],
        },
    ]

    responses = {
        "Lost laptop?": results(11, 13, 22),
        # Deliberately return more than requested to test cutoff enforcement.
        "Planned leave?": results(1, 2, 3, 7),
    }

    report = runner.evaluate_results(
        cases,
        lambda question, top_k: responses[question],
        evaluator,
        top_k=3,
        warmup_queries=0,
    )

    hit_rate, mrr, details, _, _ = report

    assert hit_rate == pytest.approx(0.5)
    assert mrr == pytest.approx(0.25)
    assert [item["rank"] for item in details] == [2, None]


def test_runner_preserves_original_single_label_evaluation():
    cases = [
        {
            "question": "Lost laptop?",
            "expected_source": "handbook.pdf",
            "expected_chunk": 25,
        }
    ]

    report = runner.evaluate_results(
        cases,
        lambda question, top_k: results(13, 25, 22),
        evaluator,
        top_k=3,
        warmup_queries=0,
    )

    hit_rate, mrr, details, _, _ = report

    assert hit_rate == 1.0
    assert mrr == 0.5
    assert details[0]["rank"] == 2


def test_warmup_is_excluded_from_quality_and_latency(monkeypatch):
    cases = [
        {
            "question": "Lost laptop?",
            "expected_source": "handbook.pdf",
            "expected_chunk": 25,
            "relevant_chunks": [13, 25],
        }
    ]

    calls = []

    def retrieve(question, top_k):
        calls.append((question, top_k))
        # Warm-up misses; the measured retrieval succeeds.
        return results(11) if len(calls) == 1 else results(13)

    # Only the measured retrieval should read the timer.
    timestamps = iter([10.0, 10.02])
    monkeypatch.setattr(
        runner.time,
        "perf_counter",
        lambda: next(timestamps),
    )

    report = runner.evaluate_results(
        cases,
        retrieve,
        evaluator,
        top_k=3,
        warmup_queries=1,
    )

    hit_rate, mrr, details, average_ms, p95_ms = report

    assert len(calls) == 2
    assert len(details) == 1
    assert hit_rate == 1.0
    assert mrr == 1.0
    assert average_ms == pytest.approx(20.0)
    assert p95_ms == pytest.approx(20.0)
    
def test_saves_report_and_creates_parent_directory(tmp_path):
    output = tmp_path / "reports" / "evaluation.json"
    report = {
        "dataset_version": "handbook-reviewed-v1",
        "strategies": {
            "Vector-only": {"hit_rate_at_k": 0.95}
        },
    }

    runner.save_evaluation_report(output, report)

    assert json.loads(output.read_text(encoding="utf-8")) == report


def test_does_not_overwrite_existing_report(tmp_path):
    output = tmp_path / "evaluation.json"
    output.write_text("existing report\n", encoding="utf-8")

    with pytest.raises(FileExistsError):
        runner.save_evaluation_report(output, {"new": "report"})

    assert output.read_text(encoding="utf-8") == "existing report\n"