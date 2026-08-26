from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


def load_jsonl(path: Path | None) -> list[dict[str, Any]]:
    if path is None or not path.exists():
        return []
    results = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSONL {path}:{line_number}: {exc}") from exc
            if isinstance(value, dict):
                results.append(value)
    return results


def _latin(record: dict[str, Any]) -> str:
    latin = record.get("latin")
    if isinstance(latin, dict):
        return str(latin.get("text", ""))
    return str(record.get("target_latin", latin or ""))


def _normal(value: str) -> str:
    return " ".join(re.findall(r"[a-z]+", value.casefold().replace("j", "i").replace("v", "u")))


def _best_legacy_match(audit: dict[str, Any], records: list[dict[str, Any]]) -> dict[str, Any] | None:
    target = _normal(audit.get("target_latin", ""))
    if not target:
        return None
    best = None
    best_score = 0.0
    target_tokens = set(target.split())
    for record in records:
        legacy = _normal(_latin(record))
        if not legacy:
            continue
        if target in legacy or legacy in target:
            score = min(len(target), len(legacy)) / max(len(target), len(legacy)) + 1.0
        else:
            legacy_tokens = set(legacy.split())
            score = len(target_tokens & legacy_tokens) / max(1, len(target_tokens | legacy_tokens))
        if score > best_score:
            best, best_score = record, score
    return best if best_score >= 0.35 else None


def compare_legacy(
    audits: list[dict[str, Any]],
    *,
    qwen_path: Path | None,
    mistral_path: Path | None,
    prosecutor_path: Path | None,
    review_path: Path | None,
) -> list[dict[str, Any]]:
    qwen, mistral = load_jsonl(qwen_path), load_jsonl(mistral_path)
    prosecutors, reviews = load_jsonl(prosecutor_path), load_jsonl(review_path)
    report = []
    for audit in audits:
        q = _best_legacy_match(audit, qwen)
        m = _best_legacy_match(audit, mistral)
        old_review = _best_legacy_match(audit, reviews)
        old_prosecutor = _best_legacy_match(audit, prosecutors)
        stages = audit.get("stages", {})
        adjudication = stages.get("adjudicator", {}).get("output")
        adjudication_initial = stages.get("adjudicator_initial", {}).get(
            "output"
        )
        prosecutor_requests = (
            stages.get("prosecutor_initial", {})
            .get("output", {})
            .get("evidence_requests", [])
        )
        adjudicator_requests = (adjudication_initial or {}).get(
            "evidence_requests", []
        )
        prosecutor_evidence = (
            stages.get("research_prosecutor", {})
            .get("output", {})
            .get("evidence", [])
        )
        adjudicator_evidence = (
            stages.get("research_adjudicator", {})
            .get("output", {})
            .get("evidence", [])
        )
        final = stages.get("finalize", {}).get("output", {})
        legacy_decision = (old_review or {}).get("adjudication", {})
        old_status = legacy_decision.get("review_status")
        new_status = final.get("final_status", audit.get("final_status"))
        human_flags = final.get("human_review_requests", audit.get("human_review_requests", []))
        report.append(
            {
                "chunk_id": audit["chunk_id"],
                "legacy_match_ids": {
                    "qwen": q and q.get("id"),
                    "mistral": m and m.get("id"),
                    "prosecutor": old_prosecutor and old_prosecutor.get("id"),
                    "review": old_review and old_review.get("id"),
                },
                "v4_witnesses": {
                    "qwen": (q or {}).get("witness"),
                    "mistral": (m or {}).get("witness"),
                },
                "v4_prosecutor": (old_prosecutor or {}).get("prosecutor"),
                "v4_adjudication": legacy_decision or None,
                "new_structural_parse": stages.get("structural_parse", {}).get("output"),
                "new_prosecutor_initial": stages.get("prosecutor_initial", {}).get("output"),
                "new_prosecutor": stages.get("prosecutor_grounded", {}).get("output"),
                "new_evidence_requests": {
                    "prosecutor": prosecutor_requests,
                    "adjudicator": adjudicator_requests,
                },
                "new_retrieved_evidence": {
                    "prosecutor": prosecutor_evidence,
                    "adjudicator": adjudicator_evidence,
                },
                "new_adjudication_initial": adjudication_initial,
                "new_adjudication": adjudication,
                "status_change": {"old": old_status, "new": new_status, "changed": old_status is not None and old_status != new_status},
                "new_human_review_flags": human_flags,
                "comparison_available": any((q, m, old_prosecutor, old_review)),
            }
        )
    return report
