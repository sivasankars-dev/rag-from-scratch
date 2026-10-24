
"""Ingest selected handbook sections into the Neo4j knowledge graph."""

import argparse
import importlib.util
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from neo4j import GraphDatabase

ROOT = Path(__file__).resolve().parents[3]
LEVEL2 = ROOT / "levels" / "level-2-practical-rag"
LEVEL3 = ROOT / "levels" / "level-3-advanced-rag"
PDF_PATH = ROOT / "data" / "documents" / "rag_practice_employee_handbook.pdf"

sys.path.insert(0, str(LEVEL3))

from services.document_section_parser import parse_document_sections
from services.graph_extractor import GraphExtractor
from services.graph_store import Neo4jGraphStore


def load_module(module_name, file_path):
    """Load an existing Level 2 module without duplicating its code."""
    spec = importlib.util.spec_from_file_location(module_name, file_path)

    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load module: {file_path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def load_sections():
    """Load PDF pages and parse them into document-aware sections."""
    loader = load_module(
        "level2_graph_ingestion_document_loader",
        LEVEL2 / "services" / "document_loader.py",
    )

    pages = loader.extract_text_from_pdf(str(PDF_PATH))
    return parse_document_sections(
        pages,
        source=PDF_PATH.name,
    )


def select_sections(sections, section_number=None, all_sections=False):
    """Select numbered sections or FAQ entries for ingestion."""
    candidates = [
        section
        for section in sections
        if section["section_type"] not in {"preamble", "faq"}
        and section.get("text", "").strip()
    ]

    if section_number:
        selected = [
            section
            for section in candidates
            if section.get("section_number") == section_number
        ]
        if not selected:
            available = sorted(
                section["section_number"]
                for section in candidates
                if section.get("section_number")
            )
            raise ValueError(
                f"Section {section_number!r} not found. "
                f"Available section numbers: {', '.join(available)}"
            )
        return selected

    if all_sections:
        return candidates

    raise ValueError(
        "Choose --section-number NUMBER or explicitly pass --all-sections"
    )


def build_metadata(section):
    """Build source metadata expected by GraphExtractor and GraphStore."""
    return {
        "source": section["document_id"],
        "section_id": section["section_id"],
        "section_number": section.get("section_number"),
        "section_title": section["section_title"],
        "section_type": section["section_type"],
        "section_path": section["section_path"],
        "start_page": section["start_page"],
        "end_page": section["end_page"],
    }


def main():
    parser = argparse.ArgumentParser(
        description="Ingest selected handbook sections into Neo4j."
    )
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument(
        "--section-number",
        help="Ingest one numbered section, e.g. 2.2.",
    )
    selection.add_argument(
        "--all-sections",
        action="store_true",
        help="Ingest every eligible section and FAQ item; this makes LLM calls.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List selected sections without calling the LLM or writing to Neo4j.",
    )
    args = parser.parse_args()

    if not PDF_PATH.is_file():
        parser.error(f"Handbook PDF not found: {PDF_PATH}")

    sections = load_sections()

    try:
        selected = select_sections(
            sections,
            section_number=args.section_number,
            all_sections=args.all_sections,
        )
    except ValueError as error:
        parser.error(str(error))

    print(f"Parsed sections: {len(sections)}")
    print(f"Selected sections: {len(selected)}")

    for section in selected:
        print(
            f"- {section['section_id']} | "
            f"{section['section_title']} | "
            f"pages {section['start_page']}-{section['end_page']}"
        )

    if args.dry_run:
        print("\nDry run complete. No LLM calls or Neo4j writes performed.")
        return

    load_dotenv(dotenv_path=ROOT / ".env")

    uri = os.getenv("NEO4J_URI")
    username = os.getenv("NEO4J_USERNAME")
    password = os.getenv("NEO4J_PASSWORD")

    if not all([uri, username, password]):
        parser.error(
            "Missing NEO4J_URI, NEO4J_USERNAME, or NEO4J_PASSWORD in .env"
        )

    llm_module = load_module(
        "level2_graph_ingestion_llm_client",
        LEVEL2 / "services" / "llm_client.py",
    )

    driver = GraphDatabase.driver(uri, auth=(username, password))
    succeeded = 0
    failed = []

    try:
        driver.verify_connectivity()
        graph_store = Neo4jGraphStore(driver)
        graph_store.ensure_constraints()
        extractor = GraphExtractor(llm_module.OpenAILLMClient())

        for index, section in enumerate(selected, start=1):
            section_id = section["section_id"]
            text = section["text"]
            metadata = build_metadata(section)

            try:
                extraction = extractor.extract(text, metadata)
                result = graph_store.store_extraction(text, extraction)
                succeeded += 1
                print(
                    f"[{index}/{len(selected)}] OK {section_id}: "
                    f"{result['entities_stored']} entities, "
                    f"{result['relationships_stored']} relationships"
                )
            except Exception as error:
                failed.append((section_id, str(error)))
                print(f"[{index}/{len(selected)}] FAILED {section_id}: {error}")

    finally:
        driver.close()

    print("\nIngestion summary")
    print(f"Successful sections: {succeeded}")
    print(f"Failed sections: {len(failed)}")

    if failed:
        print("\nFailed section details:")
        for section_id, error in failed:
            print(f"- {section_id}: {error}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
