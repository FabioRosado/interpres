from __future__ import annotations

from typing import Any


SUPPORTING_EVIDENCE_CLASSES = {"verified_evidence", "retrieved_evidence"}


def _receipt_supports_positive_claim(receipt: dict[str, Any] | None) -> bool:
    """Return whether a receipt can positively support an adjudicator claim.

    Absence and failure receipts remain useful audit evidence, but they cannot
    prove a positive Grade-A/B claim. External research leads likewise remain
    leads until separately verified.
    """

    return bool(
        receipt
        and receipt.get("status") == "found"
        and receipt.get("evidence_class") in SUPPORTING_EVIDENCE_CLASSES
        and receipt.get("results")
    )


def assess_adjudication_evidence(
    decision: dict[str, Any], receipts: list[dict[str, Any]]
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
    valid_strong_basis = False

    def inspect_ids(
        evidence_ids: Any,
        *,
        location: str,
        claim: str,
        require_receipt: bool,
    ) -> tuple[list[str], list[dict[str, Any]]]:
        ids = [str(item) for item in evidence_ids] if isinstance(evidence_ids, list) else []
        invalid = []
        for evidence_id in ids:
            receipt = receipt_index.get(evidence_id)
            if _receipt_supports_positive_claim(receipt):
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
        return ids, invalid

    for index, item in enumerate(decision.get("decision_basis", [])):
        if not isinstance(item, dict) or item.get("grade") not in {"A", "B"}:
            continue
        grade = str(item.get("grade"))
        ids, invalid = inspect_ids(
            item.get("evidence_ids"),
            location=f"decision_basis[{index}]",
            claim=str(item.get("claim") or ""),
            require_receipt=grade == "B",
        )
        # A source-visible Grade-A statement without IDs is permitted as the
        # architecture's deterministic/source-verifiable evidence class.
        if not invalid and (grade == "A" or ids):
            valid_strong_basis = True

    finding_support: dict[int, bool] = {}
    for index, item in enumerate(decision.get("findings", [])):
        if not isinstance(item, dict):
            continue
        ids = item.get("evidence_ids")
        _, invalid = inspect_ids(
            ids,
            location=f"findings[{index}]",
            claim=str(item.get("resolution") or item.get("reason") or ""),
            require_receipt=False,
        )
        finding_support[index] = bool(ids) and not invalid

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
        "finding_support": finding_support,
        "issues": issues,
    }
