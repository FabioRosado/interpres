from __future__ import annotations

import json
import math
import re
from collections import Counter
from difflib import SequenceMatcher
from typing import Any

from .checks import (
    CURATED_PROPER_NAME_EQUIVALENTS,
    DEFAULT_ARCHAIC_RESIDUE,
    modernization_check_text,
)
from .tasks import task_profile_from_chunk

WITNESS_CONTRACT_VERSION = 4
WITNESS_VALIDATION_POLICY_VERSION = 8
WITNESS_QUORUM_POLICY_VERSION = 1
MAX_CONTIGUOUS_LATIN_COPY_WORDS = 7
MIN_CONTEXT_ANCHOR_MATCHES = 2
WORD_RE = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ]+")
META_PREAMBLE_RE = re.compile(
    r"^\s*(?:here\s+is|below\s+is|the\s+following\s+is).*?translation",
    re.IGNORECASE | re.DOTALL,
)
QUOTED_TEXT_RE = re.compile(r'"[^"]+"|“[^”]+”')


def expected_source_unit_ids(chunk: dict[str, Any]) -> list[str]:
    units = chunk.get("source_units") or []
    return [
        str(unit.get("source_unit_id"))
        for unit in units
        if isinstance(unit, dict) and unit.get("source_unit_id")
    ]


def _configured_archaic_terms(chunk: dict[str, Any]) -> set[str]:
    checks = chunk.get("checks") if isinstance(chunk.get("checks"), dict) else {}
    raw = checks.get("archaic_residue_terms")
    if isinstance(raw, list):
        configured = {str(item).casefold() for item in raw if str(item).strip()}
        if configured:
            return configured
    return set(DEFAULT_ARCHAIC_RESIDUE)


def _modernization_word_set(chunk: dict[str, Any], value: str) -> set[str]:
    return {
        word.casefold()
        for word in WORD_RE.findall(modernization_check_text(chunk, value))
    }


def witness_contract_schema(chunk: dict[str, Any]) -> dict[str, Any]:
    unit_ids = expected_source_unit_ids(chunk)
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["segments", "omissions", "uncertainties"],
        "properties": {
            "segments": {
                "type": "array",
                "minItems": len(unit_ids),
                "maxItems": len(unit_ids),
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "source_unit_id",
                        "translation",
                    ],
                    "properties": {
                        "source_unit_id": {
                            "type": "string",
                            **({"enum": unit_ids} if unit_ids else {}),
                        },
                        "translation": {
                            "type": "string",
                            "minLength": 1,
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


def _derived_end_marker(text: str) -> str:
    matches = list(WORD_RE.finditer(text))
    if not matches:
        return text[-100:]
    count = min(8, len(matches))
    while count > 1:
        marker = text[matches[-count].start() :].strip()
        if len(marker) <= 100:
            return marker
        count -= 1
    return text[matches[-1].start() :].strip()[-100:]


def _derive_segment_translation(
    segments: Any,
) -> tuple[str, list[dict[str, Any]]]:
    if not isinstance(segments, list):
        return "", []
    translation = ""
    mappings: list[dict[str, Any]] = []
    for item in segments:
        if not isinstance(item, dict):
            continue
        text = item.get("translation")
        unit_id = item.get("source_unit_id")
        if not isinstance(text, str) or not isinstance(unit_id, str):
            continue
        clean = text.strip()
        if translation and clean:
            translation += " "
        start = len(translation)
        translation += clean
        mappings.append(
            {
                "source_unit_id": unit_id,
                "english_end_quote": _derived_end_marker(clean),
                "translation_start": start,
                "translation_end": len(translation),
            }
        )
    return translation, mappings


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
    if "segments" in value:
        translation, mappings = _derive_segment_translation(value.get("segments"))
        return {
            "translation": translation,
            "segments": value.get("segments", []),
            "source_mappings": mappings,
            "uncertainties": value.get("uncertainties", []),
            "omissions": value.get("omissions", []),
            "contract": value,
            "contract_format": "witness_json_v3",
            "parse_error": None,
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


def parse_plain_witness_proposal(raw: str) -> dict[str, Any]:
    """Treat the complete provider response as an immutable v4 proposal.

    Do not strip known boilerplate here: commentary and fences must remain
    visible to the validation boundary and audit trail.
    """

    return {
        "translation": raw.strip(),
        "contract": None,
        "contract_format": "witness_plain_v4",
        "parse_error": None,
        "source_mappings": [],
        "omissions": None,
        "uncertainties": [],
    }


def _contract_shape_errors(contract: dict[str, Any] | None) -> list[str]:
    if contract is None:
        return ["response is not a JSON object"]
    if "segments" in contract:
        required = {"segments", "omissions", "uncertainties"}
        errors = []
        if set(contract) != required:
            errors.append(
                "top-level keys must be exactly " + ", ".join(sorted(required))
            )
        segments = contract.get("segments")
        if not isinstance(segments, list):
            errors.append("segments must be an array")
        else:
            for index, item in enumerate(segments):
                if not isinstance(item, dict) or set(item) != {
                    "source_unit_id",
                    "translation",
                }:
                    errors.append(f"segments[{index}] has invalid keys")
                    continue
                if (
                    not isinstance(item.get("source_unit_id"), str)
                    or not item.get("source_unit_id")
                    or not isinstance(item.get("translation"), str)
                    or not item.get("translation", "").strip()
                ):
                    errors.append(f"segments[{index}] values must be nonempty text")
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


def _name_stem(value: str) -> str:
    folded = value.casefold().replace("j", "i").replace("v", "u")
    return folded[: min(6, len(folded))]


def _missing_proper_name_multiplicity(
    latin: str, translation: str
) -> list[dict[str, Any]]:
    latin_counter = Counter(word.casefold() for word in WORD_RE.findall(latin))
    english_counter = Counter(
        word.casefold() for word in WORD_RE.findall(translation)
    )
    missing = []
    for source_form, equivalents in CURATED_PROPER_NAME_EQUIVALENTS.items():
        required_count = latin_counter[source_form]
        if not required_count:
            continue
        rendered_count = sum(english_counter[value] for value in equivalents)
        if rendered_count < required_count:
            missing.append(
                {
                    "source_form": source_form,
                    "required_count": required_count,
                    "rendered_count": rendered_count,
                    "expected_any": sorted(equivalents),
                }
            )
    return missing


def _context_leakage_signal(chunk: dict[str, Any], translation: str) -> dict[str, Any]:
    """Conservative signals only; this does not pretend to back-translate."""

    target_stems = {
        _name_stem(word)
        for word in WORD_RE.findall(str(chunk.get("target_latin") or ""))
        if len(word) >= 4
    }
    output_stems = {
        _name_stem(word) for word in WORD_RE.findall(translation) if len(word) >= 4
    }
    sides = {}
    literal = {}
    for side in ("context_before", "context_after"):
        context = str(chunk.get(side) or "")
        anchors = []
        for word in WORD_RE.findall(context):
            if len(word) < 4 or not word[:1].isupper():
                continue
            stem = _name_stem(word)
            if stem in target_stems or stem not in output_stems:
                continue
            anchors.append(word)
        sides[side] = list(dict.fromkeys(anchors))
        literal[side] = _longest_source_copy(context, translation)
    matched_anchor_count = len(
        {_name_stem(word) for values in sides.values() for word in values}
    )
    max_literal = max(
        (item["word_count"] for item in literal.values()), default=0
    )
    suspicious = (
        matched_anchor_count >= MIN_CONTEXT_ANCHOR_MATCHES
        or max_literal > MAX_CONTIGUOUS_LATIN_COPY_WORDS
    )
    return {
        "suspicious": suspicious,
        "matched_distinctive_anchor_count": matched_anchor_count,
        "minimum_anchor_matches": MIN_CONTEXT_ANCHOR_MATCHES,
        "matched_anchors": sides,
        "literal_context_copy": literal,
        "maximum_literal_words": MAX_CONTIGUOUS_LATIN_COPY_WORDS,
        "limit": (
            "Conservative proper-name/literal-copy signal; absence does not prove "
            "that translated context is absent."
        ),
    }


def estimate_witness_output_budget(
    chunk: dict[str, Any],
    prompt: str,
    *,
    max_output_tokens: int,
    context_window: int,
) -> dict[str, Any]:
    """Conservative provider-free preflight for the plain witness contract."""

    task = task_profile_from_chunk(chunk)
    target_bytes = len(task.source_text(chunk).encode("utf-8"))
    target_token_proxy = math.ceil(target_bytes / 4)
    # Cached complete free-text witnesses in chunks 1-3 used about 0.97-1.07
    # output tokens per target token proxy. Keep 20% translation headroom.
    translation_tokens = math.ceil(target_token_proxy * 1.2)
    # v4 deliberately avoids provider-enforced JSON. Matched-seed Chunk 5
    # controls showed that even a one-string JSON schema caused a decisive
    # parenthetical clause to disappear while the plain response retained it.
    contract_tokens = 0
    uncertainty_reserve_tokens = 64
    before_margin = (
        translation_tokens + contract_tokens + uncertainty_reserve_tokens
    )
    margin_tokens = max(128, math.ceil(before_margin * 0.15))
    required_output_tokens = before_margin + margin_tokens
    estimated_prompt_tokens = math.ceil(len(prompt.encode("utf-8")) / 4)
    output_fits = required_output_tokens <= max_output_tokens
    context_fits = estimated_prompt_tokens + required_output_tokens <= context_window
    return {
        "policy_version": 3,
        "method": "plain_text_utf8_bytes_div_4_calibrated_from_book1_controls",
        "target_token_proxy": target_token_proxy,
        "estimated_translation_tokens": translation_tokens,
        "max_compact_contract_tokens": contract_tokens,
        "uncertainty_reserve_tokens": uncertainty_reserve_tokens,
        "completion_margin_tokens": margin_tokens,
        "estimated_required_output_tokens": required_output_tokens,
        "configured_output_limit": max_output_tokens,
        "estimated_prompt_tokens": estimated_prompt_tokens,
        "configured_context_window": context_window,
        "output_fits": output_fits,
        "context_fits": context_fits,
        "proceed": output_fits and context_fits,
        "failure_reason": (
            None
            if output_fits and context_fits
            else (
                "Estimated plain witness response exceeds configured output budget"
                if not output_fits
                else "Estimated prompt plus response exceeds context window"
            )
        ),
    }


def validate_witness_record(
    chunk: dict[str, Any], record: dict[str, Any], *, witness: str
) -> dict[str, Any]:
    """Validate an immutable witness record as an untrusted proposal."""

    task = task_profile_from_chunk(chunk)
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

    stored_inputs = ((record.get("cache_material") or {}).get("inputs") or {})
    stored_target = stored_inputs.get("target_latin")
    if task.is_modernization and stored_target is None:
        stored_target = stored_inputs.get("source_text")
    check(
        "exact_target_input",
        stored_target == task.source_text(chunk),
        {
            "stored_chars": len(stored_target) if isinstance(stored_target, str) else None,
            "expected_chars": len(task.source_text(chunk)),
        },
    )
    check("raw_response_persisted", bool(raw_text), {"raw_chars": len(raw_text)})

    contract_format = output.get("contract_format")
    plain_contract = contract_format == "witness_plain_v4"
    if fixture:
        check(
            "nonproduction_challenge_fixture",
            True,
            "Frozen challenge candidates intentionally bypass the production witness contract.",
        )
    else:
        check(
            "witness_response_contract",
            plain_contract
            or (
                contract is not None
                and contract_format
                in {"witness_json_v1", "witness_json_v2", "witness_json_v3"}
            ),
            output.get("parse_error")
            or contract_format
            or "legacy cached proposal",
        )
        if plain_contract:
            check(
                "valid_contract_schema",
                True,
                "Not applicable: v4 intentionally uses a raw plain-text response.",
            )
        else:
            schema_errors = _contract_shape_errors(contract)
            check("valid_contract_schema", not schema_errors, schema_errors)

    if contract is not None:
        try:
            parsed_raw = json.loads(raw_text.strip())
        except (json.JSONDecodeError, TypeError):
            parsed_raw = None
        if output.get("contract_format") == "witness_json_v3":
            derived_translation, derived_mappings = _derive_segment_translation(
                contract.get("segments")
            )
            integrity_ok = (
                parsed_raw == contract
                and translation == derived_translation
                and output.get("source_mappings") == derived_mappings
            )
            integrity_detail = (
                "Persisted raw segment JSON must exactly derive the exposed "
                "translation and mappings."
            )
        else:
            integrity_ok = parsed_raw == contract and translation == contract.get(
                "translation"
            )
            integrity_detail = (
                "Persisted raw JSON, parsed contract, and exposed translation "
                "must agree."
            )
        check("raw_contract_integrity", integrity_ok, integrity_detail)
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

    has_meta = bool(
        META_PREAMBLE_RE.search(raw_text) or META_PREAMBLE_RE.search(translation)
    )
    has_fence = (
        raw_text.strip().startswith(("```", "---"))
        or raw_text.strip().endswith(("```", "---"))
        or translation.strip().startswith(("```", "---"))
        or translation.strip().endswith(("```", "---"))
    )
    check(
        "no_commentary_or_fences",
        fixture or (not has_meta and not has_fence),
        {"preamble_detected": has_meta, "fence_detected": has_fence},
    )
    plain_json_envelope = False
    if plain_contract:
        try:
            plain_json_envelope = isinstance(
                json.loads(raw_text.strip()), (dict, list)
            )
        except (json.JSONDecodeError, TypeError):
            pass
    check(
        "plain_text_response_shape",
        fixture or not plain_contract or not plain_json_envelope,
        {"json_envelope_detected": plain_json_envelope},
    )
    check("nonempty_translation", bool(translation.strip()), {"translation_chars": len(translation)})

    if task.is_translation:
        context_leakage = _context_leakage_signal(chunk, translation)
        check(
            "no_context_leakage",
            not context_leakage["suspicious"],
            context_leakage,
        )

    segment_contract = contract_format == "witness_json_v3"
    if segment_contract or plain_contract:
        request_context = {
            "context_before": stored_inputs.get("request_context_before"),
            "context_after": stored_inputs.get("request_context_after"),
        }
        check(
            "auxiliary_context_withheld",
            request_context == {"context_before": "", "context_after": ""},
            request_context,
        )

    expected_ids = expected_source_unit_ids(chunk)
    segments = contract.get("segments") if segment_contract and contract else None
    mappings = (
        output.get("source_mappings")
        if segment_contract
        else contract.get("source_mappings") if contract is not None else None
    )
    reported_ids = [
        item.get("source_unit_id")
        for item in (segments if segment_contract else mappings) or []
        if isinstance(item, dict)
    ]
    if fixture:
        coverage_ok = True
        mapping_detail: Any = "Nonproduction frozen challenge fixture"
        mapping_blocking = True
    elif plain_contract:
        coverage_ok = False
        mapping_blocking = False
        mapping_detail = {
            "expected": expected_ids,
            "reported": [],
            "reason": (
                "Provider-enforced mappings are intentionally unavailable in the "
                "v4 plain-text contract; deterministic whole-target signals apply."
            ),
        }
    else:
        coverage_ok = reported_ids == expected_ids and len(set(reported_ids)) == len(reported_ids)
        mapping_blocking = True
        mapping_detail = {"expected": expected_ids, "reported": reported_ids}
    check(
        "expected_source_units",
        coverage_ok,
        mapping_detail,
        blocking=mapping_blocking,
    )

    spans_ok = bool(mappings) and len(mappings or []) == len(expected_ids)
    marker_candidates: list[list[int]] = []
    for index, item in enumerate([] if segment_contract else mappings or []):
        quote = item.get("english_end_quote") if isinstance(item, dict) else None
        candidates_for_marker = []
        if isinstance(quote, str) and quote:
            offset = 0
            while True:
                found = translation.find(quote, offset)
                if found < 0:
                    break
                candidates_for_marker.append(found)
                offset = found + 1
            if index == len(mappings) - 1:
                boundary = len(translation) - len(quote)
                candidates_for_marker = [
                    value for value in candidates_for_marker if value == boundary
                ]
        marker_candidates.append(candidates_for_marker)

    solutions: list[list[int]] = []

    def resolve_markers(index: int, previous_end: int, chosen: list[int]) -> None:
        if len(solutions) > 1:
            return
        if index == len(marker_candidates):
            solutions.append(list(chosen))
            return
        item = mappings[index]
        quote = item.get("english_end_quote", "")
        for position in marker_candidates[index]:
            if position < previous_end:
                continue
            start_quote = item.get("english_start_quote")
            if isinstance(start_quote, str):
                start_positions = []
                start_at = previous_end
                while True:
                    found = translation.find(start_quote, start_at)
                    if found < 0 or found > position:
                        break
                    start_positions.append(found)
                    start_at = found + 1
                if not start_positions:
                    continue
            chosen.append(position)
            resolve_markers(index + 1, position + len(quote), chosen)
            chosen.pop()

    if spans_ok and not segment_contract:
        resolve_markers(0, 0, [])
    spans_ok = spans_ok and (segment_contract or len(solutions) == 1)
    span_receipts = []
    if segment_contract and spans_ok:
        span_receipts = [
            {
                "source_unit_id": item.get("source_unit_id"),
                "start": item.get("translation_start"),
                "end": item.get("translation_end"),
                "derived_from": "segment_serialization",
            }
            for item in mappings or []
        ]
        solutions = [[item.get("translation_end") for item in mappings or []]]
    elif solutions:
        cursor = 0
        for item, position, candidates_for_marker in zip(
            mappings, solutions[0], marker_candidates
        ):
            quote = item.get("english_end_quote", "")
            span_receipts.append(
                {
                    "source_unit_id": item.get("source_unit_id"),
                    "start": cursor,
                    "end": position,
                    "end_marker_occurrences": len(candidates_for_marker),
                }
            )
            cursor = position + len(quote)
    mapping_detail = {
        "spans": span_receipts,
        "ordered_solutions": len(solutions),
        "ambiguous": len(solutions) > 1,
        "derivation": "segment_serialization" if segment_contract else "end_markers",
    }
    if fixture:
        spans_ok = True
        span_receipts = []
    check(
        "ordered_translation_mappings",
        spans_ok,
        mapping_detail,
        blocking=not plain_contract,
    )

    if task.is_translation:
        missing_global_names = _missing_proper_name_multiplicity(
            task.source_text(chunk), translation
        )
        check(
            "whole_target_name_multiplicity",
            fixture or not missing_global_names,
            {"missing": missing_global_names},
        )

    if segment_contract:
        unit_text = {
            str(item.get("source_unit_id")): str(item.get("text") or "")
            for item in chunk.get("source_units") or []
            if isinstance(item, dict) and item.get("source_unit_id")
        }
        segment_ratios = []
        segment_copies = []
        segment_name_counts = []
        per_unit_length_ok = True
        per_unit_copy_ok = True
        per_unit_names_ok = True
        for item in segments or []:
            unit_id = str(item.get("source_unit_id") or "")
            latin = unit_text.get(unit_id, "")
            rendered = str(item.get("translation") or "")
            latin_count = max(1, len(WORD_RE.findall(latin)))
            english_count = len(WORD_RE.findall(rendered))
            unit_ratio = english_count / latin_count
            unit_copy = _longest_source_copy(latin, rendered)
            copied_fraction = unit_copy["word_count"] / latin_count
            missing_names = _missing_proper_name_multiplicity(latin, rendered)
            segment_ratios.append(
                {
                    "source_unit_id": unit_id,
                    "latin_words": latin_count,
                    "english_words": english_count,
                    "ratio": round(unit_ratio, 3),
                }
            )
            segment_copies.append(
                {
                    "source_unit_id": unit_id,
                    **unit_copy,
                    "latin_word_fraction": round(copied_fraction, 3),
                }
            )
            segment_name_counts.append(
                {"source_unit_id": unit_id, "missing": missing_names}
            )
            per_unit_length_ok = per_unit_length_ok and 0.35 <= unit_ratio <= 2.75
            per_unit_copy_ok = per_unit_copy_ok and not (
                unit_copy["word_count"] > MAX_CONTIGUOUS_LATIN_COPY_WORDS
                or (latin_count >= 3 and unit_copy["word_count"] >= 3 and copied_fraction >= 0.5)
            )
            per_unit_names_ok = per_unit_names_ok and not missing_names
        check(
            "per_source_unit_length_signal",
            per_unit_length_ok and len(segment_ratios) == len(expected_ids),
            {"segments": segment_ratios, "limits": [0.35, 2.75]},
        )
        check(
            "per_source_unit_copy_signal",
            per_unit_copy_ok,
            {
                "segments": segment_copies,
                "maximum_contiguous_words": MAX_CONTIGUOUS_LATIN_COPY_WORDS,
                "short_unit_fraction_rule": {
                    "minimum_copied_words": 3,
                    "minimum_latin_fraction": 0.5,
                },
            },
        )
        check(
            "per_source_unit_name_multiplicity",
            per_unit_names_ok,
            {"segments": segment_name_counts},
        )

    omissions = contract.get("omissions") if contract is not None else None
    check(
        "no_reported_omissions",
        fixture or plain_contract or omissions == [],
        (
            "Not applicable: v4 relies on deterministic omission signals."
            if plain_contract
            else omissions
        ),
    )

    if task.is_translation:
        copied = _longest_source_copy(task.source_text(chunk), translation)
        check(
            "no_suspicious_source_copy",
            copied["word_count"] <= MAX_CONTIGUOUS_LATIN_COPY_WORDS,
            {**copied, "maximum_words": MAX_CONTIGUOUS_LATIN_COPY_WORDS},
        )
    latin_words = max(1, len(WORD_RE.findall(task.source_text(chunk))))
    english_words = len(WORD_RE.findall(translation))
    ratio = english_words / latin_words
    length_limits = [0.6, 1.9] if task.is_modernization else [0.45, 2.2]
    check(
        "coverage_length_signal",
        length_limits[0] <= ratio <= length_limits[1],
        {
            "latin_words": latin_words,
            "english_words": english_words,
            "ratio": round(ratio, 3),
            "limits": length_limits,
        },
    )

    if task.is_modernization:
        archaic_terms = _configured_archaic_terms(chunk)
        source_terms = _modernization_word_set(chunk, task.source_text(chunk))
        target_terms = _modernization_word_set(chunk, translation)
        introduced = [
            term
            for term in sorted(archaic_terms)
            if term in target_terms and term not in source_terms
        ]
        check(
            "no_archaic_introduction",
            not introduced,
            {
                "introduced_terms": introduced,
                "configured_terms": sorted(archaic_terms),
                "ordinary_quotation_marks_protected": False,
                "explicit_protected_spans_ignored": True,
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
        "provider_structured_output_required": False,
    }


def witness_gate_receipt(validations: dict[str, dict[str, Any]]) -> dict[str, Any]:
    valid = [
        name
        for name in ("witness_a", "witness_b")
        if (validations.get(name) or {}).get("valid")
    ]
    invalid = [name for name in ("witness_a", "witness_b") if name not in valid]
    if len(valid) == 2:
        status = "both_valid"
        mode = "normal"
        behavior = "normal_prosecution_and_adjudication"
        automatic_acceptance_allowed = True
    elif len(valid) == 1:
        suffix = valid[0].removeprefix("witness_")
        status = f"single_valid_{suffix}"
        mode = "degraded"
        behavior = (
            "continue_with_valid_witness_only; invalid witness retained as a "
            "non-authoritative audit clue; mandatory human review"
        )
        automatic_acceptance_allowed = False
    else:
        status = "both_invalid"
        mode = "blocked"
        behavior = "fail_closed_before_prosecution; human review or witness rerun required"
        automatic_acceptance_allowed = False
    allowed = [name.removeprefix("witness_") for name in valid]
    return {
        "policy_version": WITNESS_VALIDATION_POLICY_VERSION,
        "quorum_policy_version": WITNESS_QUORUM_POLICY_VERSION,
        "quorum": status,
        "status": status,
        "mode": mode,
        "proceed": status != "both_invalid",
        "automatic_acceptance_allowed": automatic_acceptance_allowed,
        "valid_witnesses": valid,
        "invalid_witnesses": invalid,
        "allowed_base_witnesses": allowed,
        "permitted_base_witness_ids": allowed,
        "corroborating_witnesses": valid if status == "both_valid" else [],
        "invalid_witness_output_role": "non_authoritative_clue_not_evidence",
        "invalid_witness_may_support_evidence_grade": False,
        "degraded_reason": (
            None
            if mode == "normal"
            else (
                "Exactly one witness passed deterministic validation; automatic "
                "acceptance is disabled and only that witness may be a base."
                if mode == "degraded"
                else "Neither witness passed deterministic validation."
            )
        ),
        "behavior": behavior,
        "validations": {
            name: {
                "valid": receipt.get("valid"),
                "blocking_failures": receipt.get("blocking_failures", []),
            }
            for name, receipt in validations.items()
        },
    }
