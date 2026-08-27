from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any, Protocol

WORD_RE = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ]+")
ARABIC_RE = re.compile(r"(?<!\w)\d+(?!\w)")
ROMAN_RE = re.compile(r"(?<![A-Za-z])[IVXLCDM]{2,}(?![A-Za-z])")
CHECKS_VERSION = 8
FINAL_CHECKS_VERSION = 4
MAX_AUTOMATIC_EDIT_WORDS = 48
MAX_SOURCE_COPY_WORDS = 7
LATIN_NEGATIONS = {"non", "nec", "neque", "nihil", "numquam", "nunquam", "nullus", "nemo"}
ENGLISH_NEGATIONS = {"not", "no", "nor", "neither", "nothing", "never", "none", "nobody", "without"}
LATIN_NUMBER_CONCEPTS = {
    "unus": {"one", "first", "1"},
    "duo": {"two", "second", "2"},
    "tres": {"three", "third", "3"},
    "tribus": {"three", "third", "3"},
    "quattuor": {"four", "fourth", "4"},
    "quatuor": {"four", "fourth", "4"},
    "quinque": {"five", "fifth", "5"},
    "octo": {"eight", "eighth", "8"},
    "decem": {"ten", "tenth", "10"},
    "duodecimo": {"twelve", "twelfth", "12"},
    "tricesimo": {"thirty", "thirtieth", "30"},
    "triginta": {"thirty", "thirtieth", "30"},
}
LATIN_CARDINAL_VALUES = {
    "unus": 1,
    "duo": 2,
    "tres": 3,
    "tribus": 3,
    "quattuor": 4,
    "quatuor": 4,
    "quinque": 5,
    "octo": 8,
    "decem": 10,
    "triginta": 30,
}
ENGLISH_CARDINAL_VALUES = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
    "thirty": 30,
}
CURATED_PROPER_NAME_EQUIVALENTS = {
    "paulae": {"paula"},
    "jesu": {"jesus"},
    "christi": {"christ"},
    "paulus": {"paul"},
    "pauli": {"paul"},
    "matthaei": {"matthew"},
    "marcum": {"mark"},
    "lucae": {"luke"},
    "joannis": {"john"},
    "isaia": {"isaiah"},
    "zachariae": {"zacharias", "zachariah"},
    "aquila": {"aquila"},
}
CURATED_TRANSLATION_TRAPS = (
    {
        "source_phrase": "electri",
        "wrong_renderings": ("lightning", "electrified"),
        "expected": (
            "Preserve the ancient material term as electrum unless evidence "
            "supports a more precise alloy or amber rendering."
        ),
    },
    {
        "source_phrase": "concaluit cor meum",
        "wrong_renderings": ("grew cold",),
        "expected": "Render concaluit as grew hot, burned, or grew fervent.",
    },
    {
        "source_phrase": "silui a bonis",
        "wrong_renderings": ("among the good", "with the good"),
        "expected": "Preserve a bonis as separation: from good things.",
    },
    {
        "source_phrase": "quatuor plagas mundi",
        "wrong_renderings": ("four corners of the world",),
        "expected": "Do not replace plagas with corners; retain plagues, blows, or an explicitly justified contextual sense.",
    },
)


def _roman_to_int(value: str) -> int:
    numerals = {
        "I": 1,
        "V": 5,
        "X": 10,
        "L": 50,
        "C": 100,
        "D": 500,
        "M": 1000,
    }
    total = 0
    previous = 0
    for char in reversed(value.upper()):
        current = numerals[char]
        total += -current if current < previous else current
        previous = max(previous, current)
    return total


class ScriptureVerifier(Protocol):
    def lookup_reference(self, reference: str, *, limit: int = 8) -> dict[str, Any]: ...


def _finding(
    check: str,
    status: str,
    severity: str,
    message: str,
    *,
    evidence: dict[str, Any],
) -> dict[str, Any]:
    return {
        "check": check,
        "status": status,
        "severity": severity,
        "message": message,
        "evidence": evidence,
        "provenance": {
            "kind": "deterministic_check",
            "implementation": f"checks.{check}/v{CHECKS_VERSION}",
        },
    }


def _translation_checks(latin: str, english: str, witness: str) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    latin_words = [word.casefold() for word in WORD_RE.findall(latin)]
    english_words = [word.casefold() for word in WORD_RE.findall(english)]
    english_set = set(english_words) | set(ARABIC_RE.findall(english))

    digits = ARABIC_RE.findall(latin)
    missing_digits = [value for value in digits if value not in ARABIC_RE.findall(english)]
    findings.append(
        _finding(
            "numbers",
            "warning" if missing_digits else "pass",
            "high" if missing_digits else "low",
            f"{witness}: explicit source digits not visible in English" if missing_digits else f"{witness}: explicit digits accounted for",
            evidence={"source_digits": digits, "missing": missing_digits, "witness": witness},
        )
    )

    latin_folded = " ".join(latin_words)
    english_casefolded = english.casefold()
    for trap in CURATED_TRANSLATION_TRAPS:
        source_phrase = str(trap["source_phrase"])
        if source_phrase not in latin_folded:
            continue
        for wrong in trap["wrong_renderings"]:
            wrong_text = str(wrong)
            if wrong_text not in english_casefolded:
                continue
            findings.append(
                _finding(
                    "known_translation_trap",
                    "warning",
                    "high",
                    f"{witness}: verified wrong rendering remains for {source_phrase!r}",
                    evidence={
                        "source_phrase": source_phrase,
                        "matched_wrong_rendering": wrong_text,
                        "expected": trap["expected"],
                        "witness": witness,
                    },
                )
            )
            break

    source_romans = ROMAN_RE.findall(latin)
    english_romans = {item.upper() for item in ROMAN_RE.findall(english)}
    english_digits = set(ARABIC_RE.findall(english))
    missing_romans = [
        {
            "source": value,
            "arabic": _roman_to_int(value),
        }
        for value in source_romans
        if value.upper() not in english_romans
        and str(_roman_to_int(value)) not in english_digits
    ]
    findings.append(
        _finding(
            "roman_numerals",
            "warning" if missing_romans else "pass",
            "high" if missing_romans else "low",
            (
                f"{witness}: explicit source Roman numeral/date is not "
                "visible in English"
                if missing_romans
                else f"{witness}: explicit Roman numerals/dates accounted for"
            ),
            evidence={
                "source_roman_numerals": source_romans,
                "missing": missing_romans,
                "witness": witness,
            },
        )
    )

    latin_number_forms = set(latin_words)
    latin_number_forms.update(
        word[:-3]
        for word in latin_words
        if word.endswith("que") and len(word) > 3
    )
    english_number_values = {
        ENGLISH_CARDINAL_VALUES[word]
        for word in english_words
        if word in ENGLISH_CARDINAL_VALUES
    }
    english_number_values.update(int(value) for value in ARABIC_RE.findall(english))
    composite_equivalents = []
    composite_covered_forms: set[str] = set()
    for index in range(len(latin_words) - 2):
        left, conjunction, right = latin_words[index : index + 3]
        if (
            conjunction == "et"
            and left in LATIN_CARDINAL_VALUES
            and right in LATIN_CARDINAL_VALUES
        ):
            total = LATIN_CARDINAL_VALUES[left] + LATIN_CARDINAL_VALUES[right]
            if total in english_number_values:
                composite_covered_forms.update({left, right})
                composite_equivalents.append(
                    {
                        "latin": f"{left} et {right}",
                        "value": total,
                    }
                )
    missing_concepts = []
    for latin_form, equivalents in LATIN_NUMBER_CONCEPTS.items():
        if (
            latin_form in latin_number_forms
            and latin_form not in composite_covered_forms
            and not (equivalents & english_set)
        ):
            missing_concepts.append({"latin": latin_form, "expected_any": sorted(equivalents)})
    if missing_concepts:
        findings.append(
            _finding(
                "number_words",
                "warning",
                "medium",
                f"{witness}: Latin number concepts lack an obvious English counterpart",
                evidence={
                    "missing": missing_concepts,
                    "composite_equivalents": composite_equivalents,
                    "witness": witness,
                },
            )
        )
    elif composite_equivalents:
        findings.append(
            _finding(
                "number_words",
                "pass",
                "low",
                f"{witness}: additive Latin number phrase is represented by its English total",
                evidence={
                    "missing": [],
                    "composite_equivalents": composite_equivalents,
                    "witness": witness,
                },
            )
        )

    latin_neg = [word for word in latin_words if word in LATIN_NEGATIONS]
    english_neg = [word for word in english_words if word in ENGLISH_NEGATIONS]
    findings.append(
        _finding(
            "negation",
            "warning" if latin_neg and not english_neg else "pass",
            "high" if latin_neg and not english_neg else "low",
            f"{witness}: explicit Latin negation may be absent" if latin_neg and not english_neg else f"{witness}: no obvious missing negation",
            evidence={"latin_negations": latin_neg, "english_negations": english_neg, "witness": witness},
        )
    )

    latin_word_count = max(1, len(latin_words))
    ratio = len(english_words) / latin_word_count
    findings.append(
        _finding(
            "coverage_signal",
            "warning" if ratio < 0.28 else "pass",
            "high" if ratio < 0.28 else "low",
            f"{witness}: unusually short English may omit source clauses" if ratio < 0.28 else f"{witness}: length signal does not show an obvious large omission",
            evidence={"latin_words": latin_word_count, "english_words": len(english_words), "ratio": round(ratio, 3), "witness": witness},
        )
    )

    capitalized = []
    for index, token in enumerate(WORD_RE.findall(latin)):
        if token[:1].isupper() and index > 0 and len(token) > 2:
            capitalized.append(token)
    english_folded = english.casefold().replace("j", "i").replace("v", "u")
    curated_name_mismatches = []
    for source_form, expected in CURATED_PROPER_NAME_EQUIVALENTS.items():
        if source_form in latin_words and not (expected & set(english_words)):
            curated_name_mismatches.append(
                {
                    "source_form": source_form,
                    "expected_any": sorted(expected),
                }
            )
    if curated_name_mismatches:
        findings.append(
            _finding(
                "proper_names",
                "warning",
                "high",
                f"{witness}: curated source name lacks its expected English form",
                evidence={
                    "curated_mismatches": curated_name_mismatches,
                    "witness": witness,
                },
            )
        )
    missing_names = []
    for name in dict.fromkeys(capitalized):
        if name.casefold() in CURATED_PROPER_NAME_EQUIVALENTS:
            continue
        stem = name.casefold().replace("j", "i").replace("v", "u")[:5]
        if stem and stem not in english_folded:
            missing_names.append(name)
    if missing_names:
        findings.append(
            _finding(
                "proper_names",
                "warning",
                "medium",
                f"{witness}: capitalized source forms lack an obvious English name stem",
                evidence={"candidates": capitalized, "missing": missing_names, "witness": witness},
            )
        )
    return findings


def run_deterministic_checks(
    chunk: dict[str, Any],
    witness_a: str,
    witness_b: str,
    *,
    scripture: ScriptureVerifier | None = None,
    witness_gate: dict[str, Any] | None = None,
) -> dict[str, Any]:
    findings = _translation_checks(chunk["target_latin"], witness_a, "witness_a")
    findings.extend(_translation_checks(chunk["target_latin"], witness_b, "witness_b"))
    valid_witnesses = set((witness_gate or {}).get("valid_witnesses") or [])
    quorum_recorded = bool(witness_gate)
    for finding in findings:
        evidence = finding.get("evidence")
        witness = evidence.get("witness") if isinstance(evidence, dict) else None
        if witness not in {"witness_a", "witness_b"}:
            continue
        eligible = not quorum_recorded or witness in valid_witnesses
        evidence["witness_validation_role"] = (
            "eligible_proposal" if eligible else "invalid_witness_clue_not_evidence"
        )
        evidence["may_corroborate"] = eligible

    target_spans = [span for span in chunk.get("source_spans", []) if span.get("role") == "target"]
    span_pages = list(
        dict.fromkeys(span.get("page") for span in target_spans if span.get("page"))
    )
    marker_pages = [marker.get("page") for marker in chunk.get("page_markers", [])]
    pages_ok = span_pages == marker_pages == chunk.get("source", {}).get("pages", [])
    findings.append(
        _finding(
            "page_marker_integrity",
            "pass" if pages_ok else "failure",
            "low" if pages_ok else "high",
            "Target page markers and source spans agree" if pages_ok else "Target page marker provenance is inconsistent",
            evidence={"span_pages": span_pages, "marker_pages": marker_pages, "source_pages": chunk.get("source", {}).get("pages", [])},
        )
    )

    editorial = [item for item in chunk.get("annotations", []) if item.get("type") == "editorial_reference"]
    missing_links = [item.get("annotation_id") for item in editorial if not item.get("reference")]
    offsets_bad = [
        item.get("annotation_id")
        for item in chunk.get("annotations", [])
        if not (0 <= int(item.get("offset", -1)) <= len(chunk["target_latin"]))
    ]
    findings.append(
        _finding(
            "note_integrity",
            "failure" if offsets_bad else ("warning" if missing_links else "pass"),
            "high" if offsets_bad else ("medium" if missing_links else "low"),
            "Editorial notes preserve valid target offsets and definitions" if not offsets_bad and not missing_links else "One or more editorial notes are unlinked or outside target offsets",
            evidence={"note_count": len(editorial), "missing_definitions": missing_links, "invalid_offsets": offsets_bad},
        )
    )

    scripture_results = []
    for item in editorial:
        reference = item.get("reference")
        if not reference:
            continue
        if scripture is None:
            scripture_results.append({"annotation_id": item.get("annotation_id"), "reference": reference, "status": "unavailable"})
        else:
            result = scripture.lookup_reference(reference, limit=2)
            scripture_results.append({"annotation_id": item.get("annotation_id"), "reference": reference, "status": "verified" if result.get("source_annotation_verified") else "not_found", "parsed": result.get("parsed", [])})
    if any(item["status"] == "not_found" for item in scripture_results):
        status, severity = "warning", "medium"
    elif any(item["status"] == "unavailable" for item in scripture_results):
        status, severity = "unavailable", "medium"
    else:
        status, severity = "pass", "low"
    findings.append(
        _finding(
            "scripture_reference",
            status,
            severity,
            "Source annotation references checked independently against the local Vulgate",
            evidence={"results": scripture_results, "source_annotation_verified": status == "pass", "textual_match_verified": False},
        )
    )
    return {
        "summary": {
            "pass": sum(1 for item in findings if item["status"] == "pass"),
            "warning": sum(1 for item in findings if item["status"] == "warning"),
            "failure": sum(1 for item in findings if item["status"] == "failure"),
            "unavailable": sum(1 for item in findings if item["status"] == "unavailable"),
        },
        "findings": findings,
        "witness_quorum": {
            "quorum": (witness_gate or {}).get("quorum"),
            "mode": (witness_gate or {}).get("mode"),
            "valid_witnesses": sorted(valid_witnesses),
            "invalid_witnesses": (witness_gate or {}).get("invalid_witnesses", []),
            "invalid_witness_output_is_evidence": False,
        },
        "limits": "These checks surface cheap signals; they do not prove semantic correctness.",
    }


def run_final_draft_checks(
    chunk: dict[str, Any],
    final_draft: str,
    *,
    applied_edits: list[dict[str, Any]] | None = None,
    base_witness_text: str | None = None,
    edit_budget: dict[str, Any] | None = None,
) -> dict[str, Any]:
    findings = _translation_checks(
        chunk["target_latin"], final_draft, "final_draft"
    )
    source_matches = list(WORD_RE.finditer(chunk["target_latin"]))
    final_matches = list(WORD_RE.finditer(final_draft))
    source_words = [match.group(0).casefold() for match in source_matches]
    final_words = [match.group(0).casefold() for match in final_matches]
    blocks = SequenceMatcher(
        None, source_words, final_words, autojunk=False
    ).get_matching_blocks()
    longest = max(blocks, key=lambda block: block.size, default=None)
    copied_count = longest.size if longest is not None else 0
    source_phrase = (
        chunk["target_latin"][
            source_matches[longest.a].start() : source_matches[
                longest.a + longest.size - 1
            ].end()
        ]
        if longest is not None and longest.size
        else ""
    )
    final_phrase = (
        final_draft[
            final_matches[longest.b].start() : final_matches[
                longest.b + longest.size - 1
            ].end()
        ]
        if longest is not None and longest.size
        else ""
    )
    source_copy_blocked = copied_count > MAX_SOURCE_COPY_WORDS
    findings.append(
        _finding(
            "source_latin_copy",
            "warning" if source_copy_blocked else "pass",
            "high" if source_copy_blocked else "low",
            (
                "final_draft: a long contiguous target-Latin span remains untranslated"
                if source_copy_blocked
                else "final_draft: no long contiguous target-Latin span was copied"
            ),
            evidence={
                "copied_word_count": copied_count,
                "maximum_automatic_words": MAX_SOURCE_COPY_WORDS,
                "source_phrase": source_phrase,
                "final_phrase": final_phrase,
                "witness": "final_draft",
            },
        )
    )

    edit_budget = edit_budget or {}
    per_edit_limit = int(
        edit_budget.get("max_words_per_edit", MAX_AUTOMATIC_EDIT_WORDS)
    )
    cumulative_limit = int(edit_budget.get("max_cumulative_words", 96))
    ratio_limit = float(edit_budget.get("max_base_replacement_ratio", 0.25))
    oversized_edits = []
    cumulative_words = 0
    replaced_base_words = 0
    for index, edit in enumerate(applied_edits or []):
        if not isinstance(edit, dict):
            continue
        old_words = len(WORD_RE.findall(str(edit.get("old") or "")))
        new_words = len(WORD_RE.findall(str(edit.get("new") or "")))
        cumulative_words += max(old_words, new_words)
        replaced_base_words += old_words
        if max(old_words, new_words) > per_edit_limit:
            oversized_edits.append(
                {
                    "edit_index": index,
                    "old_word_count": old_words,
                    "new_word_count": new_words,
                    "reason": edit.get("reason", ""),
                }
            )
    findings.append(
        _finding(
            "adjudicator_edit_scope",
            "warning" if oversized_edits else "pass",
            "high" if oversized_edits else "low",
            (
                "final_draft: an adjudicator edit replaces too much witness text for automatic acceptance"
                if oversized_edits
                else "final_draft: adjudicator edits remain bounded corrections to the selected witness"
            ),
            evidence={
                "maximum_automatic_edit_words": per_edit_limit,
                "oversized_edits": oversized_edits,
                "witness": "final_draft",
            },
        )
    )

    base_words = len(WORD_RE.findall(base_witness_text or ""))
    replacement_ratio = (
        replaced_base_words / base_words if base_words else (1.0 if replaced_base_words else 0.0)
    )
    cumulative_blocked = (
        cumulative_words > cumulative_limit or replacement_ratio > ratio_limit
    )
    findings.append(
        _finding(
            "adjudicator_cumulative_edit_scope",
            "warning" if cumulative_blocked else "pass",
            "high" if cumulative_blocked else "low",
            (
                "final_draft: cumulative adjudicator edits exceed the safe automatic-correction scope"
                if cumulative_blocked
                else "final_draft: cumulative adjudicator edits remain a bounded correction"
            ),
            evidence={
                "cumulative_edit_words": cumulative_words,
                "maximum_cumulative_words": cumulative_limit,
                "replaced_base_words": replaced_base_words,
                "base_witness_words": base_words,
                "base_replacement_ratio": round(replacement_ratio, 4),
                "maximum_base_replacement_ratio": ratio_limit,
                "witness": "final_draft",
            },
        )
    )
    return {
        "policy_version": FINAL_CHECKS_VERSION,
        "summary": {
            "pass": sum(1 for item in findings if item["status"] == "pass"),
            "warning": sum(
                1 for item in findings if item["status"] == "warning"
            ),
            "failure": sum(
                1 for item in findings if item["status"] == "failure"
            ),
        },
        "findings": findings,
        "limits": (
            "Post-adjudication checks block known deterministic hazards; "
            "they do not prove full semantic correctness."
        ),
    }
