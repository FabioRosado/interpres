from __future__ import annotations

import re
from typing import Any

SUPPORTING_EVIDENCE_CLASSES = {"verified_evidence", "retrieved_evidence"}
SUPPORTING_EVIDENCE_KINDS = {
    "jerome_phrase",
    "jerome_lemma",
    "scripture",
    "glossary",
    "morphology",
    "semantic_rag",
    "corpus_related",
    "source_edition",
    "chronology",
    "proper_name",
}


def _receipt_supports_positive_claim(receipt: dict[str, Any] | None) -> bool:
    """Return whether a receipt can positively support an adjudicator claim.

    Absence and failure receipts remain useful audit evidence, but they cannot
    prove a positive Grade-A/B claim. External research leads likewise remain
    leads until separately verified.
    """

    request = receipt.get("request") if isinstance(receipt, dict) else None
    return bool(
        receipt
        and isinstance(request, dict)
        and request.get("kind") in SUPPORTING_EVIDENCE_KINDS
        and receipt.get("status") == "found"
        and receipt.get("evidence_class") in SUPPORTING_EVIDENCE_CLASSES
        and receipt.get("results")
    )


def _terms(value: Any) -> set[str]:
    stop = {
        "the", "and", "for", "that", "this", "with", "from", "into",
        "use", "reading", "supports", "correct", "correction", "witness",
    }
    return {
        word.casefold()
        for word in re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿ]+", str(value or ""))
        if len(word) >= 3 and word.casefold() not in stop
    }


def _receipt_relevance(receipt: dict[str, Any], claim: str) -> dict[str, Any]:
    request = receipt.get("request") if isinstance(receipt.get("request"), dict) else {}
    request_text = " ".join(
        str(request.get(key) or "") for key in ("query", "reason")
    )
    overlap = sorted(_terms(request_text) & _terms(claim))
    query = str(request.get("query") or "").strip().casefold()
    folded_claim = claim.casefold()
    relevant = bool(overlap or (query and query in folded_claim))
    return {
        "relevant": relevant,
        "overlap_terms": overlap,
        "request_query": request.get("query"),
    }


def _deterministic_support(
    claim: str, deterministic_findings: list[dict[str, Any]], evidence_ids: list[str] | None = None
) -> list[str]:
    """Return deterministic finding IDs that explicitly support a claim.

    Grade A claims must cite deterministic finding IDs in evidence_ids.
    Keyword overlap is NOT sufficient - explicit provenance required.
    """
    evidence_ids = [str(e) for e in evidence_ids] if evidence_ids else []
    supported: list[str] = []
    for item in deterministic_findings:
        if not isinstance(item, dict) or item.get("status") == "pass":
            continue
        # Deterministic findings are identified by check name or finding_id
        finding_id = str(item.get("finding_id") or item.get("check") or "")
        if finding_id and finding_id in evidence_ids:
            supported.append(finding_id)
    return sorted(set(supported))


def assess_adjudication_evidence(
    decision: dict[str, Any],
    receipts: list[dict[str, Any]],
    *,
    deterministic_findings: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Audit positive adjudicator evidence claims against actual receipts.

    Grade A may refer directly to visible deterministic/source material and
    therefore need not carry a receipt ID. Grade B is retrieved evidence by
    definition and must cite at least one supporting receipt. Any Grade-A/B
    receipt IDs that are present must resolve to positive, non-lead receipts.
    Finding and applied-edit receipt IDs are also treated as positive support.
    """

    receipt_index = {
        str(item.get("evidence_id")): item
        for item in receipts
        if isinstance(item, dict) and item.get("evidence_id")
    }
    issues: list[dict[str, Any]] = []
    deterministic_findings = deterministic_findings or []
    valid_strong_basis = False
    basis_support: dict[int, dict[str, Any]] = {}

    def inspect_ids(
        evidence_ids: Any,
        *,
        location: str,
        claim: str,
        require_receipt: bool,
    ) -> tuple[list[str], list[dict[str, Any]], list[dict[str, Any]]]:
        ids = [str(item) for item in evidence_ids] if isinstance(evidence_ids, list) else []
        invalid = []
        relationships = []
        for evidence_id in ids:
            receipt = receipt_index.get(evidence_id)
            if _receipt_supports_positive_claim(receipt):
                relevance = _receipt_relevance(receipt, claim)
                relationships.append(
                    {"evidence_id": evidence_id, **relevance}
                )
                if relevance["relevant"]:
                    continue
                invalid.append(
                    {
                        "evidence_id": evidence_id,
                        "status": "irrelevant_to_claim",
                        "evidence_class": receipt.get("evidence_class"),
                    }
                )
                continue
            invalid.append(
                {
                    "evidence_id": evidence_id,
                    "status": receipt.get("status") if receipt else "unknown_evidence_id",
                    "evidence_class": receipt.get("evidence_class") if receipt else "none",
                }
            )
        if require_receipt and not ids:
            invalid.append(
                {
                    "evidence_id": None,
                    "status": "missing_evidence_id",
                    "evidence_class": "none",
                }
            )
        if invalid:
            issues.append(
                {
                    "location": location,
                    "claim": claim,
                    "evidence_ids": ids,
                    "invalid_receipts": invalid,
                }
            )
        return ids, invalid, relationships

    for index, item in enumerate(decision.get("decision_basis", [])):
        if not isinstance(item, dict) or item.get("grade") not in {"A", "B"}:
            continue
        grade = str(item.get("grade"))
        ids, invalid, relationships = inspect_ids(
            item.get("evidence_ids"),
            location=f"decision_basis[{index}]",
            claim=str(item.get("claim") or ""),
            require_receipt=grade == "B",
        )
        deterministic_ids = _deterministic_support(
            str(item.get("claim") or ""), deterministic_findings, item.get("evidence_ids")
        ) if grade == "A" else []
        supported = bool(deterministic_ids) if grade == "A" else bool(ids) and not invalid
        basis_support[index] = {
            "grade": grade,
            "supported": supported,
            "deterministic_finding_ids": deterministic_ids,
            "receipt_relationships": relationships,
        }
        valid_strong_basis = valid_strong_basis or supported

    finding_support: dict[int, bool] = {}
    finding_support_detail: dict[int, dict[str, Any]] = {}
    for index, item in enumerate(decision.get("findings", [])):
        if not isinstance(item, dict):
            continue
        ids = item.get("evidence_ids")
        claim = " ".join(
            str(item.get(key) or "")
            for key in ("latin", "english", "resolution", "reason")
        )
        _, invalid, relationships = inspect_ids(
            ids,
            location=f"findings[{index}]",
            claim=claim,
            require_receipt=False,
        )
        deterministic_ids = _deterministic_support(claim, deterministic_findings, ids)
        receipt_supported = bool(ids) and not invalid
        finding_support[index] = receipt_supported or bool(deterministic_ids)
        finding_support_detail[index] = {
            "supported": finding_support[index],
            "receipt_supported": receipt_supported,
            "receipt_relationships": relationships,
            "deterministic_finding_ids": deterministic_ids,
        }

    applied_edits = decision.get("coverage", {}).get("applied_edits", [])
    for index, item in enumerate(applied_edits):
        if not isinstance(item, dict) or not item.get("evidence_ids"):
            continue
        inspect_ids(
            item.get("evidence_ids"),
            location=f"coverage.applied_edits[{index}]",
            claim=str(item.get("reason") or ""),
            require_receipt=False,
        )

    return {
        "policy": "positive_receipts/v1",
        "receipt_count": len(receipt_index),
        "valid_strong_basis": valid_strong_basis,
        "basis_support": basis_support,
        "finding_support": finding_support,
        "finding_support_detail": finding_support_detail,
        "issues": issues,
    }
