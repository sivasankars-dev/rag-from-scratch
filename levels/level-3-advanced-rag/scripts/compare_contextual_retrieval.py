"""Compare existing baseline and contextual stores using relevance proxies."""

import argparse
import math
from pathlib import Path
import sys

LEVEL3 = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LEVEL3))
import chromadb
from services.parent_child_store import ParentChildStore
from services.parent_child_retrieval import ParentChildRetrievalService

from scripts import run_evaluate_parent_child_retrieval as baseline
from scripts import run_evaluate_contextual_retrieval as contextual
from services.parent_child_evaluator import (
    PROXY_NOTICE,
    evaluate,
    load_cases,
    summarize,
    validate_cases,
)


def index_questions(rows, label):
    if not isinstance(rows, list) or not rows:
        raise ValueError(f"{label}: expected a nonempty list of questions")
    indexed = {}
    for row in rows:
        question = row.get("question") if isinstance(row, dict) else None
        if not isinstance(question, str) or not question.strip():
            raise ValueError(f"{label}: missing or invalid question")
        if question in indexed:
            raise ValueError(f"{label}: duplicate question: {question!r}")
        indexed[question] = row
    return indexed


def compare_reports(cases, baseline_report, contextual_report):
    """Match exact questions and reuse shared aggregation; never match by position."""
    validate_cases(cases)
    expected = index_questions(cases, "Dataset")
    indexed_reports = []
    summaries = []
    for label, report in (
        ("Baseline", baseline_report),
        ("Contextual", contextual_report),
    ):
        if not isinstance(report, dict) or report.get("top_k") != 3:
            raise ValueError(f"{label}: expected an evaluator report with top_k=3")
        indexed = index_questions(report.get("results"), label)
        if indexed.keys() != expected.keys():
            raise ValueError(
                f"{label}: question set mismatch; missing={sorted(expected.keys() - indexed.keys())}; "
                f"unexpected={sorted(indexed.keys() - expected.keys())}"
            )
        for question, row in indexed.items():
            if row.get("expected_answer") != expected[question]["expected_answer"]:
                raise ValueError(f"{label}: dataset answer mismatch for {question!r}")
            rank, hit = row.get("first_relevant_rank"), row.get("hit")
            if (
                "first_relevant_rank" not in row
                or (rank is not None and (type(rank) is not int or not 1 <= rank <= 3))
                or type(hit) is not bool
                or hit != (rank is not None)
            ):
                raise ValueError(f"{label}: invalid rank/hit for {question!r}")
            latency = row.get("latency_ms")
            if (
                type(latency) not in (int, float)
                or not math.isfinite(latency)
                or latency < 0
            ):
                raise ValueError(f"{label}: invalid latency for {question!r}")
        indexed_reports.append(indexed)
        summaries.append(summarize(list(indexed.values())))
    rows = []
    for question in expected:
        left, right = (report[question] for report in indexed_reports)
        if not left["hit"] and right["hit"]:
            outcome = "improved"
        elif left["hit"] and not right["hit"]:
            outcome = "regressed"
        elif left["first_relevant_rank"] != right["first_relevant_rank"]:
            outcome = "rank_changed"
        else:
            outcome = "unchanged"
        rows.append(
            {
                "question": question,
                "baseline_rank": left["first_relevant_rank"],
                "baseline_hit": left["hit"],
                "contextual_rank": right["first_relevant_rank"],
                "contextual_hit": right["hit"],
                "outcome": outcome,
            }
        )
    left, right = summaries
    return {
        "rows": rows,
        "baseline": left,
        "contextual": right,
        "difference": {
            "hit_rate_pp": (right["hit_rate"] - left["hit_rate"]) * 100,
            "mrr": right["mrr"] - left["mrr"],
            "average_latency_ms": right["average_latency_ms"]
            - left["average_latency_ms"],
        },
    }


def format_comparison(comparison):
    lines = [
        PROXY_NOTICE,
        "Hit Rate@3 and MRR@3 are substring/source relevance proxies, not semantic relevance or answer-quality measurements.",
        "Single-run latency is not a controlled benchmark (baseline runs first; model/cache warm-up may affect timings).",
        "Ranks refer to deduplicated parents from up to three child hits.",
        "improved/regressed: miss-to-hit/hit-to-miss; rank_changed: both hit at different ranks; otherwise unchanged.",
        "",
        f"{'Question':60} | B rank | B hit | C rank | C hit | Outcome",
    ]
    for row in comparison["rows"]:
        question = " ".join(row["question"].split())
        if len(question) > 60:
            question = question[:57] + "..."
        lines.append(
            f"{question:60} | {str(row['baseline_rank']):6} | {str(row['baseline_hit']):5} | "
            f"{str(row['contextual_rank']):6} | {str(row['contextual_hit']):5} | {row['outcome']}"
        )
    left, right, delta = (
        comparison[key] for key in ("baseline", "contextual", "difference")
    )
    lines.extend(
        [
            "\nMetric | Baseline | Contextual | Difference (contextual - baseline)",
            f"Hit Rate@3 (proxy) | {left['hit_rate']:.2%} | {right['hit_rate']:.2%} | {delta['hit_rate_pp']:+.2f} pp",
            f"MRR@3 (proxy) | {left['mrr']:.4f} | {right['mrr']:.4f} | {delta['mrr']:+.4f}",
            f"Average retrieval latency (ms) | {left['average_latency_ms']:.2f} | {right['average_latency_ms']:.2f} | {delta['average_latency_ms']:+.2f}",
        ]
    )
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--contextual-data-path",
        type=Path,
        default=contextual.PARENT_PATH.parent,
        help="Directory containing the contextual parents.json and chroma/ store.",
    )
    args = parser.parse_args(argv)
    if baseline.DATASET_PATH.resolve() != contextual.DATASET_PATH.resolve():
        raise ValueError("Evaluator dataset paths do not match")
    cases = load_cases(baseline.DATASET_PATH, expected_count=20)
    index_questions(cases, "Dataset")  # Reject duplicates before loading stores/models.
    print(PROXY_NOTICE)

    def baseline_children(persist_directory, collection_name):
        client = chromadb.PersistentClient(path=persist_directory)
        collection = client.get_collection(name=collection_name)
        return contextual.existing_child_store(client, collection)

    baseline_parents, baseline_store = baseline.load_stores(
        cases, ParentChildStore, baseline_children, chromadb.PersistentClient
    )
    contextual_parents, contextual_store = contextual.load_stores(
        cases,
        ParentChildStore,
        contextual.existing_child_store,
        chromadb.PersistentClient,
        parent_path=args.contextual_data_path / "parents.json",
        chroma_path=args.contextual_data_path / "chroma",
    )
    embedding = contextual.load_embedding_service()
    baseline_service = ParentChildRetrievalService(
        embedding, baseline_store, baseline_parents
    )
    contextual_service = ParentChildRetrievalService(
        embedding, contextual_store, contextual_parents
    )
    print(f"Dataset: {baseline.DATASET_PATH} (20 questions; child top_k=3)")
    baseline_report = evaluate(cases, baseline_service, top_k=3)
    contextual_report = evaluate(cases, contextual_service, top_k=3)
    print(format_comparison(compare_reports(cases, baseline_report, contextual_report)))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError) as exc:
        raise SystemExit(f"Comparison failed: {exc}") from exc
