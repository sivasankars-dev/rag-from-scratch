"""Offline-testable retrieval metrics using an explicitly limited text proxy."""

import json
from pathlib import Path
import time

PROXY_NOTICE = (
    "RELEVANCE PROXY ONLY: normalized expected_answer substring in parent text "
    "from expected_source. Not human-verified semantic relevance or answer evaluation. "
    "Paraphrases can cause false negatives; partial/context-insensitive matches can "
    "cause false positives. Ranks refer to deduplicated parents, not child ranks."
)


def normalize_text(text):
    return " ".join(text.casefold().split())


def validate_cases(cases, expected_count=None):
    if not isinstance(cases, list) or not cases:
        raise ValueError("Dataset must be a nonempty JSON list of question objects.")
    if expected_count is not None and len(cases) != expected_count:
        raise ValueError(f"Expected {expected_count} questions, found {len(cases)}.")
    for index, case in enumerate(cases, start=1):
        if not isinstance(case, dict):
            raise ValueError(f"Dataset case {index} must be an object.")
        for field in ("question", "expected_answer", "expected_source"):
            value = case.get(field)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"Dataset case {index}: {field} must be a nonempty string.")
    # expected_chunk belongs to the Level 2 index and is deliberately not used.


def load_cases(path, expected_count=20):
    path = Path(path)
    try:
        cases = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"Cannot read evaluation dataset {path}: {exc}") from exc
    validate_cases(cases, expected_count)
    return cases


def first_matching_rank(parents, expected_answer, expected_source, top_k=3):
    needle = normalize_text(expected_answer)
    if not needle:
        raise ValueError("expected_answer must not be blank.")
    for rank, parent in enumerate(parents[:top_k], start=1):
        if (parent["source"] == expected_source
                and needle in normalize_text(parent["text"])):
            return rank
    return None


def reciprocal_rank(rank):
    if rank is None:
        return 0.0
    if isinstance(rank, bool) or not isinstance(rank, int) or rank < 1:
        raise ValueError("rank must be a positive integer or None.")
    return 1.0 / rank


def summarize(results):
    count = len(results)
    return {
        "questions": count,
        "hit_rate": sum(row["hit"] for row in results) / count if count else 0.0,
        "mrr": sum(reciprocal_rank(row["first_relevant_rank"]) for row in results)
        / count if count else 0.0,
        "average_latency_ms": sum(row["latency_ms"] for row in results)
        / count if count else 0.0,
    }


def evaluate(cases, retrieval_service, top_k=3, clock=None, show_context=False):
    validate_cases(cases)
    if isinstance(top_k, bool) or not isinstance(top_k, int) or top_k < 1:
        raise ValueError("top_k must be a positive integer.")
    clock = time.perf_counter if clock is None else clock
    results = []
    for case in cases:
        start = clock()
        parents = retrieval_service.retrieve(case["question"], top_k=top_k)
        elapsed_ms = (clock() - start) * 1000
        rank = first_matching_rank(
            parents, case["expected_answer"], case["expected_source"], top_k
        )
        results.append({
            "question": case["question"],
            "expected_answer": case["expected_answer"],
            "first_relevant_rank": rank,
            "hit": rank is not None,
            "latency_ms": elapsed_ms,
            "parents_returned": len(parents),
        })
        if show_context and rank is None:
            results[-1]["failed_context"] = [
                {
                    "rank": index,
                    "source": parent.get("source", "Unknown"),
                    "page_number": parent.get("page_number", "Unknown"),
                    "parent_id": parent.get("parent_id", "Unknown"),
                    "preview": text_preview(parent["text"]),
                }
                for index, parent in enumerate(parents, start=1)
            ]
    return {"top_k": top_k, "results": results, "summary": summarize(results)}


def text_preview(text):
    """Keep original case, collapse whitespace, and cap previews at 500 characters."""
    text = " ".join(text.split())
    return text if len(text) <= 500 else text[:497] + "..."


def format_report(report):
    lines = [PROXY_NOTICE]
    for row in report["results"]:
        lines.extend([
            "",
            f"Question: {row['question']}",
            f"Expected answer: {row['expected_answer']}",
            f"First relevant parent rank (proxy): {row['first_relevant_rank']}",
            f"Hit: {row['hit']}",
            f"Parents returned: {row['parents_returned']}",
            f"Retrieval latency: {row['latency_ms']:.2f} ms",
        ])
        if "failed_context" in row:
            lines.append(
                "Diagnostic: substring/source proxy did not match; "
                "this is not a confirmed semantic retrieval failure."
            )
            if not row["failed_context"]:
                lines.append("No parent chunks returned.")
            for parent in row["failed_context"]:
                lines.extend([
                    f"Parent rank: {parent['rank']}",
                    f"Source: {parent['source']}",
                    f"Page number: {parent['page_number']}",
                    f"Parent ID: {parent['parent_id']}",
                    f"Text preview: {parent['preview']}",
                ])
    summary = report["summary"]
    k = report["top_k"]
    lines.extend([
        "\n--- Parent-Child retrieval: text-proxy metrics ---",
        f"Questions evaluated: {summary['questions']}",
        f"Child search cutoff: {k}; metrics rank the returned parent list",
        f"Hit Rate@{k} (proxy): {summary['hit_rate']:.2%}",
        f"MRR@{k} (proxy): {summary['mrr']:.4f}",
        f"Average retrieval latency: {summary['average_latency_ms']:.2f} ms",
    ])
    return "\n".join(lines)
