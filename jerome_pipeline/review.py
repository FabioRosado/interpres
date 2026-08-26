from __future__ import annotations

import difflib
import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from .cache import StageCache
from .config import PipelineConfig
from .editorial import EditorialRevisionStore, text_digest
from .pipeline import STAGE_ORDER


REVIEW_SCHEMA_VERSION = "jerome-review-v1"


class ReviewArtifactError(ValueError):
    pass


def _stable_id(prefix: str, *parts: Any) -> str:
    payload = json.dumps(parts, ensure_ascii=False, sort_keys=True, default=str)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}-{digest}"


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _stage_state(record: dict[str, Any] | None) -> dict[str, Any]:
    if not record:
        return {
            "available": False,
            "state": "missing",
            "error": None,
        }
    status = str(record.get("status") or "unknown")
    return {
        "available": status == "complete",
        "state": status,
        "error": record.get("error"),
    }


def _evidence_ids(value: Any) -> list[str]:
    explicit: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "evidence_ids" and isinstance(item, list):
                explicit.update(str(entry) for entry in item if entry)
            else:
                explicit.update(_evidence_ids(item))
    elif isinstance(value, list):
        for item in value:
            explicit.update(_evidence_ids(item))
    elif isinstance(value, str):
        explicit.update(re.findall(r"\bev-[A-Za-z0-9_-]+\b", value))
    return sorted(explicit)


def _source_unit_for_offset(
    source_units: list[dict[str, Any]], offset: Any
) -> list[str]:
    if not isinstance(offset, int):
        return []
    return [
        str(unit.get("source_unit_id"))
        for unit in source_units
        if isinstance(unit.get("clean_start"), int)
        and isinstance(unit.get("clean_end"), int)
        and unit["clean_start"] <= offset < unit["clean_end"]
        and unit.get("source_unit_id")
    ]


def _source_units_for_locator(
    source_units: list[dict[str, Any]], locator: Any
) -> list[str]:
    value = _dict(locator)
    start = value.get("start")
    end = value.get("end")
    if not isinstance(start, int):
        return []
    if not isinstance(end, int):
        end = start + 1
    return [
        str(unit.get("source_unit_id"))
        for unit in source_units
        if isinstance(unit.get("clean_start"), int)
        and isinstance(unit.get("clean_end"), int)
        and start < unit["clean_end"]
        and end > unit["clean_start"]
        and unit.get("source_unit_id")
    ]


def _elapsed_seconds(started: Any, finished: Any) -> float | None:
    if not isinstance(started, str) or not isinstance(finished, str):
        return None
    try:
        left = datetime.fromisoformat(started.replace("Z", "+00:00"))
        right = datetime.fromisoformat(finished.replace("Z", "+00:00"))
    except ValueError:
        return None
    return round((right - left).total_seconds(), 3)


def _text_diff(before: str, after: str) -> list[dict[str, str]]:
    before_parts = re.split(r"(\s+)", before)
    after_parts = re.split(r"(\s+)", after)
    matcher = difflib.SequenceMatcher(a=before_parts, b=after_parts, autojunk=False)
    segments: list[dict[str, str]] = []

    def append(kind: str, text: str) -> None:
        if not text:
            return
        if segments and segments[-1]["kind"] == kind:
            segments[-1]["text"] += text
        else:
            segments.append({"kind": kind, "text": text})

    for opcode, a0, a1, b0, b1 in matcher.get_opcodes():
        if opcode == "equal":
            append("equal", "".join(before_parts[a0:a1]))
        elif opcode == "delete":
            append("delete", "".join(before_parts[a0:a1]))
        elif opcode == "insert":
            append("insert", "".join(after_parts[b0:b1]))
        else:
            append("delete", "".join(before_parts[a0:a1]))
            append("insert", "".join(after_parts[b0:b1]))
    return segments


def _normalise_finding(
    finding: Any,
    *,
    prefix: str,
    index: int,
    source_units: list[dict[str, Any]],
) -> dict[str, Any]:
    item = _dict(finding)
    supplied_id = item.get("finding_id") or item.get("id")
    source_unit_ids = _list(item.get("source_unit_ids"))
    if not source_unit_ids:
        source_unit_ids = _source_units_for_locator(
            source_units, item.get("latin_locator")
        )
    return {
        "finding_id": str(supplied_id)
        if supplied_id
        else _stable_id(prefix, index, item),
        "derived_id": not bool(supplied_id),
        "source_unit_ids": source_unit_ids,
        "latin": item.get("latin") or _dict(item.get("evidence")).get("source_phrase"),
        "english": item.get("english"),
        "type": item.get("type") or item.get("check"),
        "severity": item.get("severity"),
        "status": item.get("status"),
        "message": item.get("message") or item.get("claim") or item.get("issue"),
        "reason": item.get("reason") or item.get("visible_basis"),
        "resolution": item.get("resolution"),
        "witness_target": item.get("witness_target")
        or _dict(item.get("evidence")).get("witness"),
        "confidence": item.get("confidence"),
        "evidence_ids": _evidence_ids(item),
        "requires_external_evidence": item.get("requires_external_evidence"),
        "raw": item,
    }


def _normalise_witness(
    label: str,
    record: dict[str, Any] | None,
    validation_record: dict[str, Any] | None = None,
) -> dict[str, Any]:
    state = _stage_state(record)
    output = _dict((record or {}).get("output"))
    model = _dict((record or {}).get("model"))
    uncertainties = output.get("uncertainties")
    if uncertainties is None:
        uncertainties = output.get("uncertainty")
    validation = _dict(_dict(validation_record).get("output"))
    return {
        "witness_id": label,
        "label": f"Witness {label.upper()}",
        **state,
        "provider": model.get("provider"),
        "model": model.get("model"),
        "translation": output.get("translation") if state["available"] else None,
        "source_mappings": _list(output.get("source_mappings")),
        "uncertainty": _list(uncertainties),
        "uncertainty_recorded": uncertainties is not None,
        "validation": validation,
        "validation_recorded": bool(validation),
        "eligible_as_adjudicator_base": validation.get(
            "eligible_as_adjudicator_base"
        ),
    }


def _quote_range_exists(text: Any, start_quote: Any, end_quote: Any) -> bool:
    if not isinstance(text, str) or not isinstance(start_quote, str):
        return False
    start = text.find(start_quote)
    if start < 0:
        return False
    if not isinstance(end_quote, str) or not end_quote:
        return True
    return text.find(end_quote, start) >= 0


def _mapping_with_offsets(
    text: Any, mapping: dict[str, Any], cursor: int = 0, *, is_last: bool = False
) -> tuple[dict[str, Any] | None, int]:
    if not isinstance(text, str):
        return None, cursor
    end_quote = mapping.get("english_end_quote")
    start_quote = mapping.get("english_start_quote")
    if not isinstance(end_quote, str) or not end_quote:
        return None, cursor
    start = cursor
    if isinstance(start_quote, str) and start_quote:
        start = text.find(start_quote, cursor)
    end_marker = (
        len(text) - len(end_quote)
        if is_last and text.endswith(end_quote)
        else text.find(end_quote, max(cursor, start))
    )
    if start < cursor or end_marker < start:
        return None, cursor
    end = end_marker + len(end_quote)
    return {
        **mapping,
        "english_start_offset": start,
        "english_end_offset": end,
        "english_start_quote": (
            start_quote
            if isinstance(start_quote, str) and start_quote
            else text[start:min(end, start + 80)]
        ),
    }, end


def _mappings_with_offsets(text: Any, mappings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    cursor = 0
    for index, mapping in enumerate(mappings):
        enriched_mapping, next_cursor = _mapping_with_offsets(
            text, mapping, cursor, is_last=index == len(mappings) - 1
        )
        if enriched_mapping is None:
            return []
        enriched.append(enriched_mapping)
        cursor = next_cursor
    return enriched


def _final_source_mappings(
    final_output: dict[str, Any],
    final_draft: Any,
    base_witness: Any,
    witness_a: dict[str, Any],
    witness_b: dict[str, Any],
) -> list[dict[str, Any]]:
    explicit = [
        _dict(mapping)
        for mapping in _list(final_output.get("source_mappings"))
        if _dict(mapping).get("source_unit_id")
    ]
    if explicit:
        return _mappings_with_offsets(final_draft, explicit) or explicit
    if base_witness not in {"a", "b"}:
        return []
    witness = witness_a if base_witness == "a" else witness_b
    carried: list[dict[str, Any]] = []
    witness_mappings = [
        _dict(raw)
        for raw in _list(witness.get("source_mappings"))
        if _dict(raw).get("source_unit_id")
    ]
    for mapping in _mappings_with_offsets(final_draft, witness_mappings):
        source_unit_id = mapping.get("source_unit_id")
        if not source_unit_id:
            continue
        carried.append(
            {
                **mapping,
                "mapping_source": f"base_witness_{base_witness}",
                "mapping_confidence": "carried_forward_exact_boundary_quotes",
            }
        )
    return carried


def _normalise_prosecutor_stage(
    stage: str,
    record: dict[str, Any] | None,
    source_units: list[dict[str, Any]],
) -> dict[str, Any]:
    state = _stage_state(record)
    output = _dict((record or {}).get("output"))
    findings = [
        _normalise_finding(
            item,
            prefix=f"{stage}-finding",
            index=index,
            source_units=source_units,
        )
        for index, item in enumerate(_list(output.get("challenges")), 1)
    ]
    requests = _list(output.get("evidence_requests"))
    return {
        "stage": stage,
        **state,
        "status": output.get("status"),
        "summary": output.get("summary"),
        "findings": findings,
        "evidence_requests": requests,
        "requested_evidence": bool(requests),
    }


def _normalise_evidence(
    records: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    states = {
        stage: _stage_state(records.get(stage))
        for stage in ("research_prosecutor", "research_adjudicator")
    }
    by_id: dict[str, dict[str, Any]] = {}
    for stage in ("research_prosecutor", "research_adjudicator"):
        output = _dict(_dict(records.get(stage)).get("output"))
        for index, raw in enumerate(_list(output.get("evidence")), 1):
            receipt = _dict(raw)
            supplied_id = receipt.get("evidence_id")
            evidence_id = str(supplied_id) if supplied_id else _stable_id(
                "evidence", stage, index, receipt
            )
            result_source_units = {
                str(result.get("source_unit_id") or _dict(result.get("provenance")).get("source_unit_id"))
                for result in _list(receipt.get("results"))
                if isinstance(result, dict)
                and (
                    result.get("source_unit_id")
                    or _dict(result.get("provenance")).get("source_unit_id")
                )
            }
            existing = by_id.get(evidence_id)
            if existing:
                if stage not in existing["stages"]:
                    existing["stages"].append(stage)
                continue
            grade = receipt.get("grade")
            by_id[evidence_id] = {
                "evidence_id": evidence_id,
                "derived_id": not bool(supplied_id),
                "stages": [stage],
                "grade": grade if grade in {"A", "B", "C", "D"} else None,
                "grade_recorded": grade in {"A", "B", "C", "D"},
                "source_type": receipt.get("evidence_class")
                or _dict(receipt.get("request")).get("kind"),
                "status": receipt.get("status"),
                "request": receipt.get("request"),
                "requested_by": receipt.get("requested_by"),
                "source_annotation_verified": receipt.get(
                    "source_annotation_verified"
                ),
                "textual_match_verified": receipt.get("textual_match_verified"),
                "source_unit_ids": sorted(result_source_units),
                "results": _list(receipt.get("results")),
                "retrieved_at": receipt.get("retrieved_at"),
                "relationship": receipt.get("relationship"),
                "raw": receipt,
            }
    return {
        "available": any(state["available"] for state in states.values()),
        "stages": states,
        "receipts": list(by_id.values()),
    }


def _normalise_run_details(
    records: dict[str, dict[str, Any]], history: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    history_counts: dict[str, int] = {}
    for record in history:
        stage = str(record.get("stage") or "unknown")
        history_counts[stage] = history_counts.get(stage, 0) + 1
    details = []
    for stage in STAGE_ORDER:
        record = records.get(stage)
        state = _stage_state(record)
        model = _dict((record or {}).get("model"))
        material = _dict((record or {}).get("cache_material"))
        inputs = _dict(material.get("inputs"))
        details.append(
            {
                "stage": stage,
                **state,
                "provider": model.get("provider"),
                "model": model.get("model"),
                "model_options": {
                    key: model.get(key)
                    for key in (
                        "temperature",
                        "context",
                        "max_output_tokens",
                        "thinking",
                        "extra",
                    )
                    if key in model
                },
                "prompt_version": (record or {}).get("prompt_version"),
                "prompt_digest": inputs.get("prompt_digest"),
                "elapsed_seconds": _elapsed_seconds(
                    (record or {}).get("started_at"),
                    (record or {}).get("finished_at"),
                ),
                "cache_status": "persisted" if record else "not_present",
                "artifact_id": (record or {}).get("cache_key"),
                "input_digest": (record or {}).get("input_digest"),
                "dependencies": _list(material.get("dependencies")),
                "provider_attempts": _list((record or {}).get("provider_attempts")),
                "input_budget": inputs.get("input_budget"),
                "raw_response": (record or {}).get("raw_response"),
                "history_records": history_counts.get(stage, 0),
            }
        )
    return details


def _issue_catalog(
    *,
    disagreements: list[dict[str, Any]],
    deterministic: list[dict[str, Any]],
    prosecutor: list[dict[str, Any]],
    adjudicator: list[dict[str, Any]],
    unresolved: list[dict[str, Any]],
    human_review: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build stable, resolvable issue records without inferring relationships."""

    groups = (
        ("witness_disagreement", disagreements, "finding_id"),
        ("deterministic", deterministic, "finding_id"),
        ("prosecutor", prosecutor, "finding_id"),
        ("adjudicator", adjudicator, "finding_id"),
        ("unresolved", unresolved, "issue_id"),
        ("human_review", human_review, "request_id"),
    )
    catalog: list[dict[str, Any]] = []
    for origin, items, identifier_key in groups:
        for item in items:
            source_id = str(item.get(identifier_key) or _stable_id(origin, item))
            latin = str(item.get("latin") or "").strip() or None
            message = (
                item.get("message")
                or item.get("issue")
                or item.get("missing_evidence")
                or item.get("reason")
                or item.get("resolution")
                or item.get("type")
            )
            catalog.append(
                {
                    "issue_id": f"{origin}:{source_id}",
                    "source_record_id": source_id,
                    "origin": origin,
                    "type": item.get("type"),
                    "severity": item.get("severity"),
                    "status": item.get("status"),
                    "message": message,
                    "latin": latin,
                    "english": item.get("english")
                    or item.get("witness_target"),
                    "source_unit_ids": item.get("source_unit_ids", []),
                    "evidence_ids": item.get("evidence_ids", []),
                    "reusable_eligible": bool(latin),
                }
            )
    return catalog


def build_review_view(
    audit: dict[str, Any],
    *,
    navigation: dict[str, Any] | None = None,
    artifact_errors: Iterable[dict[str, Any]] = (),
) -> dict[str, Any]:
    """Normalize one immutable audit into the stable reviewer UI contract."""

    if not isinstance(audit, dict):
        raise ReviewArtifactError("Audit must be a JSON object")
    chunk_id = audit.get("chunk_id")
    if not isinstance(chunk_id, str) or not chunk_id:
        raise ReviewArtifactError("Audit is missing a stable chunk_id")
    target_latin = audit.get("target_latin")
    if not isinstance(target_latin, str):
        raise ReviewArtifactError(f"Chunk {chunk_id} target_latin is not text")
    source = _dict(audit.get("source"))
    source_units = [item for item in _list(audit.get("source_units")) if isinstance(item, dict)]
    records = {
        str(key): value
        for key, value in _dict(audit.get("stages")).items()
        if isinstance(value, dict)
    }
    history = [item for item in _list(audit.get("stage_history")) if isinstance(item, dict)]

    witness_a = _normalise_witness(
        "a", records.get("witness_a"), records.get("witness_a_validation")
    )
    witness_b = _normalise_witness(
        "b", records.get("witness_b"), records.get("witness_b_validation")
    )

    explicit_disagreements = audit.get("disagreements")
    if explicit_disagreements is None:
        explicit_disagreements = _dict(
            _dict(records.get("deterministic_checks")).get("output")
        ).get("disagreements")
    disagreement_recorded = isinstance(explicit_disagreements, list)
    disagreements = [
        _normalise_finding(
            item,
            prefix="disagreement",
            index=index,
            source_units=source_units,
        )
        for index, item in enumerate(_list(explicit_disagreements), 1)
    ]

    morphology_record = records.get("morphology")
    morphology_state = _stage_state(morphology_record)
    morphology_output = _dict(_dict(morphology_record).get("output"))
    morphology_flags = []
    for index, raw in enumerate(_list(morphology_output.get("flags")), 1):
        flag = _dict(raw)
        morphology_flags.append(
            {
                "flag_id": _stable_id("morphology-flag", index, flag),
                "derived_id": True,
                "source_unit_ids": _source_unit_for_offset(
                    source_units, flag.get("offset")
                ),
                **flag,
            }
        )
    morphology_entries = []
    for index, raw in enumerate(_list(morphology_output.get("morphology")), 1):
        entry = _dict(raw)
        morphology_entries.append(
            {
                "entry_id": _stable_id("morphology", index, entry),
                "derived_id": True,
                "source_unit_ids": _source_unit_for_offset(
                    source_units, entry.get("offset")
                ),
                **entry,
            }
        )

    structural_record = records.get("structural_parse")
    structural_state = _stage_state(structural_record)
    structural_output = _dict(_dict(structural_record).get("output"))

    checks_record = records.get("deterministic_checks")
    checks_state = _stage_state(checks_record)
    checks_output = _dict(_dict(checks_record).get("output"))
    deterministic_findings = [
        _normalise_finding(
            item,
            prefix="deterministic",
            index=index,
            source_units=source_units,
        )
        for index, item in enumerate(_list(checks_output.get("findings")), 1)
    ]
    substantive_deterministic = [
        item for item in deterministic_findings if item.get("status") != "pass"
    ]

    prosecutor_initial = _normalise_prosecutor_stage(
        "prosecutor_initial", records.get("prosecutor_initial"), source_units
    )
    prosecutor_grounded = _normalise_prosecutor_stage(
        "prosecutor_grounded", records.get("prosecutor_grounded"), source_units
    )
    evidence = _normalise_evidence(records)

    adjudicator_record = records.get("adjudicator") or records.get(
        "adjudicator_initial"
    )
    adjudicator_state = _stage_state(adjudicator_record)
    adjudicator_output = _dict(_dict(adjudicator_record).get("output"))
    final_record = records.get("finalize")
    final_state = _stage_state(final_record)
    final_output = _dict(_dict(final_record).get("output"))
    decision = _dict(final_output.get("decision")) or adjudicator_output
    coverage = _dict(decision.get("coverage"))
    applied_edits = []
    for index, raw in enumerate(_list(coverage.get("applied_edits")), 1):
        edit = _dict(raw)
        supplied_id = edit.get("edit_id") or edit.get("id")
        applied_edits.append(
            {
                "edit_id": str(supplied_id)
                if supplied_id
                else _stable_id("edit", chunk_id, index, edit),
                "derived_id": not bool(supplied_id),
                "source_unit_ids": _list(edit.get("source_unit_ids")),
                "mapping_available": bool(edit.get("source_unit_ids")),
                "old": edit.get("old"),
                "new": edit.get("new"),
                "reason": edit.get("reason"),
                "evidence_ids": _evidence_ids(edit),
                "applied": True,
                "ambiguous": False,
                "verification": "exact_unique_match_applied",
                "start_before": edit.get("start_before"),
                "end_before": edit.get("end_before"),
            }
        )
    adjudicator_findings = [
        _normalise_finding(
            item,
            prefix="adjudicator-finding",
            index=index,
            source_units=source_units,
        )
        for index, item in enumerate(_list(decision.get("findings")), 1)
    ]

    unresolved = []
    for index, raw in enumerate(_list(decision.get("unresolved_issues")), 1):
        item = _dict(raw)
        unresolved.append(
            {
                "issue_id": _stable_id("unresolved", chunk_id, index, item),
                "derived_id": True,
                "source_unit_ids": _source_units_for_locator(
                    source_units, item.get("latin_locator")
                ),
                **item,
            }
        )
    human_review = []
    for index, raw in enumerate(_list(decision.get("human_review_requests")), 1):
        item = _dict(raw)
        human_review.append(
            {
                "request_id": _stable_id("human-review", chunk_id, index, item),
                "derived_id": True,
                "source_unit_ids": _source_units_for_locator(
                    source_units, item.get("latin_locator")
                ),
                **item,
            }
        )

    final_draft = final_output.get("final_draft") or audit.get("final_draft")
    final_status = final_output.get("final_status") or audit.get("final_status")
    if final_status not in {
        "accepted",
        "corrected",
        "unresolved",
        "human_review",
    }:
        final_status = "incomplete"
    if not final_state["available"]:
        final_status = "incomplete"
    final_checks = _dict(final_output.get("final_checks"))
    if not final_checks:
        final_checks = _dict(_dict(final_output.get("decision")).get("final_checks"))

    base_witness = coverage.get("base_witness")
    base_text = (
        witness_a.get("translation")
        if base_witness == "a"
        else witness_b.get("translation") if base_witness == "b" else None
    )
    diff = (
        _text_diff(str(base_text), str(final_draft))
        if isinstance(base_text, str) and isinstance(final_draft, str)
        else []
    )
    final_source_mappings = _final_source_mappings(
        final_output, final_draft, base_witness, witness_a, witness_b
    )

    adjudicator_failure = _dict(_dict(adjudicator_record).get("error"))
    ambiguous_edit_failure = (
        adjudicator_failure
        if "exactly once" in str(adjudicator_failure.get("message", ""))
        or "ambiguous" in str(adjudicator_failure.get("message", "")).casefold()
        else None
    )
    incomplete_stages = [
        {
            "stage": stage,
            **_stage_state(records.get(stage)),
        }
        for stage in STAGE_ORDER
        if _stage_state(records.get(stage))["state"] != "complete"
    ]
    if incomplete_stages:
        final_status = "incomplete"

    page_start = source.get("pl_start")
    page_end = source.get("pl_end")
    pages = _list(source.get("pages"))
    if page_start is None and pages:
        page_start = pages[0]
    if page_end is None and pages:
        page_end = pages[-1]

    issue_count = len(unresolved) + len(human_review)
    prosecutor_count = len(
        prosecutor_grounded["findings"]
        if prosecutor_grounded["available"]
        else prosecutor_initial["findings"]
    )
    counts = {
        "witness_disagreements": len(disagreements)
        if disagreement_recorded
        else None,
        "deterministic_findings": len(substantive_deterministic),
        "prosecutor_findings": prosecutor_count,
        "adjudicator_edits": len(applied_edits),
        "unresolved_human_review": issue_count,
    }
    active_prosecutor = (
        prosecutor_grounded["findings"]
        if prosecutor_grounded["available"]
        else prosecutor_initial["findings"]
    )
    issue_catalog = _issue_catalog(
        disagreements=disagreements,
        deterministic=substantive_deterministic,
        prosecutor=active_prosecutor,
        adjudicator=adjudicator_findings,
        unresolved=unresolved,
        human_review=human_review,
    )
    machine_final = final_draft if final_state["available"] else None
    machine = {
        "immutable": True,
        "final_status": final_status,
        "final_draft": machine_final,
        "final_draft_digest": text_digest(machine_final),
        "pipeline_version": audit.get("pipeline_version"),
        "prompt_version": audit.get("prompt_version"),
        "schema_version": audit.get("schema_version"),
        "execution_profile": audit.get("execution_profile"),
        "source_fingerprint": audit.get("source_fingerprint"),
        "final_artifact_id": _dict(final_record).get("cache_key"),
    }
    expected_unit_ids = [str(unit.get("source_unit_id")) for unit in source_units if unit.get("source_unit_id")]
    witness_mapped_units = sorted(
        {
            str(_dict(mapping).get("source_unit_id"))
            for witness in (witness_a, witness_b)
            for mapping in _list(witness.get("source_mappings"))
            if _dict(mapping).get("source_unit_id")
        }
    )
    final_mapped_units = sorted(
        {
            str(_dict(mapping).get("source_unit_id"))
            for mapping in final_source_mappings
            if _dict(mapping).get("source_unit_id")
        }
    )
    review_links = {
        "persisted": {
            "source_unit_ids": expected_unit_ids,
            "finding_source_unit_ids": sorted(
                {
                    unit_id
                    for item in issue_catalog
                    for unit_id in _list(item.get("source_unit_ids"))
                }
            ),
            "finding_ids": sorted(
                str(item.get("source_record_id"))
                for item in issue_catalog
                if item.get("source_record_id")
            ),
            "evidence_ids": sorted(
                {
                    evidence_id
                    for item in issue_catalog
                    for evidence_id in _list(item.get("evidence_ids"))
                }
            ),
            "edit_ids": sorted(edit["edit_id"] for edit in applied_edits),
            "witness_mapped_source_unit_ids": witness_mapped_units,
            "final_mapped_source_unit_ids": final_mapped_units,
        },
        "unavailable": {
            "final_source_mappings": not bool(final_mapped_units),
            "witness_source_mappings": not bool(witness_mapped_units),
            "prosecutor_initial_grounded_equivalence": True,
            "arbitrary_latin_to_english_alignment": True,
        },
        "note": "The reviewer UI highlights only these persisted relationships; absent alignments are shown as missing rather than inferred.",
    }

    return {
        "review_schema_version": REVIEW_SCHEMA_VERSION,
        "chunk": {
            "book": source.get("book") or audit.get("book") or (
                source_units[0].get("book") if source_units else None
            ),
            "chunk_id": chunk_id,
            "pl_start": page_start,
            "pl_end": page_end,
            "pages": pages,
            "source_unit_count": len(source_units),
            "final_status": final_status,
            "counts": counts,
            "navigation": navigation or {"previous": None, "next": None},
        },
        "source": {
            "state": "available",
            "target_latin": target_latin,
            "context_before": audit.get("context_before"),
            "context_after": audit.get("context_after"),
            "units": source_units,
            "spans": _list(audit.get("source_spans")),
            "page_markers": _list(audit.get("page_markers")),
            "annotations": _list(audit.get("annotations")),
        },
        "machine": machine,
        "issues": {
            "items": issue_catalog,
            "count": len(issue_catalog),
            "origins": sorted({item["origin"] for item in issue_catalog}),
            "note": "Issue records are linked to persisted findings; no cross-stage equivalence is inferred.",
        },
        "review_links": review_links,
        "witnesses": [witness_a, witness_b],
        "disagreements": {
            "available": disagreement_recorded,
            "items": disagreements,
            "note": None
            if disagreement_recorded
            else "The pipeline did not persist an explicit disagreement set; the UI does not infer one from prose similarity.",
        },
        "structural": {
            **structural_state,
            "sentences": _list(structural_output.get("sentences")),
            "intrinsic_ambiguity": _list(
                structural_output.get("intrinsic_ambiguity")
            ),
            "context_dependent": _list(
                structural_output.get("context_dependent")
            ),
            "unverified_analyses": _list(
                structural_output.get("unverified_analyses")
            ),
        },
        "morphology": {
            **morphology_state,
            "backend": morphology_output.get("backend"),
            "flags": morphology_flags,
            "entries": morphology_entries,
        },
        "deterministic": {
            **checks_state,
            "summary": checks_output.get("summary"),
            "findings": deterministic_findings,
            "substantive_findings": substantive_deterministic,
            "limits": checks_output.get("limits"),
        },
        "prosecutor": {
            "initial": prosecutor_initial,
            "grounded": prosecutor_grounded,
            "transition_mapping_recorded": False,
            "transition_note": "Initial and grounded findings have no shared persisted finding IDs, so the UI shows both stages without inferring survival or disappearance.",
        },
        "evidence": evidence,
        "adjudicator": {
            **adjudicator_state,
            "status": decision.get("status"),
            "summary": decision.get("summary"),
            "base_witness": base_witness,
            "findings": adjudicator_findings,
            "edits": applied_edits,
            "unresolved_issues": unresolved,
            "human_review_requests": human_review,
            "evidence_requests": _list(decision.get("evidence_requests")),
            "decision_basis": _list(decision.get("decision_basis")),
            "coverage": coverage,
            "edit_validation_error": ambiguous_edit_failure,
        },
        "final": {
            **final_state,
            "status": final_status,
            "translation": final_draft if final_state["available"] else None,
            "base_witness": base_witness,
            "applied_edit_count": len(applied_edits),
            "diff": diff,
            "source_mappings": final_source_mappings,
            "mapping_available": bool(final_source_mappings),
        },
        "verification": {
            **final_state,
            "coverage_assertion": coverage.get("all_clauses_accounted_for"),
            "source_units_total": len(source_units),
            "source_units_accounted_for": coverage.get(
                "source_units_accounted_for"
            ),
            "missing_source_unit_ids": coverage.get("missing_source_unit_ids"),
            "exact_edit_validation": (
                "failed_ambiguous"
                if ambiguous_edit_failure
                else "passed"
                if adjudicator_state["available"]
                else "unavailable"
            ),
            "schema_status_validation": (
                "passed" if final_state["available"] else "unavailable"
            ),
            "final_checks": final_checks,
            "incomplete_stages": incomplete_stages,
        },
        "run_details": _normalise_run_details(records, history),
        "artifact_errors": list(artifact_errors),
        "filters": {
            "all": True,
            "disagreements": bool(disagreements),
            "deterministic": bool(substantive_deterministic),
            "prosecutor": prosecutor_count > 0,
            "evidence": bool(evidence["receipts"]),
            "edited": bool(applied_edits),
            "unresolved": bool(unresolved),
            "human_review": bool(human_review),
            "failed_incomplete": bool(incomplete_stages),
        },
    }


@dataclass
class ReviewRepository:
    """Immutable machine-artifact reader plus append-only editorial revisions."""

    config: PipelineConfig
    book: int = 1
    profile: str = "production"
    revision_store: EditorialRevisionStore = field(init=False)

    def __post_init__(self) -> None:
        self.revision_store = EditorialRevisionStore(
            self.config.path_value("editorial_reviews")
        )

    @property
    def chunks_path(self) -> Path:
        return self.config.path_value("artifacts") / f"book{self.book:02d}" / "chunks.jsonl"

    def _read_chunks(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        path = self.chunks_path
        if not path.exists():
            return [], [
                {
                    "artifact_kind": "chunks",
                    "path": str(path),
                    "message": "Chunk artifact is missing; run preprocessing first.",
                }
            ]
        chunks: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        with path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                try:
                    value = json.loads(line)
                    if not isinstance(value, dict):
                        raise TypeError("record is not an object")
                    if not isinstance(value.get("chunk_id"), str):
                        raise ValueError("record has no chunk_id")
                    chunks.append(value)
                except Exception as exc:
                    errors.append(
                        {
                            "artifact_kind": "chunks",
                            "path": str(path),
                            "line": line_number,
                            "message": str(exc),
                        }
                    )
        return chunks, errors

    def _records_by_chunk(
        self,
    ) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
        cache = StageCache(self.config.path_value("cache"))
        records = cache.inspect(include_attempts=True)
        by_chunk: dict[str, list[dict[str, Any]]] = {}
        errors: list[dict[str, Any]] = []
        for record in records:
            if record.get("status") == "cache_read_error":
                errors.append(
                    {
                        "artifact_kind": "stage_cache",
                        "stage": record.get("stage"),
                        "path": record.get("path"),
                        "message": record.get("error"),
                    }
                )
                continue
            chunk_id = record.get("chunk_id")
            if isinstance(chunk_id, str):
                by_chunk.setdefault(chunk_id, []).append(record)
        return by_chunk, errors

    def _audit(
        self,
        chunk: dict[str, Any],
        records: list[dict[str, Any]],
    ) -> dict[str, Any]:
        source_fingerprint = chunk.get("source_fingerprint")

        def belongs_to_current_source(record: dict[str, Any]) -> bool:
            record_fingerprint = _dict(record.get("cache_material")).get(
                "source_fingerprint"
            )
            # Pre-fingerprint fixture/legacy records remain readable. Modern
            # content-addressed records must match the currently preprocessed
            # Latin so the reviewer cannot pair stale decisions with new text.
            return not (
                source_fingerprint
                and record_fingerprint
                and record_fingerprint != source_fingerprint
            )

        selected = [
            record
            for record in records
            if belongs_to_current_source(record)
            and (
                record.get("execution_profile", "production") == self.profile
                or (
                    self.profile == "smoke"
                    and record.get("stage") == "morphology"
                    and not record.get("model")
                )
            )
        ]
        latest: dict[str, dict[str, Any]] = {}
        for record in selected:
            stage = record.get("stage")
            if not isinstance(stage, str):
                continue
            if stage not in latest or str(record.get("finished_at", "")) > str(
                latest[stage].get("finished_at", "")
            ):
                latest[stage] = record
        final = _dict(_dict(latest.get("finalize")).get("output"))
        return {
            "schema_version": self.config.schema_version,
            "pipeline_version": self.config.pipeline_version,
            "prompt_version": self.config.prompt_version,
            "execution_profile": self.profile,
            "chunk_id": chunk["chunk_id"],
            "source_fingerprint": chunk.get("source_fingerprint"),
            "book": chunk.get("book"),
            "source": chunk.get("source", {}),
            "source_units": chunk.get("source_units", []),
            "page_markers": chunk.get("page_markers", []),
            "target_latin": chunk.get("target_latin"),
            "context_before": chunk.get("context_before"),
            "context_after": chunk.get("context_after"),
            "source_spans": chunk.get("source_spans", []),
            "annotations": chunk.get("annotations", []),
            "stages": latest,
            "stage_history": sorted(
                selected,
                key=lambda item: (
                    str(item.get("finished_at", "")),
                    str(item.get("stage", "")),
                    str(item.get("cache_key", "")),
                ),
            ),
            "final_draft": final.get("final_draft"),
            "final_status": final.get("final_status", "incomplete"),
            "human_review_requests": final.get("human_review_requests", []),
            "unresolved_issues": final.get("unresolved_issues", []),
        }

    def list_chunks(self) -> dict[str, Any]:
        chunks, chunk_errors = self._read_chunks()
        records_by_chunk, cache_errors = self._records_by_chunk()
        errors = chunk_errors + cache_errors
        items = []
        for index, chunk in enumerate(chunks):
            previous_id = chunks[index - 1]["chunk_id"] if index else None
            next_id = chunks[index + 1]["chunk_id"] if index + 1 < len(chunks) else None
            try:
                view = build_review_view(
                    self._audit(chunk, records_by_chunk.get(chunk["chunk_id"], [])),
                    navigation={"previous": previous_id, "next": next_id},
                    artifact_errors=errors,
                )
                summary = dict(view["chunk"])
                editorial = self.revision_store.state(
                    int(summary.get("book") or self.book),
                    str(summary["chunk_id"]),
                    machine_final_digest=view["machine"]["final_draft_digest"],
                )
                latest = editorial.get("latest") or {}
                summary["editorial"] = {
                    "revision_count": editorial["revision_count"],
                    "state": _dict(latest.get("editorial")).get("state"),
                    "based_on_current_machine_final": editorial[
                        "based_on_current_machine_final"
                    ],
                }
                items.append(summary)
            except ReviewArtifactError as exc:
                items.append(
                    {
                        "book": self.book,
                        "chunk_id": chunk.get("chunk_id"),
                        "final_status": "incomplete",
                        "counts": {},
                        "artifact_error": str(exc),
                    }
                )
        return {
            "review_schema_version": REVIEW_SCHEMA_VERSION,
            "book": self.book,
            "profile": self.profile,
            "chunks": items,
            "artifact_errors": errors,
        }

    def get_chunk(self, chunk_id: str) -> dict[str, Any] | None:
        chunks, chunk_errors = self._read_chunks()
        index = next(
            (position for position, item in enumerate(chunks) if item["chunk_id"] == chunk_id),
            None,
        )
        if index is None:
            return None
        records_by_chunk, cache_errors = self._records_by_chunk()
        previous_id = chunks[index - 1]["chunk_id"] if index else None
        next_id = chunks[index + 1]["chunk_id"] if index + 1 < len(chunks) else None
        view = build_review_view(
            self._audit(chunks[index], records_by_chunk.get(chunk_id, [])),
            navigation={"previous": previous_id, "next": next_id},
            artifact_errors=chunk_errors + cache_errors,
        )
        view["editorial"] = self.revision_store.state(
            int(view["chunk"].get("book") or self.book),
            chunk_id,
            machine_final_digest=view["machine"]["final_draft_digest"],
        )
        return view

    def save_editorial_revision(
        self, chunk_id: str, payload: dict[str, Any]
    ) -> dict[str, Any] | None:
        view = self.get_chunk(chunk_id)
        if view is None:
            return None
        revision = self.revision_store.save(
            book=int(view["chunk"].get("book") or self.book),
            chunk_id=chunk_id,
            payload=payload,
            machine=view["machine"],
            issues=view["issues"]["items"],
        )
        editorial = self.revision_store.state(
            int(view["chunk"].get("book") or self.book),
            chunk_id,
            machine_final_digest=view["machine"]["final_draft_digest"],
        )
        return {
            "saved": True,
            "revision": revision,
            "editorial": editorial,
        }
