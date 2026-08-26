from __future__ import annotations

import json
import re
from difflib import SequenceMatcher
from typing import Any


WITNESS_CONTRACT_VERSION = 2
WITNESS_VALIDATION_POLICY_VERSION = 3
MAX_CONTIGUOUS_LATIN_COPY_WORDS = 7
WORD_RE = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ]+")
META_PREAMBLE_RE = re.compile(
    r"^\s*(?:here\s+is|below\s+is|the\s+following\s+is).*?translation",
    re.IGNORECASE | re.DOTALL,
)


def expected_source_unit_ids(chunk: dict[str, Any]) -> list[str]:
    units = chunk.get("source_units") or []
    return [
        str(unit.get("source_unit_id"))
        for unit in units
        if isinstance(unit, dict) and unit.get("source_unit_id")
    ]


def witness_contract_schema(chunk: dict[str, Any]) -> dict[str, Any]:
    unit_ids = expected_source_unit_ids(chunk)
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["translation", "source_mappings", "omissions", "uncertainties"],
        "properties": {
            "translation": {"type": "string", "minLength": 1},
            "source_mappings": {
                "type": "array",
                "minItems": len(unit_ids),
                "maxItems": len(unit_ids),
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "source_unit_id",
                        "english_end_quote",
                    ],
                    "properties": {
                        "source_unit_id": {
                            "type": "string",
                            **({"enum": unit_ids} if unit_ids else {}),
                        },
                        "english_end_quote": {
                            "type": "string",
                            "minLength": 3,
                            "maxLength": 100,
                        },
                    },
                },
            },
            "omissions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["source_unit_id", "latin", "reason"],
                    "properties": {
                        "source_unit_id": {"type": "string"},
                        "latin": {"type": "string"},
                        "reason": {"type": "string"},
                    },
                },
            },
            "uncertainties": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
    }


def parse_witness_proposal(raw: str) -> dict[str, Any]:
    """Persist a proposal without treating successful parsing as trust."""

    stripped = raw.strip()
    try:
        value = json.loads(stripped)
    except (json.JSONDecodeError, TypeError) as exc:
        return {
            "translation": stripped,
            "contract": None,
            "contract_format": "legacy_plain_text",
            "parse_error": str(exc),
        }
    if not isinstance(value, dict):
        return {
            "translation": "",
            "contract": None,
            "contract_format": "invalid_json_value",
            "parse_error": "Witness JSON must be an object",
        }
    return {
        "translation": value.get("translation") if isinstance(value.get("translation"), str) else "",
        "source_mappings": value.get("source_mappings", []),
        "uncertainties": value.get("uncertainties", []),
        "omissions": value.get("omissions", []),
        "contract": value,
        "contract_format": "witness_json_v2",
        "parse_error": None,
    }


def _contract_shape_errors(contract: dict[str, Any] | None) -> list[str]:
    if contract is None:
        return ["response is not a JSON object"]
    required = {"translation", "source_mappings", "omissions", "uncertainties"}
    errors = []
    if set(contract) != required:
        errors.append(
            "top-level keys must be exactly " + ", ".join(sorted(required))
        )
    if not isinstance(contract.get("translation"), str) or not contract.get(
        "translation", ""
    ).strip():
        errors.append("translation must be nonempty text")
    mappings = contract.get("source_mappings")
    if not isinstance(mappings, list):
        errors.append("source_mappings must be an array")
    else:
        compact_mapping = {"source_unit_id", "english_end_quote"}
        legacy_mapping = {
            "source_unit_id",
            "english_start_quote",
            "english_end_quote",
        }
        for index, item in enumerate(mappings):
            item_keys = frozenset(item) if isinstance(item, dict) else frozenset()
            if not isinstance(item, dict) or item_keys not in {
                frozenset(compact_mapping),
                frozenset(legacy_mapping),
            }:
                errors.append(f"source_mappings[{index}] has invalid keys")
                continue
            if (
                not isinstance(item.get("source_unit_id"), str)
                or not item.get("source_unit_id")
                or not isinstance(item.get("english_end_quote"), str)
                or not 3 <= len(item.get("english_end_quote")) <= 100
                or (
                    "english_start_quote" in item
                    and (
                        not isinstance(item.get("english_start_quote"), str)
                        or len(item.get("english_start_quote")) < 3
                    )
                )
            ):
                errors.append(f"source_mappings[{index}] values must be text")
    omissions = contract.get("omissions")
    if not isinstance(omissions, list):
        errors.append("omissions must be an array")
    elif any(not isinstance(item, dict) for item in omissions):
        errors.append("omissions entries must be objects")
    uncertainties = contract.get("uncertainties")
    if not isinstance(uncertainties, list) or any(
        not isinstance(item, str) for item in uncertainties or []
    ):
        errors.append("uncertainties must be an array of strings")
    return errors


def _longest_source_copy(latin: str, english: str) -> dict[str, Any]:
    source_matches = list(WORD_RE.finditer(latin))
    output_matches = list(WORD_RE.finditer(english))
    source_words = [item.group(0).casefold() for item in source_matches]
    output_words = [item.group(0).casefold() for item in output_matches]
    longest = max(
        SequenceMatcher(None, source_words, output_words, autojunk=False).get_matching_blocks(),
        key=lambda block: block.size,
        default=None,
    )
    count = longest.size if longest is not None else 0
    phrase = (
        latin[
            source_matches[longest.a].start() : source_matches[
                longest.a + longest.size - 1
            ].end()
        ]
        if longest is not None and longest.size
        else ""
    )
    return {"word_count": count, "source_phrase": phrase}


def validate_witness_record(
    chunk: dict[str, Any], record: dict[str, Any], *, witness: str
) -> dict[str, Any]:
    """Validate an immutable witness record as an untrusted proposal."""

    checks: list[dict[str, Any]] = []

    def check(name: str, passed: bool, detail: Any, *, blocking: bool = True) -> None:
        checks.append(
            {
                "check": name,
                "status": "pass" if passed else "failure",
                "blocking": blocking and not passed,
                "detail": detail,
            }
        )

    output = record.get("output") if isinstance(record.get("output"), dict) else {}
    raw = record.get("raw_response")
    raw_text = raw if isinstance(raw, str) else ""
    contract = output.get("contract") if isinstance(output.get("contract"), dict) else None
    translation = output.get("translation") if isinstance(output.get("translation"), str) else ""
    model = record.get("model") if isinstance(record.get("model"), dict) else {}
    attempts = record.get("provider_attempts") if isinstance(record.get("provider_attempts"), list) else []
    last_attempt = attempts[-1] if attempts and isinstance(attempts[-1], dict) else {}
    fixture = model.get("provider") == "challenge_fixture"

    stored_target = (
        ((record.get("cache_material") or {}).get("inputs") or {}).get("target_latin")
    )
    check(
        "exact_target_input",
        stored_target == chunk.get("target_latin"),
        {
            "stored_chars": len(stored_target) if isinstance(stored_target, str) else None,
            "expected_chars": len(str(chunk.get("target_latin") or "")),
        },
    )
    check("raw_response_persisted", bool(raw_text), {"raw_chars": len(raw_text)})

    if fixture:
        check(
            "nonproduction_challenge_fixture",
            True,
            "Frozen challenge candidates intentionally bypass the production witness contract.",
        )
    else:
        check(
            "structured_contract",
            contract is not None
            and output.get("contract_format")
            in {"witness_json_v1", "witness_json_v2"},
            output.get("parse_error") or output.get("contract_format") or "legacy cached proposal",
        )
        schema_errors = _contract_shape_errors(contract)
        check("valid_contract_schema", not schema_errors, schema_errors)

    if contract is not None:
        try:
            parsed_raw = json.loads(raw_text.strip())
        except (json.JSONDecodeError, TypeError):
            parsed_raw = None
        check(
            "raw_contract_integrity",
            parsed_raw == contract and translation == contract.get("translation"),
            "Persisted raw JSON, parsed contract, and exposed translation must agree.",
        )
    else:
        check(
            "raw_translation_integrity",
            raw_text.strip() == translation,
            "Legacy output may differ only by outer whitespace.",
        )

    reason = last_attempt.get("done_reason") or last_attempt.get("finish_reason")
    complete = last_attempt.get("outcome") == "complete" and reason not in {
        "length",
        "max_tokens",
    }
    if fixture and last_attempt.get("outcome") == "complete":
        complete = True
    check(
        "provider_completion",
        complete,
        {
            "outcome": last_attempt.get("outcome"),
            "done": last_attempt.get("done"),
            "done_reason": reason,
        },
    )
    generated = last_attempt.get("eval_count")
    limit = model.get("max_output_tokens")
    token_headroom = (
        isinstance(generated, int)
        and isinstance(limit, int)
        and generated < limit
    )
    if fixture:
        token_headroom = True
    check(
        "output_token_headroom",
        token_headroom,
        {"generated_tokens": generated, "configured_limit": limit},
    )

    has_meta = bool(META_PREAMBLE_RE.search(raw_text))
    has_fence = raw_text.strip().startswith(("```", "---")) or raw_text.strip().endswith(("```", "---"))
    check(
        "no_commentary_or_fences",
        fixture or (not has_meta and not has_fence),
        {"preamble_detected": has_meta, "fence_detected": has_fence},
    )
    check("nonempty_translation", bool(translation.strip()), {"translation_chars": len(translation)})

    expected_ids = expected_source_unit_ids(chunk)
    mappings = contract.get("source_mappings") if contract is not None else None
    reported_ids = [
        item.get("source_unit_id")
        for item in mappings or []
        if isinstance(item, dict)
    ]
    if fixture:
        coverage_ok = True
        mapping_detail: Any = "Nonproduction frozen challenge fixture"
    else:
        coverage_ok = reported_ids == expected_ids and len(set(reported_ids)) == len(reported_ids)
        mapping_detail = {"expected": expected_ids, "reported": reported_ids}
    check("expected_source_units", coverage_ok, mapping_detail)

    spans_ok = bool(mappings) and len(mappings or []) == len(expected_ids)
    cursor = 0
    span_receipts = []
    for index, item in enumerate(mappings or []):
        if not isinstance(item, dict):
            spans_ok = False
            continue
        end_quote = item.get("english_end_quote")
        if not isinstance(end_quote, str):
            spans_ok = False
            continue
        is_last = index == len(mappings) - 1
        end = (
            len(translation) - len(end_quote)
            if is_last and translation.endswith(end_quote)
            else translation.find(end_quote, cursor)
        )
        start_quote = item.get("english_start_quote")
        start = cursor
        if isinstance(start_quote, str):
            start = translation.find(start_quote, cursor)
        current_ok = start >= cursor and end >= start
        spans_ok = spans_ok and current_ok
        if current_ok:
            cursor = end + len(end_quote)
        span_receipts.append(
            {
                "source_unit_id": item.get("source_unit_id"),
                "start": start,
                "end": end,
                "end_marker_occurrences": translation.count(end_quote),
            }
        )
    if mappings and translation:
        last = mappings[-1]
        if isinstance(last, dict):
            last_quote = last.get("english_end_quote")
            spans_ok = spans_ok and isinstance(last_quote, str) and translation.endswith(last_quote)
    if fixture:
        spans_ok = True
        span_receipts = []
    check("ordered_translation_mappings", spans_ok, span_receipts)

    omissions = contract.get("omissions") if contract is not None else None
    check(
        "no_reported_omissions",
        fixture or omissions == [],
        omissions,
    )

    copied = _longest_source_copy(str(chunk.get("target_latin") or ""), translation)
    check(
        "no_suspicious_source_copy",
        copied["word_count"] <= MAX_CONTIGUOUS_LATIN_COPY_WORDS,
        {**copied, "maximum_words": MAX_CONTIGUOUS_LATIN_COPY_WORDS},
    )
    latin_words = max(1, len(WORD_RE.findall(str(chunk.get("target_latin") or ""))))
    english_words = len(WORD_RE.findall(translation))
    ratio = english_words / latin_words
    check(
        "coverage_length_signal",
        0.45 <= ratio <= 2.2,
        {
            "latin_words": latin_words,
            "english_words": english_words,
            "ratio": round(ratio, 3),
            "limits": [0.45, 2.2],
        },
    )

    blocking_failures = [item["check"] for item in checks if item["blocking"]]
    return {
        "policy_version": WITNESS_VALIDATION_POLICY_VERSION,
        "contract_version": WITNESS_CONTRACT_VERSION,
        "witness": witness,
        "valid": not blocking_failures,
        "eligible_as_adjudicator_base": not blocking_failures,
        "blocking_failures": blocking_failures,
        "checks": checks,
        "expected_source_unit_ids": expected_ids,
        "reported_source_unit_ids": reported_ids,
        "translation_chars": len(translation),
        "raw_response_preserved": bool(raw_text),
        "production_contract_required": not fixture,
    }


def witness_gate_receipt(validations: dict[str, dict[str, Any]]) -> dict[str, Any]:
    valid = [name for name, receipt in validations.items() if receipt.get("valid")]
    invalid = [name for name in ("witness_a", "witness_b") if name not in valid]
    if len(valid) == 2:
        status = "both_valid"
        behavior = "normal_prosecution_and_adjudication"
    elif len(valid) == 1:
        status = "single_valid_witness"
        behavior = "fail_closed_before_prosecution; retain valid proposal for human review or rerun"
    else:
        status = "no_valid_witnesses"
        behavior = "fail_closed_before_prosecution; human review or witness rerun required"
    return {
        "policy_version": WITNESS_VALIDATION_POLICY_VERSION,
        "status": status,
        "proceed": status == "both_valid",
        "valid_witnesses": valid,
        "invalid_witnesses": invalid,
        "allowed_base_witnesses": [name.removeprefix("witness_") for name in valid],
        "behavior": behavior,
        "validations": {
            name: {
                "valid": receipt.get("valid"),
                "blocking_failures": receipt.get("blocking_failures", []),
            }
            for name, receipt in validations.items()
        },
    }
