from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .cache import StageCache, utc_now
from .challenge import challenge_metrics, load_challenges, run_challenges
from .config import PipelineConfig, load_config
from .evidence import EvidenceService, build_concordance, build_retrieval_index
from glossary import WhitakersWordsBackend
from .pipeline import EvidenceFirstPipeline, STAGE_ORDER, write_audit_jsonl
from .reports import compare_legacy, load_jsonl
from .source import load_chunks, preprocess_book


def _json(value: Any) -> None:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except (AttributeError, OSError):
            pass
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def _select_chunks(chunks: list[dict[str, Any]], args: argparse.Namespace) -> list[dict[str, Any]]:
    selected = chunks
    requested = getattr(args, "chunk", None) or []
    if requested:
        found = []
        for value in requested:
            if value.isdigit():
                index = int(value) - 1
                if not 0 <= index < len(chunks):
                    raise ValueError(f"Chunk index out of range: {value}")
                found.append(chunks[index])
                continue
            matches = [item for item in chunks if item["chunk_id"] == value or item["chunk_id"].startswith(value)]
            if len(matches) != 1:
                raise ValueError(f"Chunk selector {value!r} matched {len(matches)} chunks")
            found.append(matches[0])
        selected = found
    else:
        start = max(1, int(getattr(args, "start", 1) or 1))
        end = getattr(args, "end", None)
        selected = chunks[start - 1 : end]
    limit = getattr(args, "limit", None)
    return selected[:limit] if limit else selected


def _add_selection(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--book", type=int, default=1)
    parser.add_argument("--chunk", action="append", help="Exact/unique-prefix chunk ID, or 1-based index; repeatable")
    parser.add_argument("--start", type=int, default=1, help="1-based first chunk when --chunk is omitted")
    parser.add_argument("--end", type=int, help="1-based inclusive final chunk when --chunk is omitted")
    parser.add_argument("--limit", type=int, help="Maximum selected chunks")


def _failed_chunk_jobs(
    config: PipelineConfig, book: int, profile: str
) -> list[dict[str, Any]]:
    """Return only attempted chunks whose current-source latest stage failed."""

    chunks = load_chunks(config, book)
    chunk_by_id = {chunk["chunk_id"]: (index, chunk) for index, chunk in enumerate(chunks, 1)}
    latest: dict[tuple[str, str], dict[str, Any]] = {}
    for record in StageCache(config.path_value("cache")).inspect():
        chunk_entry = chunk_by_id.get(str(record.get("chunk_id") or ""))
        if chunk_entry is None:
            continue
        _, chunk = chunk_entry
        if record.get("execution_profile", "production") != profile:
            continue
        record_fingerprint = (record.get("cache_material") or {}).get(
            "source_fingerprint"
        )
        if (
            record_fingerprint
            and chunk.get("source_fingerprint")
            and record_fingerprint != chunk.get("source_fingerprint")
        ):
            continue
        stage = record.get("stage")
        if not isinstance(stage, str) or stage not in STAGE_ORDER:
            continue
        key = (chunk["chunk_id"], stage)
        if key not in latest or str(record.get("finished_at", "")) > str(
            latest[key].get("finished_at", "")
        ):
            latest[key] = record

    jobs: list[dict[str, Any]] = []
    for index, chunk in enumerate(chunks, 1):
        current = {
            stage: latest[(chunk["chunk_id"], stage)]
            for stage in STAGE_ORDER
            if (chunk["chunk_id"], stage) in latest
        }
        failed_stage = next(
            (
                stage
                for stage in STAGE_ORDER
                if current.get(stage, {}).get("status")
                in {"failed", "unavailable", "incomplete"}
            ),
            None,
        )
        if failed_stage is None:
            continue
        failed = current[failed_stage]
        jobs.append(
            {
                "index": index,
                "chunk_id": chunk["chunk_id"],
                "failed_stage": failed_stage,
                "status": failed.get("status"),
                "finished_at": failed.get("finished_at"),
                "error": failed.get("error"),
                "completed_stages": [
                    stage
                    for stage in STAGE_ORDER
                    if current.get(stage, {}).get("status") == "complete"
                ],
            }
        )
    return jobs


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="jerome-pipeline", description="Evidence-first, auditable Latin-to-English pipeline for Jerome")
    parser.add_argument("--config", default="pipeline.yaml", help="Pipeline YAML path")
    sub = parser.add_subparsers(dest="command", required=True)

    preprocess = sub.add_parser("preprocess", help="Parse source and write canonical units/chunks")
    preprocess.add_argument("--book", type=int, default=1)
    inspect_chunks = sub.add_parser("inspect-chunks", help="Inspect canonical processing chunks")
    _add_selection(inspect_chunks)
    inspect_chunks.add_argument("--full", action="store_true")
    concordance = sub.add_parser(
        "build-concordance", help="Build exact/normalized/lemma concordance"
    )
    concordance.add_argument("--book", type=int, action="append", dest="books")
    concordance.add_argument("--no-lemmas", action="store_true")
    retrieval = sub.add_parser(
        "build-retrieval-index",
        help="Build persisted inspectable local Latin retrieval vectors",
    )
    search_corpus = sub.add_parser(
        "search-corpus", help="Inspect persisted local retrieval results"
    )
    search_corpus.add_argument("--query", required=True)
    search_corpus.add_argument("--limit", type=int, default=8)

    run = sub.add_parser("run", help="Run selected chunks through a stage or the full pipeline")
    _add_selection(run)
    run.add_argument("--through", choices=STAGE_ORDER, default="finalize")
    run.add_argument("--force-stage", choices=STAGE_ORDER)
    run.add_argument("--retry-failed", action="store_true")
    run.add_argument("--profile", choices=["production", "smoke"], default="production")
    resume = sub.add_parser("resume", help="Resume selected chunks and retry failed stages")
    _add_selection(resume)
    resume.add_argument("--through", choices=STAGE_ORDER, default="finalize")
    resume.add_argument("--force-stage", choices=STAGE_ORDER)
    resume.add_argument("--profile", choices=["production", "smoke"], default="production")
    refinalize = sub.add_parser(
        "refinalize",
        help="Reapply local finalization policy to cached adjudication without providers",
    )
    _add_selection(refinalize)
    refinalize.add_argument(
        "--profile", choices=["production", "smoke"], default="production"
    )
    refinalize.add_argument(
        "--force", action="store_true", help="Archive and replace the current policy result"
    )
    validate_witnesses = sub.add_parser(
        "validate-witnesses",
        help="Apply the local witness contract gate to cached responses without providers",
    )
    _add_selection(validate_witnesses)
    validate_witnesses.add_argument(
        "--profile", choices=["production", "smoke"], default="production"
    )
    validate_witnesses.add_argument("--force", action="store_true")
    failed = sub.add_parser(
        "failed-chunks",
        help="List attempted chunks whose current-source latest stage failed",
    )
    failed.add_argument("--book", type=int, default=1)
    failed.add_argument("--profile", choices=["production", "smoke"], default="production")
    resume_failed = sub.add_parser(
        "resume-failed",
        help="Resume only the current snapshot of failed attempted chunks",
    )
    resume_failed.add_argument("--book", type=int, default=1)
    resume_failed.add_argument("--profile", choices=["production", "smoke"], default="production")
    resume_failed.add_argument("--through", choices=STAGE_ORDER, default="finalize")
    resume_failed.add_argument("--limit", type=int)
    resume_failed.add_argument(
        "--dry-run",
        action="store_true",
        help="List the selected failed chunks without running providers",
    )

    benchmark = sub.add_parser("benchmark-witness", help="Run an isolated optional/experimental witness")
    _add_selection(benchmark)
    benchmark.add_argument("--model-role", default="experimental_translategemma")
    benchmark.add_argument("--force", action="store_true")
    benchmark.add_argument("--retry-failed", action="store_true")

    inspect_cache = sub.add_parser("inspect-cache", help="Inspect independently cached stage records")
    inspect_cache.add_argument("--chunk")
    inspect_cache.add_argument("--stage")
    inspect_cache.add_argument("--summary", action="store_true")
    inspect_cache.add_argument("--attempts", action="store_true")
    inspect_cache.add_argument(
        "--challenge",
        action="store_true",
        help="Inspect the isolated artifacts/challenge-cache instead",
    )
    inspect_evidence = sub.add_parser("inspect-evidence", help="Inspect requests and retrieved receipts")
    inspect_evidence.add_argument("--chunk", required=True)
    flags = sub.add_parser("review-flags", help="List precise human-review/unresolved flags")
    flags.add_argument("--book", type=int, default=1)
    export = sub.add_parser("export-audit", help="Export complete per-chunk provenance JSONL")
    export.add_argument("--book", type=int, default=1)
    export.add_argument("--output")

    compare = sub.add_parser("compare-v4", help="Compare explicit v4/v4.1 artifacts with new audits")
    compare.add_argument("--book", type=int, default=1)
    compare.add_argument("--audit")
    compare.add_argument("--qwen")
    compare.add_argument("--mistral")
    compare.add_argument("--prosecutor")
    compare.add_argument("--review")
    compare.add_argument("--output")

    challenge = sub.add_parser("challenge", help="Run/report the blinded project challenge set")
    challenge_sub = challenge.add_subparsers(dest="challenge_command", required=True)
    challenge_inspect = challenge_sub.add_parser("inspect", help="Show challenge metadata (never sent as model labels)")
    challenge_inspect.add_argument("--case")
    challenge_run = challenge_sub.add_parser("run", help="Run challenge reviewer and metrics")
    challenge_mode = challenge_run.add_mutually_exclusive_group()
    challenge_mode.add_argument("--deterministic-only", action="store_true")
    challenge_mode.add_argument(
        "--full-pipeline",
        action="store_true",
        help="Inject each frozen candidate into both witnesses, then run all staged review/evidence/adjudication steps",
    )
    challenge_sub.add_parser("report", help="Report most recent challenge metrics")

    editorial = sub.add_parser("record-editorial", help="Append a versioned editorial/review decision")
    editorial.add_argument("--kind", choices=["decision", "human_review", "resolution"], required=True)
    editorial.add_argument("--source-unit", action="append", required=True)
    editorial.add_argument("--issue", required=True)
    editorial.add_argument("--decision")
    editorial.add_argument("--supersedes")
    inspect_editorial = sub.add_parser("inspect-editorial", help="Inspect append-only editorial records")
    inspect_editorial.add_argument("--kind", choices=["decision", "human_review", "resolution"])
    review = sub.add_parser(
        "review", help="Open the local append-only editorial workspace"
    )
    review.add_argument("--book", type=int, default=1)
    review.add_argument("--profile", choices=["production", "smoke"], default="production")
    review.add_argument("--host", default="127.0.0.1")
    review.add_argument("--port", type=int, default=8765)
    review.add_argument(
        "--no-browser",
        action="store_true",
        help="Start the local server without opening a browser",
    )
    return parser


def _pipeline(config: PipelineConfig) -> EvidenceFirstPipeline:
    return EvidenceFirstPipeline(config)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = load_config(args.config)
    if args.command == "review":
        from .review_server import serve_review

        serve_review(
            config,
            book=args.book,
            profile=args.profile,
            host=args.host,
            port=args.port,
            open_browser=not args.no_browser,
        )
        return 0
    if args.command == "preprocess":
        parsed, chunks = preprocess_book(config, args.book)
        _json({"book": args.book, "source_path": str(config.source_path(args.book)), "source_fingerprint": parsed["source_fingerprint"], "clean_characters": len(parsed["text"]), "source_units": len(parsed["source_units"]), "page_markers": len(parsed["page_markers"]), "annotations": len(parsed["annotations"]), "unmatched_footnote_definitions": parsed["unmatched_footnote_definitions"], "chunks": len(chunks), "artifact_dir": str(config.path_value("artifacts") / f"book{args.book:02d}")})
        return 0
    if args.command == "inspect-chunks":
        all_chunks = load_chunks(config, args.book)
        chunks = _select_chunks(all_chunks, args)
        if args.full:
            _json(chunks)
        else:
            _json([{"index": all_chunks.index(chunk) + 1, "chunk_id": chunk["chunk_id"], "source_unit_ids": chunk["source"]["source_unit_ids"], "pages": chunk["source"]["pages"], "target_chars": len(chunk["target_latin"]), "context_before_chars": len(chunk["context_before"]), "context_after_chars": len(chunk["context_after"]), "annotations": len(chunk["annotations"]), "preview": chunk["target_latin"][:180]} for chunk in chunks])
        return 0
    if args.command == "build-concordance":
        _json(build_concordance(config, books=args.books, include_lemmas=not args.no_lemmas))
        return 0
    if args.command == "build-retrieval-index":
        _json(build_retrieval_index(config))
        return 0
    if args.command == "search-corpus":
        pipeline = _pipeline(config)
        if pipeline.evidence.retrieval is None:
            _json(
                {
                    "status": "unavailable",
                    "message": "Run build-retrieval-index first",
                }
            )
            return 1
        _json(
            {
                "status": "found",
                "method": pipeline.evidence.retrieval.identity,
                "results": pipeline.evidence.retrieval.search(
                    args.query, limit=args.limit
                ),
            }
        )
        return 0
    if args.command in {"run", "resume"}:
        # Auto-rebuild stale concordance/retrieval index if needed
        try:
            EvidenceService.from_config(config, WhitakersWordsBackend())
        except ValueError as e:
            if "stale" in str(e) or "does not match" in str(e):
                print(f"[auto-rebuild] {e}", flush=True)
                build_concordance(config, books=[args.book], include_lemmas=False)
                build_retrieval_index(config)
                print("[auto-rebuild] Complete", flush=True)
            else:
                raise

        chunks = _select_chunks(load_chunks(config, args.book), args)
        pipeline = EvidenceFirstPipeline(config, model_profile=args.profile)
        retry = bool(getattr(args, "retry_failed", False) or args.command == "resume")
        overall = []
        for index, chunk in enumerate(chunks, 1):
            print(f"[{index}/{len(chunks)}] {chunk['chunk_id']} through={args.through} profile={args.profile}", flush=True)
            result = pipeline.run_chunk(chunk, through=args.through, force_stage=args.force_stage, retry_failed=retry)
            summary = {key: value for key, value in result.items() if key != "records"}
            overall.append(summary)
            _json(summary)
        return 1 if any(item["status"] == "incomplete" for item in overall) else 0
    if args.command == "refinalize":
        chunks = _select_chunks(load_chunks(config, args.book), args)
        pipeline = EvidenceFirstPipeline(config, model_profile=args.profile)
        results = []
        for index, chunk in enumerate(chunks, 1):
            print(
                f"[{index}/{len(chunks)}] {chunk['chunk_id']} "
                f"local-policy-only profile={args.profile}",
                flush=True,
            )
            result = pipeline.refinalize_chunk(chunk, force=args.force)
            results.append(result)
            _json(result)
        return 0
    if args.command == "validate-witnesses":
        chunks = _select_chunks(load_chunks(config, args.book), args)
        pipeline = EvidenceFirstPipeline(config, model_profile=args.profile)
        results = []
        for index, chunk in enumerate(chunks, 1):
            print(
                f"[{index}/{len(chunks)}] {chunk['chunk_id']} "
                f"local-witness-validation-only profile={args.profile}",
                flush=True,
            )
            result = pipeline.validate_cached_witnesses(chunk, force=args.force)
            results.append(result)
            _json(result)
        # A single-valid quorum is a deliberate safe degraded path, not a
        # validation command failure. Only a blocked both-invalid quorum should
        # produce a non-zero exit code.
        return 1 if any(item.get("status") == "both_invalid" for item in results) else 0
    if args.command == "failed-chunks":
        _json(_failed_chunk_jobs(config, args.book, args.profile))
        return 0
    if args.command == "resume-failed":
        jobs = _failed_chunk_jobs(config, args.book, args.profile)
        if args.limit:
            jobs = jobs[: args.limit]
        if args.dry_run or not jobs:
            _json(jobs)
            return 0
        chunks_by_id = {
            chunk["chunk_id"]: chunk for chunk in load_chunks(config, args.book)
        }
        pipeline = EvidenceFirstPipeline(config, model_profile=args.profile)
        overall = []
        for index, job in enumerate(jobs, 1):
            chunk = chunks_by_id[job["chunk_id"]]
            print(
                f"[{index}/{len(jobs)}] {chunk['chunk_id']} "
                f"failed_stage={job['failed_stage']} through={args.through} "
                f"profile={args.profile}",
                flush=True,
            )
            result = pipeline.run_chunk(
                chunk,
                through=args.through,
                retry_failed=True,
            )
            summary = {key: value for key, value in result.items() if key != "records"}
            overall.append(summary)
            _json(summary)
        return 1 if any(item["status"] == "incomplete" for item in overall) else 0
    if args.command == "benchmark-witness":
        chunks = _select_chunks(load_chunks(config, args.book), args)
        pipeline = _pipeline(config)
        results = [
            pipeline.run_experimental_witness(
                chunk,
                role=args.model_role,
                force=args.force,
                retry_failed=args.retry_failed,
            )
            for chunk in chunks
        ]
        _json(
            [
                {
                    "chunk_id": item.get("chunk_id"),
                    "stage": item.get("stage"),
                    "status": item.get("status"),
                    "model": item.get("model"),
                    "error": item.get("error"),
                }
                for item in results
            ]
        )
        return 1 if any(item.get("status") != "complete" for item in results) else 0
    if args.command == "inspect-cache":
        cache = (
            StageCache(config.path_value("artifacts") / "challenge-cache")
            if args.challenge
            else _pipeline(config).cache
        )
        records = cache.inspect(
            chunk_id=args.chunk,
            stage=args.stage,
            include_attempts=args.attempts,
        )
        if args.summary:
            records = [{"chunk_id": item.get("chunk_id"), "stage": item.get("stage"), "status": item.get("status"), "finished_at": item.get("finished_at"), "model": item.get("model"), "error": item.get("error"), "cache_key": item.get("cache_key")} for item in records]
        _json(records)
        return 0
    if args.command == "inspect-evidence":
        records = _pipeline(config).cache.inspect(chunk_id=args.chunk)
        evidence = []
        for item in records:
            if item.get("stage") in {"research_prosecutor", "research_adjudicator"}:
                evidence.append(item)
            elif item.get("stage") in {"prosecutor_initial", "adjudicator"}:
                evidence.append({"stage": item["stage"], "status": item["status"], "evidence_requests": (item.get("output") or {}).get("evidence_requests", [])})
        _json(evidence)
        return 0
    if args.command in {"review-flags", "export-audit"}:
        chunks = load_chunks(config, args.book)
        pipeline = _pipeline(config)
        audits = [pipeline.assemble_audit(chunk) for chunk in chunks]
        if args.command == "review-flags":
            _json([{"chunk_id": audit["chunk_id"], "final_status": audit["final_status"], "human_review_requests": audit["human_review_requests"], "unresolved_issues": audit["unresolved_issues"]} for audit in audits if audit["final_status"] in {"human_review", "unresolved", "incomplete"} or audit["human_review_requests"] or audit["unresolved_issues"]])
        else:
            output = Path(args.output).resolve() if args.output else config.path_value("artifacts") / f"book{args.book:02d}" / "audit.jsonl"
            write_audit_jsonl(output, audits)
            _json({"output": str(output), "records": len(audits)})
        return 0
    if args.command == "compare-v4":
        audit_path = Path(args.audit).resolve() if args.audit else config.path_value("artifacts") / f"book{args.book:02d}" / "audit.jsonl"
        if audit_path.exists():
            audits = load_jsonl(audit_path)
        else:
            pipeline = _pipeline(config)
            audits = [pipeline.assemble_audit(chunk) for chunk in load_chunks(config, args.book)]
        report = compare_legacy(audits, qwen_path=Path(args.qwen).resolve() if args.qwen else None, mistral_path=Path(args.mistral).resolve() if args.mistral else None, prosecutor_path=Path(args.prosecutor).resolve() if args.prosecutor else None, review_path=Path(args.review).resolve() if args.review else None)
        if args.output:
            path = Path(args.output).resolve()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            _json({"output": str(path), "chunks": len(report), "comparisons_available": sum(item["comparison_available"] for item in report)})
        else:
            _json(report)
        return 0
    if args.command == "challenge":
        if args.challenge_command == "inspect":
            cases = load_challenges(config.path_value("challenge_set"))
            if args.case:
                cases = [item for item in cases if item["case_id"] == args.case]
            _json(cases)
        elif args.challenge_command == "run":
            results = run_challenges(
                config,
                deterministic_only=args.deterministic_only,
                full_pipeline=args.full_pipeline,
            )
            _json({"metrics": challenge_metrics(results), "results_path": str(config.path_value("challenge_results"))})
        else:
            results = load_jsonl(config.path_value("challenge_results"))
            _json({"metrics": challenge_metrics(results), "results": results})
        return 0
    if args.command == "record-editorial":
        record = {"editorial_id": f"ed-{utc_now().replace(':', '').replace('-', '').replace('.', '')}", "timestamp": utc_now(), "kind": args.kind, "source_unit_ids": args.source_unit, "issue": args.issue, "decision": args.decision, "supersedes": args.supersedes, "evidence_scope": "editorial_decision_not_lexical_evidence"}
        path_key = "human_reviews" if args.kind == "human_review" else "editorial_decisions"
        path = config.path_value(path_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
        _json({"saved": str(path), "record": record})
        return 0
    if args.command == "inspect-editorial":
        records = load_jsonl(config.path_value("editorial_decisions")) + load_jsonl(config.path_value("human_reviews"))
        if args.kind:
            records = [item for item in records if item.get("kind") == args.kind]
        _json(records)
        return 0
    raise AssertionError(f"Unhandled command {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
