from __future__ import annotations

import json
import re
from typing import Any, Callable

from .source import split_sentences


class SchemaValidationError(ValueError):
    pass


PROSECUTOR_STATUSES = {
    "no_issue_found",
    "insufficient_basis_to_challenge",
    "requires_evidence",
    "grounded_challenge",
    "unresolved",
}
FINAL_STATUSES = {"accepted", "corrected", "unresolved", "human_review"}
SEVERITIES = {"low", "medium", "high"}
EVIDENCE_KINDS = (
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
    "web_research",
)


def parse_json_response(text: str) -> dict[str, Any]:
    value = text.strip()
    if value.startswith("```"):
        value = re.sub(r"^```(?:json)?\s*", "", value, flags=re.IGNORECASE)
        value = re.sub(r"\s*```$", "", value)
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        start, end = value.find("{"), value.rfind("}")
        if start < 0 or end <= start:
            raise
        parsed = json.loads(value[start : end + 1])
    if not isinstance(parsed, dict):
        raise SchemaValidationError("Structured model output must be a JSON object")
    return parsed


def _require(value: dict[str, Any], fields: set[str], name: str) -> None:
    missing = fields - set(value)
    if missing:
        raise SchemaValidationError(f"{name} missing fields: {sorted(missing)}")


def validate_structural(value: dict[str, Any]) -> dict[str, Any]:
    _require(
        value,
        {"sentences", "intrinsic_ambiguity", "context_dependent", "unverified_analyses"},
        "structural_parse",
    )
    if not isinstance(value["sentences"], list):
        raise SchemaValidationError("structural_parse.sentences must be a list")
    for index, sentence in enumerate(value["sentences"]):
        if not isinstance(sentence, dict):
            raise SchemaValidationError(f"structural sentence {index} must be an object")
        _require(
            sentence,
            {
                "latin",
                "main_verbs",
                "subject",
                "objects",
                "subordinate_clauses",
                "attachments",
                "referents",
                "idioms",
                "alternatives",
            },
            f"structural sentence {index}",
        )
        for field in (
            "main_verbs",
            "objects",
            "subordinate_clauses",
            "attachments",
            "referents",
            "idioms",
            "alternatives",
        ):
            if not isinstance(sentence[field], list):
                raise SchemaValidationError(
                    f"structural sentence {index}.{field} must be a list"
                )
    for field in ("intrinsic_ambiguity", "context_dependent", "unverified_analyses"):
        if not isinstance(value[field], list):
            raise SchemaValidationError(f"structural_parse.{field} must be a list")
    return value


def structural_wire_schema(target_latin: str) -> dict[str, Any]:
    """Compact provider schema for blind structural analysis.

    The canonical audit structure deliberately remains descriptive.  The
    model-facing representation does not repeat the Latin or verbose evidence
    labels, because four observed live responses exhausted their output
    ceilings while serializing that redundant material.
    """
    sentence_count = len(split_sentences(target_latin))
    if sentence_count < 1:
        raise SchemaValidationError("Target Latin has no structural sentences")

    short_string = {"type": "string", "maxLength": 120}
    phrase_string = {"type": "string", "maxLength": 220}

    def object_schema(
        properties: dict[str, Any], required: list[str]
    ) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": False,
        }

    string_array = {
        "type": "array",
        "items": short_string,
        "maxItems": 2,
    }
    verb = object_schema(
        {
            "form": short_string,
            "lemma": short_string,
            "mood": short_string,
            "tense": short_string,
            "voice": short_string,
        },
        ["form", "lemma", "mood", "tense", "voice"],
    )
    subject = object_schema(
        {"text": phrase_string, "uncertain": {"type": "boolean"}},
        ["text", "uncertain"],
    )
    obj = object_schema(
        {
            "text": phrase_string,
            "role": {"type": "string", "enum": ["direct", "indirect", "other"]},
        },
        ["text", "role"],
    )
    clause = object_schema(
        {"text": phrase_string, "kind": short_string, "governor": phrase_string},
        ["text", "kind", "governor"],
    )
    attachment = object_schema(
        {
            "element": phrase_string,
            "to": phrase_string,
            "alternatives": string_array,
        },
        ["element", "to", "alternatives"],
    )
    referent = object_schema(
        {
            "form": short_string,
            "candidate": phrase_string,
            "alternatives": string_array,
        },
        ["form", "candidate", "alternatives"],
    )
    idiom = object_schema(
        {"text": phrase_string, "construction": phrase_string},
        ["text", "construction"],
    )
    alternative = object_schema(
        {
            "issue": phrase_string,
            "analyses": string_array,
            "classification": {
                "type": "string",
                "enum": ["intrinsic_ambiguity", "context_dependent"],
            },
        },
        ["issue", "analyses", "classification"],
    )
    sentence = object_schema(
        {
            "id": {
                "type": "integer",
                "minimum": 1,
                "maximum": sentence_count,
            },
            "verbs": {"type": "array", "items": verb, "maxItems": 6},
            "subject": subject,
            "objects": {"type": "array", "items": obj, "maxItems": 8},
            "clauses": {"type": "array", "items": clause, "maxItems": 12},
            "attachments": {
                "type": "array",
                "items": attachment,
                "maxItems": 10,
            },
            "referents": {"type": "array", "items": referent, "maxItems": 10},
            "idioms": {"type": "array", "items": idiom, "maxItems": 6},
            "alternatives": {
                "type": "array",
                "items": alternative,
                "maxItems": 6,
            },
        },
        [
            "id",
            "verbs",
            "subject",
            "objects",
            "clauses",
            "attachments",
            "referents",
            "idioms",
            "alternatives",
        ],
    )
    issue = object_schema(
        {
            "sentence_id": {
                "type": "integer",
                "minimum": 1,
                "maximum": sentence_count,
            },
            "issue": phrase_string,
        },
        ["sentence_id", "issue"],
    )
    unverified = object_schema(
        {
            "sentence_id": {
                "type": "integer",
                "minimum": 1,
                "maximum": sentence_count,
            },
            "form": short_string,
            "analysis": phrase_string,
            "reason": phrase_string,
        },
        ["sentence_id", "form", "analysis", "reason"],
    )
    return object_schema(
        {
            "sentences": {
                "type": "array",
                "items": sentence,
                "minItems": sentence_count,
                "maxItems": sentence_count,
            },
            "intrinsic": {"type": "array", "items": issue, "maxItems": 12},
            "context": {"type": "array", "items": issue, "maxItems": 12},
            "unverified": {
                "type": "array",
                "items": unverified,
                "maxItems": 12,
            },
        },
        ["sentences", "intrinsic", "context", "unverified"],
    )


def expand_structural_wire(
    value: dict[str, Any], target_latin: str
) -> dict[str, Any]:
    """Validate compact model output and restore the canonical audit schema."""
    expected_top = {"sentences", "intrinsic", "context", "unverified"}
    if set(value) != expected_top:
        raise SchemaValidationError(
            "compact structural output must contain exactly "
            f"{sorted(expected_top)}"
        )
    sentences = split_sentences(target_latin)
    wire_sentences = value.get("sentences")
    if not isinstance(wire_sentences, list):
        raise SchemaValidationError("compact structural sentences must be a list")
    if len(wire_sentences) != len(sentences):
        raise SchemaValidationError(
            f"compact structural output has {len(wire_sentences)} sentences; "
            f"expected {len(sentences)}"
        )

    required_sentence = {
        "id",
        "verbs",
        "subject",
        "objects",
        "clauses",
        "attachments",
        "referents",
        "idioms",
        "alternatives",
    }
    by_id: dict[int, dict[str, Any]] = {}
    for index, wire in enumerate(wire_sentences):
        if not isinstance(wire, dict) or set(wire) != required_sentence:
            raise SchemaValidationError(
                f"compact structural sentence {index} has invalid fields"
            )
        sentence_id = wire.get("id")
        if isinstance(sentence_id, bool) or not isinstance(sentence_id, int):
            raise SchemaValidationError(
                f"compact structural sentence {index}.id must be an integer"
            )
        if sentence_id in by_id:
            raise SchemaValidationError(
                f"compact structural sentence id {sentence_id} is duplicated"
            )
        by_id[sentence_id] = wire
    expected_ids = set(range(1, len(sentences) + 1))
    if set(by_id) != expected_ids:
        raise SchemaValidationError(
            f"compact structural sentence ids must be {sorted(expected_ids)}"
        )

    def require_list(
        item: dict[str, Any],
        key: str,
        label: str,
        *,
        maximum: int | None = None,
    ) -> list[Any]:
        result = item.get(key)
        if not isinstance(result, list):
            raise SchemaValidationError(f"{label}.{key} must be a list")
        if maximum is not None and len(result) > maximum:
            raise SchemaValidationError(
                f"{label}.{key} has {len(result)} entries; maximum is {maximum}"
            )
        return result

    def require_object(item: dict[str, Any], key: str, label: str) -> dict[str, Any]:
        result = item.get(key)
        if not isinstance(result, dict):
            raise SchemaValidationError(f"{label}.{key} must be an object")
        return result

    canonical_sentences = []
    for sentence_id, (_, _, latin) in enumerate(sentences, 1):
        wire = by_id[sentence_id]
        label = f"compact structural sentence {sentence_id}"
        subject_value = require_object(wire, "subject", label)
        verbs = require_list(wire, "verbs", label, maximum=6)
        objects = require_list(wire, "objects", label)
        clauses = require_list(wire, "clauses", label)
        attachments = require_list(wire, "attachments", label)
        referents = require_list(wire, "referents", label)
        idioms = require_list(wire, "idioms", label)
        alternatives = require_list(wire, "alternatives", label)
        for collection_name, collection in (
            ("verbs", verbs),
            ("objects", objects),
            ("clauses", clauses),
            ("attachments", attachments),
            ("referents", referents),
            ("idioms", idioms),
            ("alternatives", alternatives),
        ):
            if not all(isinstance(entry, dict) for entry in collection):
                raise SchemaValidationError(
                    f"{label}.{collection_name} entries must be objects"
                )
        canonical_sentences.append(
            {
                "latin": latin,
                "main_verbs": [
                    {
                        "form": item.get("form", ""),
                        "lemma": item.get("lemma", ""),
                        "mood": item.get("mood", ""),
                        "tense": item.get("tense", ""),
                        "voice": item.get("voice", ""),
                        "basis": "blind structural model constrained by morphology",
                    }
                    for item in verbs
                ],
                "subject": {
                    "text": subject_value.get("text", ""),
                    "basis": "blind structural model",
                    "uncertain": bool(subject_value.get("uncertain", False)),
                },
                "objects": [
                    {
                        "text": item.get("text", ""),
                        "role": item.get("role", "other"),
                        "basis": "blind structural model",
                    }
                    for item in objects
                ],
                "subordinate_clauses": [
                    {
                        "latin": item.get("text", ""),
                        "kind": item.get("kind", ""),
                        "governor": item.get("governor", ""),
                    }
                    for item in clauses
                ],
                "attachments": [
                    {
                        "element": item.get("element", ""),
                        "attaches_to": item.get("to", ""),
                        "alternatives": item.get("alternatives", []),
                    }
                    for item in attachments
                ],
                "referents": [
                    {
                        "form": item.get("form", ""),
                        "candidate": item.get("candidate", ""),
                        "alternatives": item.get("alternatives", []),
                    }
                    for item in referents
                ],
                "idioms": [
                    {
                        "latin": item.get("text", ""),
                        "construction": item.get("construction", ""),
                    }
                    for item in idioms
                ],
                "alternatives": [
                    {
                        "issue": item.get("issue", ""),
                        "analyses": item.get("analyses", []),
                        "classification": item.get("classification", ""),
                    }
                    for item in alternatives
                ],
            }
        )

    for field in ("intrinsic", "context", "unverified"):
        if not isinstance(value.get(field), list):
            raise SchemaValidationError(f"compact structural {field} must be a list")
        if not all(isinstance(entry, dict) for entry in value[field]):
            raise SchemaValidationError(
                f"compact structural {field} entries must be objects"
            )
    canonical = {
        "sentences": canonical_sentences,
        "intrinsic_ambiguity": value["intrinsic"],
        "context_dependent": value["context"],
        "unverified_analyses": value["unverified"],
    }
    return validate_structural(canonical)


def validate_prosecutor(value: dict[str, Any]) -> dict[str, Any]:
    _require(value, {"status", "summary", "challenges", "evidence_requests"}, "prosecutor")
    if value["status"] not in PROSECUTOR_STATUSES:
        raise SchemaValidationError(f"Invalid prosecutor status: {value['status']!r}")
    if not isinstance(value["challenges"], list):
        raise SchemaValidationError("prosecutor.challenges must be a list")
    if not isinstance(value["evidence_requests"], list):
        raise SchemaValidationError("prosecutor.evidence_requests must be a list")
    if value["status"] == "grounded_challenge" and not value["challenges"]:
        raise SchemaValidationError(
            "grounded_challenge status requires at least one precise challenge"
        )
    if value["status"] == "requires_evidence" and not value["evidence_requests"]:
        raise SchemaValidationError(
            "requires_evidence status requires at least one evidence request"
        )
    for index, challenge in enumerate(value["challenges"]):
        if not isinstance(challenge, dict):
            raise SchemaValidationError(f"prosecutor challenge {index} must be an object")
        _require(
            challenge,
            {"latin", "type", "severity", "witness_target", "claim", "visible_basis", "requires_external_evidence"},
            f"prosecutor challenge {index}",
        )
        if challenge["severity"] not in SEVERITIES:
            raise SchemaValidationError(f"Invalid challenge severity at index {index}")
        if not isinstance(challenge["requires_external_evidence"], bool):
            raise SchemaValidationError(
                f"challenge {index}.requires_external_evidence must be boolean"
            )
    for index, request in enumerate(value["evidence_requests"]):
        validate_evidence_request(request, label=f"evidence request {index}")
    return value


def validate_evidence_request(
    value: Any, *, label: str = "evidence request"
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise SchemaValidationError(f"{label} must be an object")
    _require(value, {"kind", "query", "reason"}, label)
    if not all(isinstance(value[field], str) and value[field].strip() for field in ("kind", "query", "reason")):
        raise SchemaValidationError(f"{label} fields must be non-empty strings")
    if value["kind"] not in EVIDENCE_KINDS:
        raise SchemaValidationError(
            f"{label}.kind is unsupported: {value['kind']!r}"
        )
    return value


def adjudication_schema(
    allowed_base_witnesses: list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """Provider-enforced wire contract for both adjudicator passes."""

    allowed_bases = list(
        ("a", "b")
        if allowed_base_witnesses is None
        else allowed_base_witnesses
    )
    if not allowed_bases or any(item not in {"a", "b"} for item in allowed_bases):
        raise ValueError("allowed_base_witnesses must contain only 'a' and/or 'b'")

    text = {"type": "string", "maxLength": 800}
    nonempty_text = {
        "type": "string",
        "minLength": 1,
        "maxLength": 500,
    }
    text_array = {
        "type": "array",
        "items": {"type": "string", "maxLength": 320},
        "maxItems": 8,
    }

    def closed(
        properties: dict[str, Any], required: list[str]
    ) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": False,
        }

    evidence_ids = {
        "type": "array",
        "items": {"type": "string", "minLength": 1, "maxLength": 100},
        "maxItems": 12,
    }
    evidence_request = closed(
        {
            "kind": {
                "type": "string",
                "enum": list(EVIDENCE_KINDS),
            },
            "query": nonempty_text,
            "reason": nonempty_text,
        },
        ["kind", "query", "reason"],
    )
    finding = closed(
        {
            "latin": text,
            "english": text,
            "type": {
                "type": "string",
                "enum": [
                    "negation",
                    "subject_object",
                    "number",
                    "lexical",
                    "attachment",
                    "omission",
                    "addition",
                    "unsupported_certainty",
                    "scripture",
                    "proper_name",
                    "idiom",
                    "hebrew_greek",
                    "textual",
                    "chronology",
                    "morphology",
                    "source_text",
                    "internal_consistency",
                    "other",
                ],
            },
            "severity": {"type": "string", "enum": sorted(SEVERITIES)},
            "resolution": text,
            "reason": text,
            "evidence_ids": evidence_ids,
        },
        [
            "latin",
            "english",
            "type",
            "severity",
            "resolution",
            "reason",
            "evidence_ids",
        ],
    )
    unresolved = closed(
        {
            "latin": text,
            "english": text,
            "alternatives": text_array,
            "missing_evidence": text,
        },
        ["latin", "english", "alternatives", "missing_evidence"],
    )
    human_review = closed(
        {
            "latin": text,
            "english": text,
            "issue": text,
            "action": text,
        },
        ["latin", "english", "issue", "action"],
    )
    decision_basis = closed(
        {
            "grade": {"type": "string", "enum": ["A", "B", "C", "D"]},
            "claim": text,
            "evidence_ids": evidence_ids,
        },
        ["grade", "claim", "evidence_ids"],
    )
    edit = closed(
        {
            "old": {
                "type": "string",
                "minLength": 1,
                "maxLength": 1200,
            },
            "new": {
                "type": "string",
                "maxLength": 1200,
            },
            "reason": nonempty_text,
            "evidence_ids": evidence_ids,
        },
        ["old", "new", "reason", "evidence_ids"],
    )
    return closed(
        {
            "status": {"type": "string", "enum": sorted(FINAL_STATUSES)},
            "base_witness": {"type": "string", "enum": allowed_bases},
            "edits": {
                "type": "array",
                "items": edit,
                "maxItems": 12,
            },
            "summary": text,
            "coverage": closed(
                {
                    "all_clauses_accounted_for": {"type": "boolean"},
                    "omissions_corrected": text_array,
                },
                ["all_clauses_accounted_for", "omissions_corrected"],
            ),
            "findings": {
                "type": "array",
                "items": finding,
                "maxItems": 12,
            },
            "unresolved_issues": {
                "type": "array",
                "items": unresolved,
                "maxItems": 8,
            },
            "human_review_requests": {
                "type": "array",
                "items": human_review,
                "maxItems": 8,
            },
            "evidence_requests": {
                "type": "array",
                "items": evidence_request,
                "maxItems": 6,
            },
            "decision_basis": {
                "type": "array",
                "items": decision_basis,
                "maxItems": 12,
            },
        },
        [
            "status",
            "base_witness",
            "edits",
            "summary",
            "coverage",
            "findings",
            "unresolved_issues",
            "human_review_requests",
            "evidence_requests",
            "decision_basis",
        ],
    )


def expand_adjudication_wire(
    value: dict[str, Any],
    witness_a: str,
    witness_b: str,
    *,
    allowed_base_witnesses: list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """Apply bounded exact edits to a complete independent witness."""

    base_witness = value.get("base_witness")
    if base_witness not in {"a", "b"}:
        raise SchemaValidationError("adjudication.base_witness must be 'a' or 'b'")
    allowed_bases = set(
        ("a", "b")
        if allowed_base_witnesses is None
        else allowed_base_witnesses
    )
    if not allowed_bases or not allowed_bases.issubset({"a", "b"}):
        raise SchemaValidationError(
            "allowed_base_witnesses must contain only 'a' and/or 'b'"
        )
    if base_witness not in allowed_bases:
        raise SchemaValidationError(
            "adjudication.base_witness is not permitted by the deterministic "
            f"witness quorum: {base_witness!r} not in {sorted(allowed_bases)!r}"
        )
    edits = value.get("edits")
    if not isinstance(edits, list):
        raise SchemaValidationError("adjudication.edits must be a list")
    raw_base = witness_a if base_witness == "a" else witness_b
    final_draft = re.sub(
        r"^\s*Here is (?:the )?translation of the target Latin passage:\s*",
        "",
        raw_base,
        count=1,
        flags=re.IGNORECASE,
    )
    wrapper_removed = final_draft != raw_base
    normalized_edits: list[tuple[int, dict[str, Any]]] = []
    for index, edit in enumerate(edits):
        if not isinstance(edit, dict):
            raise SchemaValidationError(f"adjudication edit {index} must be an object")
        old = edit.get("old")
        new = edit.get("new")
        if not isinstance(old, str) or not old:
            raise SchemaValidationError(f"adjudication edit {index}.old must be non-empty")
        if not isinstance(new, str):
            raise SchemaValidationError(f"adjudication edit {index}.new must be a string")
        normalized_edits.append((index, edit))

    def apply_order(
        order: list[tuple[int, dict[str, Any]]],
    ) -> tuple[str, list[dict[str, Any]]] | None:
        draft = final_draft
        applied: list[dict[str, Any]] = []
        for application_order, (model_index, edit) in enumerate(order):
            old = edit["old"]
            matches = draft.count(old)
            if matches != 1:
                return None
            start = draft.index(old)
            draft = draft[:start] + edit["new"] + draft[start + len(old) :]
            applied.append(
                {
                    **edit,
                    "model_order": model_index,
                    "application_order": application_order,
                    "start_before": start,
                    "end_before": start + len(old),
                }
            )
        return draft, applied

    application_mode = "model_order"
    applied_result = apply_order(normalized_edits)
    if applied_result is None:
        # A model can emit a general replacement before a longer overlapping
        # replacement, making the general substring non-unique. Trying longer
        # exact substrings first resolves ordering only; it never chooses among
        # duplicate occurrences. Any remaining ambiguity still fails closed.
        specific_first = sorted(
            normalized_edits,
            key=lambda item: (-len(item[1]["old"]), item[0]),
        )
        applied_result = apply_order(specific_first)
        application_mode = "specificity_fallback"
    if applied_result is None:
        for index, edit in normalized_edits:
            matches = final_draft.count(edit["old"])
            if matches != 1:
                raise SchemaValidationError(
                    f"adjudication edit {index}.old must match the evolving base "
                    f"exactly once; found {matches}"
                )
        raise SchemaValidationError("adjudication edits have no unambiguous application order")
    final_draft, applied_edits = applied_result

    canonical = json.loads(json.dumps(value, ensure_ascii=False))
    canonical.pop("base_witness", None)
    canonical.pop("edits", None)
    canonical["final_draft"] = final_draft
    if applied_edits and canonical.get("status") == "accepted":
        canonical["status"] = "corrected"
    coverage = canonical.get("coverage")
    if not isinstance(coverage, dict):
        raise SchemaValidationError("adjudication.coverage must be an object")
    coverage["base_witness"] = base_witness
    coverage["base_wrapper_removed"] = wrapper_removed
    coverage["edit_application_mode"] = application_mode
    coverage["applied_edits"] = applied_edits
    normalize_adjudication_status(canonical)
    return validate_adjudication(canonical)


def normalize_adjudication_status(value: dict[str, Any]) -> dict[str, Any]:
    """Make review-bearing decisions fail closed without touching raw output."""

    if value.get("human_review_requests"):
        value["status"] = "human_review"
    elif value.get("unresolved_issues") and value.get("status") in {
        "accepted",
        "corrected",
    }:
        value["status"] = "unresolved"
    return value


def validate_adjudication(value: dict[str, Any]) -> dict[str, Any]:
    _require(
        value,
        {
            "status",
            "final_draft",
            "summary",
            "coverage",
            "findings",
            "unresolved_issues",
            "human_review_requests",
            "evidence_requests",
            "decision_basis",
        },
        "adjudication",
    )
    if value["status"] not in FINAL_STATUSES:
        raise SchemaValidationError(f"Invalid final status: {value['status']!r}")
    if not isinstance(value["final_draft"], str):
        raise SchemaValidationError("adjudication.final_draft must be a string")
    if value["status"] in {"accepted", "corrected"} and not value["final_draft"].strip():
        raise SchemaValidationError("accepted/corrected decisions require final_draft")
    if not isinstance(value["coverage"], dict) or not isinstance(
        value["coverage"].get("all_clauses_accounted_for"), bool
    ):
        raise SchemaValidationError("coverage.all_clauses_accounted_for must be boolean")
    for field in (
        "findings",
        "unresolved_issues",
        "human_review_requests",
        "evidence_requests",
        "decision_basis",
    ):
        if not isinstance(value[field], list):
            raise SchemaValidationError(f"adjudication.{field} must be a list")
    for request in value["evidence_requests"]:
        validate_evidence_request(request)
    if value["status"] == "unresolved" and not value["unresolved_issues"]:
        raise SchemaValidationError("unresolved status requires precise unresolved_issues")
    if value["status"] == "human_review" and not value["human_review_requests"]:
        raise SchemaValidationError("human_review status requires precise requests")
    if value["status"] in {"accepted", "corrected"} and (
        value["unresolved_issues"] or value["human_review_requests"]
    ):
        raise SchemaValidationError(
            "accepted/corrected decisions cannot contain unresolved or human-review items"
        )
    return value


def locate_exact_substring(haystack: str, needle: str | None) -> dict[str, Any]:
    if not needle:
        return {"start": None, "end": None, "matches": 0, "ambiguous": False}
    starts = [match.start() for match in re.finditer(re.escape(needle), haystack)]
    if not starts:
        return {"start": None, "end": None, "matches": 0, "ambiguous": False}
    return {
        "start": starts[0],
        "end": starts[0] + len(needle),
        "matches": len(starts),
        "ambiguous": len(starts) > 1,
    }


def enrich_adjudication_offsets(value: dict[str, Any], latin: str) -> dict[str, Any]:
    final = value.get("final_draft", "")
    for collection_name in ("findings", "unresolved_issues", "human_review_requests"):
        for item in value.get(collection_name, []):
            if not isinstance(item, dict):
                continue
            latin_location = locate_exact_substring(latin, item.get("latin"))
            english_location = locate_exact_substring(final, item.get("english"))
            item["latin_locator"] = latin_location
            item["english_locator"] = english_location
    return value


VALIDATORS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "structural_parse": validate_structural,
    "prosecutor_initial": validate_prosecutor,
    "prosecutor_grounded": validate_prosecutor,
    "adjudicator": validate_adjudication,
}
