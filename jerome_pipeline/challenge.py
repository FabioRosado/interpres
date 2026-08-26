from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

from glossary import WhitakersWordsBackend, analyze_chunk, flags_to_json

from .cache import canonical_digest
from .checks import run_deterministic_checks
from .config import PipelineConfig
from .pipeline import EvidenceFirstPipeline
from .providers import ModelProvider, ProviderCallError, ProviderResponse
from .schemas import parse_json_response


CHALLENGE_ERROR_TYPES = {
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
    "other",
}


class ChallengeCandidateProvider:
    """Inject the same frozen candidate into both witness slots.

    All other calls go through the configured provider. This deliberately
    creates witness agreement around the candidate under test, so the staged
    harness measures whether later review catches errors without treating
    agreement as proof.
    """

    def __init__(self, base: ModelProvider, candidate_english: str):
        self.base = base
        self.candidate_english = candidate_english

    def chat(
        self,
        spec,
        prompt: str,
        *,
        json_mode: bool,
        response_schema=None,
    ) -> ProviderResponse:
        if spec.role not in {"witness_a", "witness_b"}:
            return self.base.chat(
                spec,
                prompt,
                json_mode=json_mode,
                response_schema=response_schema,
            )
        return ProviderResponse(
            content=self.candidate_english,
            seconds=0.0,
            used_model={
                "provider": "challenge_fixture",
                "model": "frozen_candidate_under_test",
                "role": spec.role,
            },
            attempts=[
                {
                    "provider": "challenge_fixture",
                    "model": "frozen_candidate_under_test",
                    "outcome": "complete",
                }
            ],
            fallback_used=False,
            metadata={"candidate_injection": True},
        )


def load_challenges(path: Path) -> list[dict[str, Any]]:
    cases = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            case = json.loads(line)
            if not isinstance(case, dict):
                raise ValueError(f"Challenge {path}:{line_number} must be an object")
            for field in ("case_id", "latin", "candidate_english", "expected_error_types", "clean"):
                if field not in case:
                    raise ValueError(f"Challenge {path}:{line_number} missing {field}")
            cases.append(case)
    return cases


def apply_mutation(english: str, mutation: str, args: dict[str, Any] | None = None) -> str:
    """Deterministic synthetic corruptions for curated challenge authoring."""
    args = args or {}
    if mutation == "remove_negation":
        return re.sub(r"\b(?:not|never|no|neither|nor)\b\s*", "", english, count=1, flags=re.I)
    if mutation == "alter_number":
        replacements = {"three": "four", "four": "five", "thirty": "twenty", "3": "4", "4": "5", "30": "20"}
        for source, target in replacements.items():
            changed, count = re.subn(rf"\b{re.escape(source)}\b", target, english, count=1, flags=re.I)
            if count:
                return changed
        raise ValueError("No supported number found for alteration")
    if mutation == "swap_subject_object":
        subject, obj = args.get("subject"), args.get("object")
        if not subject or not obj:
            raise ValueError("swap_subject_object requires subject and object args")
        return english.replace(subject, "__OBJECT__", 1).replace(obj, subject, 1).replace("__OBJECT__", obj, 1)
    if mutation in {"plausible_wrong_lexical_sense", "attachment", "alter_proper_name"}:
        source, target = args.get("source"), args.get("target")
        if not source or target is None:
            raise ValueError(f"{mutation} requires source and target args")
        return english.replace(source, target, 1)
    if mutation == "omit_words":
        source = args.get("source")
        if not source:
            raise ValueError("omit_words requires source arg")
        return english.replace(source, "", 1)
    if mutation == "unsupported_certainty":
        return "Certainly and without ambiguity, " + english[:1].lower() + english[1:]
    if mutation == "invent_scripture_allusion":
        return english.rstrip(". ") + ", as Psalm 23 explicitly foretells."
    raise ValueError(f"Unsupported mutation: {mutation}")


def _review_prompt(case: dict[str, Any], lexical: list[dict[str, Any]], checks: dict[str, Any]) -> str:
    # Deliberately omit mutation/clean/expected labels from the reviewing model.
    return f"""Adversarially review one proposed English translation against its Latin.
The candidate may be clean or may contain subtle errors; you are not told
which. Do not manufacture findings. Agreement with your memory is not proof.
Use visible Latin and supplied deterministic signals only. External claims,
including Scripture identifications, must be flagged as unverified rather than
asserted from memory.

Return VALID JSON ONLY:
{{"status":"no_issue_found|issue_found|unresolved","findings":[{{"latin":"exact substring","english":"candidate wording","type":"negation|subject_object|number|lexical|attachment|omission|addition|unsupported_certainty|scripture|proper_name|other","severity":"low|medium|high","reason":"grounded visible reason"}}]}}

LATIN:
<<<
{case['latin']}

CANDIDATE ENGLISH:
<<<
{case['candidate_english']}

DETERMINISTIC LEXICAL FLAGS:
<<<
{json.dumps(lexical, ensure_ascii=False, indent=2)}

DETERMINISTIC CHECKS:
<<<
{json.dumps(checks, ensure_ascii=False, indent=2)}
"""


def _validate_review(value: dict[str, Any]) -> dict[str, Any]:
    if value.get("status") not in {"no_issue_found", "issue_found", "unresolved"}:
        raise ValueError("invalid challenge status")
    if not isinstance(value.get("findings"), list):
        raise ValueError("challenge findings must be a list")
    for finding in value["findings"]:
        if finding.get("type") not in CHALLENGE_ERROR_TYPES:
            raise ValueError(f"invalid challenge finding type {finding.get('type')!r}")
    return value


def _deterministic_detections(checks: dict[str, Any], lexical: list[dict[str, Any]]) -> list[str]:
    mapping = {
        "numbers": "number",
        "number_words": "number",
        "roman_numerals": "number",
        "negation": "negation",
        "proper_names": "proper_name",
        "coverage_signal": "omission",
    }
    detected = {
        mapping[item["check"]]
        for item in checks.get("findings", [])
        if item.get("status") in {"warning", "failure"} and item.get("check") in mapping
    }
    if any(flag.get("flag_type") == "known_trap" for flag in lexical):
        detected.add("lexical")
    return sorted(detected)


def _challenge_chunk(case: dict[str, Any]) -> dict[str, Any]:
    source = case.get("source") or {}
    page = str(source.get("page", "challenge"))
    source_unit_id = f"challenge-{case['case_id']}"
    latin = case["latin"]
    fingerprint = canonical_digest(
        {
            "case_id": case["case_id"],
            "latin": latin,
            "candidate_english": case["candidate_english"],
        }
    )
    return {
        "chunk_id": f"challenge-{case['case_id']}",
        "id": f"challenge-{case['case_id']}",
        "book": source.get("book"),
        "target_latin": latin,
        "context_before": "",
        "context_after": "",
        "source_fingerprint": fingerprint,
        "source": {
            "kind": source.get("kind", "challenge_case"),
            "pages": [page],
            "source_unit_ids": [source_unit_id],
        },
        "source_units": [source_unit_id],
        "source_spans": [
            {
                "role": "target",
                "source_unit_id": source_unit_id,
                "page": page,
                "clean_start": 0,
                "clean_end": len(latin),
            }
        ],
        "page_markers": [{"page": page, "raw": f"[page {page}]"}],
        "annotations": [],
    }


def _challenge_pipeline_config(config: PipelineConfig) -> PipelineConfig:
    data = copy.deepcopy(config.data)
    data.setdefault("paths", {})["cache"] = str(
        config.path_value("artifacts") / "challenge-cache"
    )
    return PipelineConfig(path=config.path, root=config.root, data=data)


def _pipeline_detections(
    records: dict[str, dict[str, Any]], deterministic: list[str]
) -> tuple[list[str], dict[str, str], dict[str, list[str]]]:
    ordered: list[tuple[str, list[str]]] = [("deterministic", deterministic)]
    for stage, field in (
        ("prosecutor_initial", "challenges"),
        ("prosecutor_grounded", "challenges"),
        ("adjudicator_initial", "findings"),
        ("adjudicator", "findings"),
    ):
        output = records.get(stage, {}).get("output") or {}
        detected = sorted(
            {
                str(item.get("type"))
                for item in output.get(field, [])
                if item.get("type") in CHALLENGE_ERROR_TYPES
            }
        )
        ordered.append((stage, detected))
    first: dict[str, str] = {}
    by_stage: dict[str, list[str]] = {}
    for stage, detected in ordered:
        by_stage[stage] = detected
        for error_type in detected:
            first.setdefault(error_type, stage)
    return sorted(first), first, by_stage


def run_challenges(
    config: PipelineConfig,
    *,
    lexicon: WhitakersWordsBackend | None = None,
    provider: ModelProvider | None = None,
    deterministic_only: bool = False,
    full_pipeline: bool = False,
) -> list[dict[str, Any]]:
    if deterministic_only and full_pipeline:
        raise ValueError("deterministic_only and full_pipeline are mutually exclusive")
    backend = lexicon or WhitakersWordsBackend()
    model_provider = provider or ModelProvider(config)
    cases = load_challenges(config.path_value("challenge_set"))
    results = []
    for case in cases:
        lexical = flags_to_json(analyze_chunk(case["latin"], backend))
        chunk = {
            "target_latin": case["latin"],
            "source_spans": [],
            "page_markers": [],
            "source": {"pages": []},
            "annotations": [],
        }
        checks = run_deterministic_checks(
            chunk, case["candidate_english"], case["candidate_english"], scripture=None
        )
        deterministic = _deterministic_detections(checks, lexical)
        reviewer: dict[str, Any] | None = None
        reviewer_error = None
        pipeline_result: dict[str, Any] | None = None
        pipeline_stage_detections: dict[str, list[str]] = {}
        first_detected = {error: "deterministic" for error in deterministic}
        if full_pipeline:
            challenge_config = _challenge_pipeline_config(config)
            challenge_provider = ChallengeCandidateProvider(
                model_provider, case["candidate_english"]
            )
            pipeline = EvidenceFirstPipeline(
                challenge_config,
                lexicon=backend,
                provider=challenge_provider,
            )
            pipeline_result = pipeline.run_chunk(_challenge_chunk(case))
            records = pipeline_result["records"]
            check_output = records.get("deterministic_checks", {}).get("output")
            if check_output:
                deterministic = _deterministic_detections(check_output, lexical)
            all_detections, first_detected, pipeline_stage_detections = (
                _pipeline_detections(records, deterministic)
            )
        elif not deterministic_only:
            try:
                response = model_provider.chat(
                    config.model("prosecutor"),
                    _review_prompt(case, lexical, checks),
                    json_mode=True,
                )
                reviewer = _validate_review(parse_json_response(response.content))
                reviewer["model"] = response.used_model
                reviewer["provider_attempts"] = response.attempts
            except Exception as exc:
                reviewer_error = {"type": type(exc).__name__, "message": str(exc)}
                if isinstance(exc, ProviderCallError):
                    reviewer_error["attempts"] = exc.attempts
        if not full_pipeline:
            reviewer_types = sorted({item["type"] for item in (reviewer or {}).get("findings", [])})
            all_detections = sorted(set(deterministic) | set(reviewer_types))
            first_detected = {
                error: ("deterministic" if error in deterministic else "reviewer")
                for error in all_detections
            }
        expected = set(case["expected_error_types"])
        results.append(
            {
                "case_id": case["case_id"],
                "clean": case["clean"],
                "mutation": case.get("mutation"),
                "expected_error_types": sorted(expected),
                "deterministic_detections": deterministic,
                "reviewer": reviewer,
                "reviewer_error": reviewer_error,
                "evaluation_mode": (
                    "full_pipeline"
                    if full_pipeline
                    else "deterministic_only"
                    if deterministic_only
                    else "reviewer"
                ),
                "pipeline_status": (
                    pipeline_result.get("status") if pipeline_result else None
                ),
                "pipeline_completed_stages": (
                    pipeline_result.get("completed_stages", [])
                    if pipeline_result
                    else []
                ),
                "pipeline_failed_stage": (
                    pipeline_result.get("failed_stage") if pipeline_result else None
                ),
                "pipeline_error": (
                    pipeline_result.get("error") if pipeline_result else None
                ),
                "pipeline_stage_detections": pipeline_stage_detections,
                "candidate_injected_into": (
                    ["witness_a", "witness_b"] if full_pipeline else []
                ),
                "detected_error_types": all_detections,
                "planted_detected": sorted(expected & set(all_detections)),
                "planted_missed": sorted(expected - set(all_detections)),
                "unexpected_flags": sorted(set(all_detections) - expected),
                "stage_first_detected": {
                    error: first_detected[error]
                    for error in sorted(expected & set(all_detections))
                },
            }
        )
    path = config.path_value("challenge_results")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for result in results:
            handle.write(json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n")
    return results


def challenge_metrics(results: list[dict[str, Any]]) -> dict[str, Any]:
    planted = sum(len(item["expected_error_types"]) for item in results if not item["clean"])
    detected = sum(len(item["planted_detected"]) for item in results)
    missed = sum(len(item["planted_missed"]) for item in results)
    clean = [item for item in results if item["clean"]]
    false_positive_cases = sum(bool(item["detected_error_types"]) for item in clean)
    reviewer_available = [item for item in results if item.get("reviewer")]
    unresolved = sum(item["reviewer"].get("status") == "unresolved" for item in reviewer_available)
    return {
        "cases": len(results),
        "planted_errors": planted,
        "planted_errors_detected": detected,
        "planted_errors_missed": missed,
        "detection_rate": round(detected / planted, 4) if planted else None,
        "clean_cases": len(clean),
        "false_positive_clean_cases": false_positive_cases,
        "reviewer_completed_cases": len(reviewer_available),
        "unresolved_rate": round(unresolved / len(reviewer_available), 4) if reviewer_available else None,
        "reviewer_failures": sum(bool(item.get("reviewer_error")) for item in results),
        "full_pipeline_cases": sum(
            item.get("evaluation_mode") == "full_pipeline" for item in results
        ),
        "full_pipeline_completed_cases": sum(
            item.get("evaluation_mode") == "full_pipeline"
            and item.get("pipeline_status") != "incomplete"
            for item in results
        ),
        "full_pipeline_failures": sum(
            item.get("evaluation_mode") == "full_pipeline"
            and item.get("pipeline_status") == "incomplete"
            for item in results
        ),
    }
