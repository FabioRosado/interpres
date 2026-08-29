from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from glossary import WhitakersWordsBackend

from .cache import StageCache, utc_now
from .challenge import challenge_metrics, load_challenges, run_challenges
from .config import PipelineConfig, load_config
from .evidence import EvidenceService, build_concordance, build_retrieval_index
from .pipeline import STAGE_ORDER, EvidenceFirstPipeline, write_audit_jsonl
from .reports import compare_legacy, load_jsonl
from .source import load_chunks, preprocess_book


def _json(value: Any) -> None:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except (AttributeError, OSError):
            pass
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def _format_duration(milliseconds: Any) -> str:
    try:
        value = int(milliseconds)
    except (TypeError, ValueError):
        return "?"
    if value < 1000:
        return f"{value}ms"
    seconds = value / 1000
    if seconds < 60:
        return f"{seconds:.1f}s" if seconds < 10 else f"{seconds:.0f}s"
    minutes = int(seconds // 60)
    remaining = int(round(seconds - minutes * 60))
    if remaining == 60:
        minutes += 1
        remaining = 0
    return f"{minutes}m {remaining:02d}s"


def _short_chunk_id(chunk_id: str) -> str:
    match = re.search(r"-([0-9a-f]{8,16})$", chunk_id)
    if match:
        return match.group(1)
    return chunk_id[:12]


def _chunk_label(chunk: dict[str, Any]) -> str:
    chunk_id = str(chunk.get("chunk_id") or "")
    candidates = [chunk_id]
    source = chunk.get("source") if isinstance(chunk.get("source"), dict) else {}
    candidates.extend(str(item) for item in source.get("source_unit_ids") or [])
    candidates.extend(str(item) for item in source.get("section_ids") or [])
    for unit in chunk.get("source_units") or []:
        if not isinstance(unit, dict):
            continue
        for key in ("canonical_parent_id", "source_unit_id"):
            if unit.get(key):
                candidates.append(str(unit[key]))
    for value in candidates:
        match = re.search(
            r"homily-(\d+)-section-(\d+)(?:\.p(\d+))?",
            value,
            flags=re.IGNORECASE,
        )
        if match:
            label = f"Homily {int(match.group(1))} section {int(match.group(2))}"
            if match.group(3):
                label += f".p{int(match.group(3)):03d}"
            return label
    pages = source.get("pages") or []
    if pages:
        return "pages " + ",".join(str(page) for page in pages[:3])
    return chunk_id[:48] if chunk_id else "chunk"


def _progress_descriptor(
    chunk: dict[str, Any],
    *,
    selected_index: int,
    selected_total: int,
    global_index: int,
) -> dict[str, Any]:
    chunk_id = str(chunk.get("chunk_id") or "")
    return {
        "selected_index": selected_index,
        "selected_total": selected_total,
        "global_index": global_index,
        "label": _chunk_label(chunk),
        "short_id": _short_chunk_id(chunk_id),
    }


def _progress_prefix(descriptor: dict[str, Any] | None) -> str:
    if not descriptor:
        return "[chunk ?]"
    return (
        f"[{descriptor['selected_index']}/{descriptor['selected_total']} | "
        f"chunk {descriptor['global_index']}] "
        f"{descriptor['label']} ({descriptor['short_id']})"
    )


def _progress_descriptors(
    chunks: list[dict[str, Any]],
    all_chunks: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    global_indices = {
        chunk["chunk_id"]: index
        for index, chunk in enumerate(all_chunks, 1)
    }
    return {
        chunk["chunk_id"]: _progress_descriptor(
            chunk,
            selected_index=index,
            selected_total=len(chunks),
            global_index=global_indices.get(chunk["chunk_id"], index),
        )
        for index, chunk in enumerate(chunks, 1)
    }


def _print_progress_event(
    event: dict[str, Any],
    descriptors: dict[str, dict[str, Any]],
    *,
    resume_failed_stages: dict[str, str] | None = None,
) -> None:
    ev = event.get("event")
    chunk_id = str(event.get("chunk_id") or "")
    descriptor = descriptors.get(chunk_id)
    if ev == "chunk_start":
        failed_stage = (resume_failed_stages or {}).get(chunk_id)
        verb = "resuming" if failed_stage else "starting"
        failed_text = f" failed_stage={failed_stage}" if failed_stage else ""
        print(
            f"\n{_progress_prefix(descriptor)} {verb}{failed_text} through={event.get('through')} profile={event.get('profile')}",
            flush=True,
        )
    elif ev == "stage_start":
        stage = event.get("stage")
        model = event.get("model") or {}
        provider = model.get("provider", "local")
        model_name = model.get("model")
        model_label = provider if not model_name else f"{provider}/{model_name}"
        print(f"  -> {stage} [{model_label}]", flush=True)
    elif ev == "stage_complete":
        stage = event.get("stage")
        status = event.get("status")
        cached = event.get("cached")
        duration = event.get("duration_ms")
        tag = "cached" if cached else _format_duration(duration)
        print(f"  <- {stage} [{status}] ({tag})", flush=True)
    elif ev == "chunk_complete":
        completed = event.get("completed_stages", [])
        status = event.get("status")
        if status == "incomplete":
            print(
                f"{_progress_prefix(descriptor)} stopped at {event.get('failed_stage')} after {len(completed)} completed stages",
                flush=True,
            )
        else:
            print(
                f"{_progress_prefix(descriptor)} finished status={status} completed_stages={len(completed)}",
                flush=True,
            )


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
    parser = argparse.ArgumentParser(
        prog="interpres",
        description="Evidence-first, human-in-the-loop translation pipeline for historical texts.",
    )
    parser.add_argument(
        "--config",
        default="pipeline.yaml",
        help="Pipeline YAML path (default: pipeline.yaml)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # ── project commands ──────────────────────────────────────────
    project = sub.add_parser("project", help="Manage Interpres projects")
    project_sub = project.add_subparsers(dest="project_command", required=True)
    project_list = project_sub.add_parser("list", help="List available projects")
    project_show = project_sub.add_parser("show", help="Show project details")
    project_show.add_argument("name", nargs="?", default=None, help="Project directory name")

    # ── doctor ────────────────────────────────────────────────────
    doctor = sub.add_parser("doctor", help="Verify installation and project setup")

    # ── source & retrieval ────────────────────────────────────────
    preprocess = sub.add_parser("preprocess", help="Parse source and write canonical units/chunks")
    preprocess.add_argument("project", nargs="?", default=None, help="Project directory name (default: auto-detect)")
    preprocess.add_argument("--book", type=int, default=1)
    inspect_chunks = sub.add_parser("inspect-chunks", help="Inspect canonical processing chunks")
    inspect_chunks.add_argument("project", nargs="?", default=None)
    _add_selection(inspect_chunks)
    inspect_chunks.add_argument("--full", action="store_true")
    concordance = sub.add_parser(
        "build-concordance", help="Build exact/normalized/lemma concordance"
    )
    concordance.add_argument("project", nargs="?", default=None)
    concordance.add_argument("--book", type=int, action="append", dest="books")
    concordance.add_argument("--no-lemmas", action="store_true")
    retrieval = sub.add_parser(
        "build-retrieval-index",
        help="Build persisted inspectable local retrieval vectors",
    )
    retrieval.add_argument("project", nargs="?", default=None)
    search_corpus = sub.add_parser(
        "search-corpus", help="Inspect persisted local retrieval results"
    )
    search_corpus.add_argument("project", nargs="?", default=None)
    search_corpus.add_argument("--query", required=True)
    search_corpus.add_argument("--limit", type=int, default=8)

    # ── pipeline ──────────────────────────────────────────────────
    run = sub.add_parser("run", help="Run selected chunks through a stage or the full pipeline")
    run.add_argument("project", nargs="?", default=None)
    _add_selection(run)
    run.add_argument("--through", choices=STAGE_ORDER, default="finalize")
    run.add_argument("--force-stage", choices=STAGE_ORDER)
    run.add_argument("--retry-failed", action="store_true")
    run.add_argument("--profile", choices=["production", "smoke"], default="production")
    resume = sub.add_parser("resume", help="Resume selected chunks and retry failed stages")
    resume.add_argument("project", nargs="?", default=None)
    _add_selection(resume)
    resume.add_argument("--through", choices=STAGE_ORDER, default="finalize")
    resume.add_argument("--force-stage", choices=STAGE_ORDER)
    resume.add_argument("--profile", choices=["production", "smoke"], default="production")
    refinalize = sub.add_parser(
        "refinalize",
        help="Reapply local finalization policy to cached adjudication without providers",
    )
    refinalize.add_argument("project", nargs="?", default=None)
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
    validate_witnesses.add_argument("project", nargs="?", default=None)
    _add_selection(validate_witnesses)
    validate_witnesses.add_argument(
        "--profile", choices=["production", "smoke"], default="production"
    )
    validate_witnesses.add_argument("--force", action="store_true")
    failed = sub.add_parser(
        "failed-chunks",
        help="List attempted chunks whose current-source latest stage failed",
    )
    failed.add_argument("project", nargs="?", default=None)
    failed.add_argument("--book", type=int, default=1)
    failed.add_argument("--profile", choices=["production", "smoke"], default="production")
    resume_failed = sub.add_parser(
        "resume-failed",
        help="Resume only the current snapshot of failed attempted chunks",
    )
    resume_failed.add_argument("project", nargs="?", default=None)
    resume_failed.add_argument("--book", type=int, default=1)
    resume_failed.add_argument("--profile", choices=["production", "smoke"], default="production")
    resume_failed.add_argument("--through", choices=STAGE_ORDER, default="finalize")
    resume_failed.add_argument("--limit", type=int)
    resume_failed.add_argument(
        "--dry-run",
        action="store_true",
        help="List the selected failed chunks without running providers",
    )

    # ── advanced / debug ──────────────────────────────────────────
    benchmark = sub.add_parser("benchmark-witness", help="Run an isolated optional/experimental witness")
    benchmark.add_argument("project", nargs="?", default=None)
    _add_selection(benchmark)
    benchmark.add_argument("--model-role", default="experimental_translategemma")
    benchmark.add_argument("--force", action="store_true")
    benchmark.add_argument("--retry-failed", action="store_true")
    inspect_cache = sub.add_parser("inspect-cache", help="Inspect independently cached stage records")
    inspect_cache.add_argument("project", nargs="?", default=None)
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
    inspect_evidence.add_argument("project", nargs="?", default=None)
    inspect_evidence.add_argument("--chunk", required=True)

    # ── audit ─────────────────────────────────────────────────────
    flags = sub.add_parser("review-flags", help="List precise human-review/unresolved flags")
    flags.add_argument("project", nargs="?", default=None)
    flags.add_argument("--book", type=int, default=1)
    export = sub.add_parser("export-audit", help="Export complete per-chunk provenance JSONL")
    export.add_argument("project", nargs="?", default=None)
    export.add_argument("--book", type=int, default=1)
    export.add_argument("--output")

    # ── compare ───────────────────────────────────────────────────
    compare = sub.add_parser("compare-v4", help="Compare explicit v4/v4.1 artifacts with new audits")
    compare.add_argument("project", nargs="?", default=None)
    compare.add_argument("--book", type=int, default=1)
    compare.add_argument("--audit")
    compare.add_argument("--qwen")
    compare.add_argument("--mistral")
    compare.add_argument("--prosecutor")
    compare.add_argument("--review")
    compare.add_argument("--output")

    # ── challenges ────────────────────────────────────────────────
    challenge = sub.add_parser("challenge", help="Run/report the blinded project challenge set")
    challenge.add_argument("project", nargs="?", default=None)
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

    # ── editorial ─────────────────────────────────────────────────
    editorial = sub.add_parser("record-editorial", help="Append a versioned editorial/review decision")
    editorial.add_argument("project", nargs="?", default=None)
    editorial.add_argument("--kind", choices=["decision", "human_review", "resolution"], required=True)
    editorial.add_argument("--source-unit", action="append", required=True)
    editorial.add_argument("--issue", required=True)
    editorial.add_argument("--decision")
    editorial.add_argument("--supersedes")
    inspect_editorial = sub.add_parser("inspect-editorial", help="Inspect append-only editorial records")
    inspect_editorial.add_argument("project", nargs="?", default=None)
    inspect_editorial.add_argument("--kind", choices=["decision", "human_review", "resolution"])

    # ── review ────────────────────────────────────────────────────
    review = sub.add_parser(
        "review", help="Open the local append-only editorial workspace"
    )
    review.add_argument("project", nargs="?", default=None)
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


def _resolve_project(args: argparse.Namespace) -> str | None:
    project = getattr(args, "project", None)
    if project:
        return project
    return None


def _load_config(args: argparse.Namespace) -> PipelineConfig:
    project = _resolve_project(args)
    config_path = Path(args.config).resolve()
    if project:
        project_cfg = config_path.parent / "projects" / project / "pipeline.yaml"
        if project_cfg.exists():
            config_path = project_cfg
    return load_config(config_path)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = _load_config(args)
    if args.command == "project":
        if args.project_command == "list":
            projects_dir = config.path_value("artifacts").parent / "projects"
            if not projects_dir.exists():
                _json({"projects": []})
                return 0
            projects = []
            for entry in sorted(projects_dir.iterdir()):
                if entry.is_dir() and (entry / "pipeline.yaml").exists():
                    projects.append({
                        "name": entry.name,
                        "path": str(entry),
                        "has_challenges": (entry / "challenges").exists(),
                        "has_editorial": (entry / "editorial").exists(),
                    })
            _json({"projects": projects})
            return 0
        if args.project_command == "show":
            project_dir = config.path_value("artifacts").parent / "projects" / (args.name or "jerome-ezekiel")
            if not project_dir.exists():
                raise SystemExit(f"Project not found: {args.name}")
            info = {"name": args.name or "jerome-ezekiel", "path": str(project_dir)}
            for filename in ("README.md", "pipeline.yaml", "project.yaml"):
                path = project_dir / filename
                if path.exists():
                    info[filename] = str(path)
            _json(info)
            return 0
    if args.command == "doctor":
        from .doctor import run_doctor
        return run_doctor(config)
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
            _json([{"index": all_chunks.index(chunk) + 1, "chunk_id": chunk["chunk_id"], "source_unit_ids": chunk["source"]["source_unit_ids"], "pages": chunk["source"]["pages"], "target_chars": len(chunk["target_latin"]), "source_chars": len(chunk.get("source_text") or chunk["target_latin"]), "context_before_chars": len(chunk["context_before"]), "context_after_chars": len(chunk["context_after"]), "annotations": len(chunk["annotations"]), "preview": (chunk.get("source_text") or chunk["target_latin"])[:180]} for chunk in chunks])
        return 0
    if args.command == "build-concordance":
        enabled = config.enabled_evidence_kinds()
        lemma_default = enabled is None or bool({"jerome_lemma", "morphology", "glossary"} & enabled)
        _json(build_concordance(config, books=args.books, include_lemmas=(not args.no_lemmas and lemma_default)))
        return 0
    if args.command == "build-retrieval-index":
        _json(build_retrieval_index(config))
        return 0
    if args.command == "search-corpus":
        pipeline = EvidenceFirstPipeline(config)
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

        all_chunks = load_chunks(config, args.book)
        chunks = _select_chunks(all_chunks, args)
        progress_descriptors = _progress_descriptors(chunks, all_chunks)
        
        def progress_handler(event: dict[str, Any]) -> None:
            _print_progress_event(event, progress_descriptors)
        
        pipeline = EvidenceFirstPipeline(
            config,
            model_profile=args.profile,
            progress_callback=progress_handler,
        )
        retry = bool(getattr(args, "retry_failed", False) or args.command == "resume")
        overall = []
        for index, chunk in enumerate(chunks, 1):
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
        all_chunks = load_chunks(config, args.book)
        chunks_by_id = {
            chunk["chunk_id"]: chunk for chunk in all_chunks
        }
        chunks = [chunks_by_id[job["chunk_id"]] for job in jobs]
        progress_descriptors = _progress_descriptors(chunks, all_chunks)
        failed_stage_by_chunk = {
            job["chunk_id"]: job["failed_stage"] for job in jobs
        }

        def progress_handler(event: dict[str, Any]) -> None:
            _print_progress_event(
                event,
                progress_descriptors,
                resume_failed_stages=failed_stage_by_chunk,
            )

        pipeline = EvidenceFirstPipeline(
            config,
            model_profile=args.profile,
            progress_callback=progress_handler,
        )
        overall = []
        for job in jobs:
            chunk = chunks_by_id[job["chunk_id"]]
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
        pipeline = EvidenceFirstPipeline(config)
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
            else EvidenceFirstPipeline(config).cache
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
        records = EvidenceFirstPipeline(config).cache.inspect(chunk_id=args.chunk)
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
        pipeline = EvidenceFirstPipeline(config)
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
            pipeline = EvidenceFirstPipeline(config)
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
