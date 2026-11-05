"""Command line: ask, harvest, refresh, ingest, evaluate."""

from __future__ import annotations

import argparse
import json
import logging
from datetime import date
from pathlib import Path

from services.engine import build_assistant


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="safari-ai")
    commands = parser.add_subparsers(dest="command", required=True)

    ask = commands.add_parser("ask", help="Ask the assistant")
    ask.add_argument("question")
    ask.add_argument("--as-of", dest="as_of", default=None)
    ask.add_argument("--origin", default=None)
    ask.add_argument("--passport", default=None)
    ask.add_argument("--days", type=int, default=None)
    ask.add_argument("--adults", type=int, default=None)
    ask.add_argument("--child-ages", dest="child_ages", default="", help="comma separated, e.g. 7,4")
    ask.add_argument("--no-llm", action="store_true", help="Use the deterministic composer only")
    ask.add_argument("--json", action="store_true", help="Print the full payload")

    ingest = commands.add_parser("ingest", help="Index a PDF, text, or Markdown file")
    ingest.add_argument("path")

    commands.add_parser("evaluate", help="Run evaluation/questions.json")
    harvest = commands.add_parser("harvest", help="Pull the TANAPA API, publications, and official pages")
    harvest.add_argument("--api-only", action="store_true", help="Only the TANAPA API (fees, parks, activities)")
    commands.add_parser("status", help="Show per-source sync status")

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    logging.getLogger("pypdf").setLevel(logging.ERROR)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    assistant = build_assistant()
    if args.command == "ask":
        profile = {
            key: value
            for key, value in {
                "origin": args.origin,
                "passport": args.passport,
                "days": args.days,
                "adults": args.adults,
                "child_ages": [int(item) for item in args.child_ages.split(",") if item.strip().isdigit()],
            }.items()
            if value not in (None, "", [])
        }
        result = assistant.ask(
            args.question,
            as_of=date.fromisoformat(args.as_of) if args.as_of else None,
            profile=profile,
            use_llm=False if args.no_llm else None,
        )
        if args.json:
            print(json.dumps(result, indent=2, ensure_ascii=False))
            return
        print(result["answer"])
        print()
        for citation in result["citations"]:
            print(f"[{citation['n']}] {citation['title']} — {citation['source_url']}")
        print(f"\n{result['confidence_label']} · {result['generator']} · {result['intent']} · tools: {', '.join(result['tool_calls']) or 'none'}")
        return
    if args.command == "ingest":
        from services.ingestion.pipeline import ingest_file

        document = ingest_file(assistant.store, Path(args.path))
        print(json.dumps({"document_id": document.document_id, "title": document.title, "document_type": document.document_type}, indent=2))
        return
    if args.command == "harvest":
        from services.sources.harvest import harvest, refresh_api

        if args.api_only:
            print(json.dumps(refresh_api(assistant.store, assistant.embedder), indent=2))
        else:
            print(json.dumps(harvest(assistant.store, assistant.embedder), indent=2, default=str))
        return
    if args.command == "status":
        print(json.dumps(assistant.store.source_status(), indent=2))
        return
    from services.evaluation.runner import evaluate, load_questions

    print(json.dumps(evaluate(assistant, load_questions()), indent=2))


if __name__ == "__main__":
    main()
