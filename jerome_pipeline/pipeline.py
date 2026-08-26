from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable

from glossary import (
    WhitakersWordsBackend,
    analyze_chunk,
    analyze_morphology,
    flags_to_json,
)

from .cache import StageCache, canonical_digest, stage_record, utc_now
from .adjudication import assess_adjudication_evidence
from .checks import (
    CHECKS_VERSION,
    FINAL_CHECKS_VERSION,
    run_deterministic_checks,
    run_final_draft_checks,
)
from .config import ModelSpec, PipelineConfig
from .evidence import EvidenceService
from .editorial import EditorialMemoryIndex
from .prompts import (
    ADJUDICATOR_INPUT_BUDGET_POLICY_VERSION,
    budgeted_adjudicator_prompt,
    grounded_prosecutor_prompt,
    prosecutor_prompt,
    structural_prompt,
    witness_prompt,
)
from .providers import (
    OPENROUTER_CONTRACT_VERSION,
    ModelProvider,
    ProviderCallError,
    ProviderResponse,
)
from .schemas import (
    SchemaValidationError,
    adjudication_schema,
    enrich_adjudication_offsets,
    expand_adjudication_wire,
    expand_structural_wire,
    normalize_adjudication_status,
    parse_json_response,
    structural_wire_schema,
    validate_adjudication,
    validate_prosecutor,
)
from .source import split_sentences
from .witnesses import (
    WITNESS_QUORUM_POLICY_VERSION,
    WITNESS_VALIDATION_POLICY_VERSION,
    estimate_witness_output_budget,
    parse_plain_witness_proposal,
    validate_witness_record,
    witness_gate_receipt,
)


STAGE_ORDER = [
    "morphology",
    "structural_parse",
    "witness_a",
    "witness_b",
    "witness_a_validation",
    "witness_b_validation",
    "witness_gate",
    "deterministic_checks",
    "prosecutor_initial",
    "research_prosecutor",
    "prosecutor_grounded",
    "adjudicator_initial",
    "research_adjudicator",
    "adjudicator",
    "finalize",
]
FINALIZATION_POLICY_VERSION = 6


class ModelOutputError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        raw_response: str,
        response: ProviderResponse,
        category: str = "invalid_model_output",
    ):
        super().__init__(message)
        self.raw_response = raw_response
        self.response = response
        self.category = category


class StageIncomplete(RuntimeError):
    def __init__(self, record: dict[str, Any]):
        super().__init__(
            f"{record.get('stage')} is {record.get('status')}: "
            f"{(record.get('error') or {}).get('message', 'no completed evidence')}"
        )
        self.record = record


class EvidenceRoundError(RuntimeError):
    def __init__(self, output: dict[str, Any]):
        failures = [
            item
            for item in output.get("evidence", [])
            if item.get("status") == "error"
        ]
        super().__init__(
            f"{len(failures)} evidence request(s) failed during execution"
        )
        self.output = output
        self.failures = failures


class AdjudicatorInputBudgetError(RuntimeError):
    def __init__(self, receipt: dict[str, Any]):
        super().__init__(
            receipt.get("failure_reason")
            or "Adjudicator input exceeded its configured safe budget"
        )
        self.receipt = receipt


class WitnessGateError(RuntimeError):
    def __init__(self, receipt: dict[str, Any]):
        super().__init__(
            "Witness validation failed closed before prosecution: "
            + ", ".join(receipt.get("invalid_witnesses", []))
        )
        self.receipt = receipt


class WitnessOutputBudgetError(RuntimeError):
    def __init__(self, receipt: dict[str, Any]):
        super().__init__(
            receipt.get("failure_reason")
            or "Witness response cannot fit the configured completion budget"
        )
        self.receipt = receipt


@dataclass
class StageResult:
    record: dict[str, Any]
    cached: bool

    @property
    def output(self) -> Any:
        return self.record.get("output")


class EvidenceFirstPipeline:
    def __init__(
        self,
        config: PipelineConfig,
        *,
        lexicon: WhitakersWordsBackend | None = None,
        provider: ModelProvider | None = None,
        model_profile: str = "production",
    ):
        self.config = config
        self.cache = StageCache(config.path_value("cache"))
        self.lexicon = lexicon or WhitakersWordsBackend()
        self.provider = provider or ModelProvider(config)
        self.model_profile = model_profile
        self.adjudicator_input_budget = config.section(
            "adjudicator_input_budget"
        )
        evidence_config = config.section("evidence")
        self.research_round_limits: dict[str, int] = {}
        for role in ("prosecutor", "adjudicator"):
            key = f"{role}_research_rounds"
            rounds = int(evidence_config.get(key, 1))
            if rounds not in {0, 1}:
                raise ValueError(
                    f"evidence.{key} supports only 0 or 1 explicit, "
                    "independently cached round"
                )
            self.research_round_limits[role] = rounds
        self.evidence = EvidenceService.from_config(config, self.lexicon)
        self.editorial_memory = EditorialMemoryIndex(
            config.path_value("editorial_reviews")
        )

    def _model(self, role: str) -> ModelSpec:
        return self.config.model(role, profile=self.model_profile)

    def _structural_model(self, chunk: dict[str, Any]) -> ModelSpec:
        spec = self._model("structural_parser")
        if self.model_profile != "production":
            return spec
        policy = self.config.section("structural_output_budget")
        threshold = int(policy.get("large_sentence_threshold", 0))
        large_limit = int(policy.get("large_max_output_tokens", 0))
        sentence_count = len(split_sentences(str(chunk.get("target_latin") or "")))
        if (
            threshold > 0
            and sentence_count >= threshold
            and large_limit > spec.max_output_tokens
        ):
            return replace(spec, max_output_tokens=large_limit)
        return spec

    @staticmethod
    def _require_successful_evidence_round(
        output: dict[str, Any],
    ) -> dict[str, Any]:
        if any(
            item.get("status") == "error"
            for item in output.get("evidence", [])
        ):
            raise EvidenceRoundError(output)
        return output

    def _stage(
        self,
        *,
        stage: str,
        chunk: dict[str, Any],
        inputs: Any,
        dependencies: list[dict[str, Any]],
        operation: Callable[[], tuple[Any, str | None, dict[str, Any] | None, list[dict[str, Any]], list[dict[str, Any]]]],
        model: ModelSpec | None = None,
        force: bool = False,
        retry_failed: bool = False,
        recover_failed: Callable[
            [dict[str, Any]],
            tuple[
                Any,
                str | None,
                dict[str, Any] | None,
                list[dict[str, Any]],
                list[dict[str, Any]],
            ]
            | None,
        ]
        | None = None,
    ) -> StageResult:
        model_identity = model.cache_identity() if model else None
        if model_identity is not None and model.provider == "openrouter":
            model_identity["provider_contract_version"] = (
                OPENROUTER_CONTRACT_VERSION
            )
        cache_key, material = self.cache.key(
            stage=stage,
            chunk=chunk,
            pipeline_version=self.config.pipeline_version,
            schema_version=self.config.schema_version,
            prompt_version=self.config.prompt_version,
            inputs=inputs,
            dependencies=dependencies,
            model=model_identity,
        )
        existing = self.cache.load(stage, chunk["chunk_id"], cache_key)
        if existing and not force:
            if existing.get("status") == "complete":
                return StageResult(existing, cached=True)
            if not retry_failed:
                raise StageIncomplete(existing)
            if recover_failed is not None:
                recovered = recover_failed(existing)
                if recovered is not None:
                    output, raw, actual_model, attempts, provenance = recovered
                    recovered_record = stage_record(
                        stage=stage,
                        chunk_id=chunk["chunk_id"],
                        cache_key=cache_key,
                        cache_material=material,
                        pipeline_version=self.config.pipeline_version,
                        schema_version=self.config.schema_version,
                        prompt_version=self.config.prompt_version,
                        status="complete",
                        started_at=utc_now(),
                        output=output,
                        raw_response=(
                            raw
                            if self.config.section("execution").get(
                                "save_raw_responses", True
                            )
                            else None
                        ),
                        model=actual_model or existing.get("model") or model_identity,
                        provider_attempts=attempts,
                        provenance=list(existing.get("provenance") or [])
                        + provenance,
                    )
                    recovered_record["execution_profile"] = self.model_profile
                    self.cache.save(recovered_record, preserve_existing=True)
                    return StageResult(recovered_record, cached=False)

        started = utc_now()
        try:
            output, raw, actual_model, attempts, provenance = operation()
            record = stage_record(
                stage=stage,
                chunk_id=chunk["chunk_id"],
                cache_key=cache_key,
                cache_material=material,
                pipeline_version=self.config.pipeline_version,
                schema_version=self.config.schema_version,
                prompt_version=self.config.prompt_version,
                status="complete",
                started_at=started,
                output=output,
                raw_response=raw if self.config.section("execution").get("save_raw_responses", True) else None,
                model=actual_model or model_identity,
                provider_attempts=attempts,
                provenance=provenance,
            )
        except ModelOutputError as exc:
            record = stage_record(
                stage=stage,
                chunk_id=chunk["chunk_id"],
                cache_key=cache_key,
                cache_material=material,
                pipeline_version=self.config.pipeline_version,
                schema_version=self.config.schema_version,
                prompt_version=self.config.prompt_version,
                status="failed",
                started_at=started,
                raw_response=exc.raw_response,
                error={"category": exc.category, "type": type(exc).__name__, "message": str(exc)},
                model=exc.response.used_model,
                provider_attempts=exc.response.attempts,
            )
        except ProviderCallError as exc:
            status = "unavailable" if exc.category == "provider_unavailable" else "failed"
            record = stage_record(
                stage=stage,
                chunk_id=chunk["chunk_id"],
                cache_key=cache_key,
                cache_material=material,
                pipeline_version=self.config.pipeline_version,
                schema_version=self.config.schema_version,
                prompt_version=self.config.prompt_version,
                status=status,
                started_at=started,
                error={"category": exc.category, "type": type(exc).__name__, "message": str(exc)},
                model=model_identity,
                provider_attempts=exc.attempts,
            )
        except EvidenceRoundError as exc:
            record = stage_record(
                stage=stage,
                chunk_id=chunk["chunk_id"],
                cache_key=cache_key,
                cache_material=material,
                pipeline_version=self.config.pipeline_version,
                schema_version=self.config.schema_version,
                prompt_version=self.config.prompt_version,
                status="failed",
                started_at=started,
                output=exc.output,
                error={
                    "category": "evidence_retrieval_failed",
                    "type": type(exc).__name__,
                    "message": str(exc),
                    "failed_evidence_ids": [
                        item.get("evidence_id") for item in exc.failures
                    ],
                },
                model=model_identity,
                provenance=[
                    {
                        "kind": "evidence_service",
                        "receipts_preserved": True,
                    }
                ],
            )
        except AdjudicatorInputBudgetError as exc:
            record = stage_record(
                stage=stage,
                chunk_id=chunk["chunk_id"],
                cache_key=cache_key,
                cache_material=material,
                pipeline_version=self.config.pipeline_version,
                schema_version=self.config.schema_version,
                prompt_version=self.config.prompt_version,
                status="failed",
                started_at=started,
                output={"input_budget": exc.receipt},
                error={
                    "category": "adjudicator_input_budget_exceeded",
                    "type": type(exc).__name__,
                    "message": str(exc),
                },
                model=model_identity,
                provider_attempts=[],
                provenance=[
                    {
                        "kind": "adjudicator_input_budget",
                        "policy_version": ADJUDICATOR_INPUT_BUDGET_POLICY_VERSION,
                        "provider_called": False,
                    }
                ],
            )
        except WitnessGateError as exc:
            record = stage_record(
                stage=stage,
                chunk_id=chunk["chunk_id"],
                cache_key=cache_key,
                cache_material=material,
                pipeline_version=self.config.pipeline_version,
                schema_version=self.config.schema_version,
                prompt_version=self.config.prompt_version,
                status="incomplete",
                started_at=started,
                output=exc.receipt,
                error={
                    "category": "witness_validation_failed",
                    "type": type(exc).__name__,
                    "message": str(exc),
                },
                model=model_identity,
                provider_attempts=[],
                provenance=[
                    {
                        "kind": "witness_validation_gate",
                        "policy_version": WITNESS_VALIDATION_POLICY_VERSION,
                        "quorum_policy_version": WITNESS_QUORUM_POLICY_VERSION,
                        "provider_called": False,
                    }
                ],
            )
        except WitnessOutputBudgetError as exc:
            record = stage_record(
                stage=stage,
                chunk_id=chunk["chunk_id"],
                cache_key=cache_key,
                cache_material=material,
                pipeline_version=self.config.pipeline_version,
                schema_version=self.config.schema_version,
                prompt_version=self.config.prompt_version,
                status="incomplete",
                started_at=started,
                output={"output_budget": exc.receipt},
                error={
                    "category": "witness_output_budget_exceeded",
                    "type": type(exc).__name__,
                    "message": str(exc),
                },
                model=model_identity,
                provider_attempts=[],
                provenance=[
                    {
                        "kind": "witness_output_budget",
                        "provider_called": False,
                    }
                ],
            )
        except Exception as exc:
            record = stage_record(
                stage=stage,
                chunk_id=chunk["chunk_id"],
                cache_key=cache_key,
                cache_material=material,
                pipeline_version=self.config.pipeline_version,
                schema_version=self.config.schema_version,
                prompt_version=self.config.prompt_version,
                status="failed",
                started_at=started,
                error={"category": "stage_failure", "type": type(exc).__name__, "message": str(exc)},
                model=model_identity,
            )
        record["execution_profile"] = self.model_profile
        self.cache.save(record, preserve_existing=True)
        if record["status"] != "complete":
            raise StageIncomplete(record)
        return StageResult(record, cached=False)

    def _structured_call(
        self,
        spec: ModelSpec,
        prompt: str,
        validator: Callable[[dict[str, Any]], dict[str, Any]],
        *,
        response_schema: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], str, dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
        response = self.provider.chat(
            spec,
            prompt,
            json_mode=True,
            response_schema=response_schema,
        )
        try:
            value = validator(parse_json_response(response.content))
        except (json.JSONDecodeError, SchemaValidationError, ValueError, TypeError) as exc:
            stopped_at_limit = (
                response.metadata.get("done_reason") == "length"
                or response.metadata.get("finish_reason") == "length"
            )
            diagnostic = ""
            category = "invalid_model_output"
            if stopped_at_limit:
                category = "output_truncated"
                count = response.metadata.get("eval_count")
                diagnostic = (
                    " Provider stopped at the configured output-token limit"
                    + (f" ({count} generated tokens)." if count is not None else ".")
                )
            raise ModelOutputError(
                f"Structured response failed validation: {exc}.{diagnostic}".rstrip(),
                raw_response=response.content,
                response=response,
                category=category,
            ) from exc
        return value, response.content, response.used_model, response.attempts, []

    @staticmethod
    def _recover_adjudication_output(
        record: dict[str, Any],
        witness_a: str,
        witness_b: str,
        allowed_base_witnesses: list[str] | None = None,
    ) -> tuple[
        Any,
        str | None,
        dict[str, Any] | None,
        list[dict[str, Any]],
        list[dict[str, Any]],
    ] | None:
        """Revalidate persisted JSON after deterministic contract improvements.

        This never repairs or rewrites model text. If the complete raw response
        still cannot pass the current exact-edit gate, the normal provider retry
        remains in force.
        """

        raw = record.get("raw_response")
        if not isinstance(raw, str) or not raw.strip():
            return None
        try:
            output = expand_adjudication_wire(
                parse_json_response(raw),
                witness_a,
                witness_b,
                allowed_base_witnesses=allowed_base_witnesses,
            )
        except (json.JSONDecodeError, SchemaValidationError, ValueError, TypeError, KeyError):
            return None
        return (
            output,
            raw,
            record.get("model"),
            list(record.get("provider_attempts") or []),
            [
                {
                    "kind": "deterministic_failed_output_revalidation",
                    "provider_called": False,
                    "original_status": record.get("status"),
                    "original_error": record.get("error"),
                }
            ],
        )

    @staticmethod
    def _finalization_inputs(
        adjudicator_record: dict[str, Any],
        prosecutor_evidence: list[dict[str, Any]],
        adjudicator_evidence: list[dict[str, Any]],
        witness_gate_record: dict[str, Any] | None = None,
        witness_a_record: dict[str, Any] | None = None,
        witness_b_record: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "adjudicator_key": adjudicator_record["cache_key"],
            "evidence_receipts": prosecutor_evidence + adjudicator_evidence,
            "witness_gate_key": (witness_gate_record or {}).get("cache_key"),
            "witness_gate": (witness_gate_record or {}).get("output"),
            "witness_a_key": (witness_a_record or {}).get("cache_key"),
            "witness_b_key": (witness_b_record or {}).get("cache_key"),
            "final_checks_version": FINAL_CHECKS_VERSION,
            "finalization_policy_version": FINALIZATION_POLICY_VERSION,
        }

    @staticmethod
    def _dependency_chain(
        records: list[dict[str, Any]], root: dict[str, Any]
    ) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
        """Resolve the exact cached lineage by key and dependency output hash."""

        index: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
        for record in records:
            stage = str(record.get("stage") or "")
            key = str(record.get("cache_key") or "")
            if not stage or not key:
                continue
            identity = (stage, key, canonical_digest(record.get("output")))
            index.setdefault(identity, []).append(record)
        selected: dict[str, dict[str, Any]] = {}
        missing: list[dict[str, Any]] = []
        pending = [root]
        seen: set[tuple[str, str, str]] = set()
        while pending:
            record = pending.pop()
            identity = (
                str(record.get("stage") or ""),
                str(record.get("cache_key") or ""),
                canonical_digest(record.get("output")),
            )
            if identity in seen:
                continue
            seen.add(identity)
            stage = identity[0]
            existing = selected.get(stage)
            if existing is None or str(record.get("finished_at", "")) > str(
                existing.get("finished_at", "")
            ):
                selected[stage] = record
            for dependency in (record.get("cache_material") or {}).get(
                "dependencies", []
            ):
                dependency_identity = (
                    str(dependency.get("stage") or ""),
                    str(dependency.get("cache_key") or ""),
                    str(dependency.get("output_digest") or ""),
                )
                candidates = index.get(dependency_identity, [])
                if not candidates:
                    missing.append(
                        {
                            "required_by_stage": stage,
                            "stage": dependency_identity[0],
                            "cache_key": dependency_identity[1],
                            "output_digest": dependency_identity[2],
                        }
                    )
                    continue
                pending.append(
                    max(candidates, key=lambda item: str(item.get("finished_at", "")))
                )
        return selected, missing

    @staticmethod
    def _witness_gate_for_lineage(
        records: list[dict[str, Any]], lineage: dict[str, dict[str, Any]]
    ) -> dict[str, Any] | None:
        """Find a local validation gate tied to the exact selected witnesses."""

        selected_validations: list[dict[str, Any]] = []
        for witness in ("witness_a", "witness_b"):
            source = lineage.get(witness)
            if source is None:
                return None
            expected = (
                witness,
                str(source.get("cache_key") or ""),
                canonical_digest(source.get("output")),
            )
            candidates = []
            for record in records:
                if record.get("stage") != f"{witness}_validation":
                    continue
                dependencies = (record.get("cache_material") or {}).get(
                    "dependencies", []
                )
                if any(
                    (
                        str(item.get("stage") or ""),
                        str(item.get("cache_key") or ""),
                        str(item.get("output_digest") or ""),
                    )
                    == expected
                    for item in dependencies
                ):
                    candidates.append(record)
            if not candidates:
                return None
            selected_validations.append(
                max(candidates, key=lambda item: str(item.get("finished_at", "")))
            )
        expected_dependencies = {
            (
                str(item.get("stage") or ""),
                str(item.get("cache_key") or ""),
                canonical_digest(item.get("output")),
            )
            for item in selected_validations
        }
        gates = []
        for record in records:
            if record.get("stage") != "witness_gate":
                continue
            dependencies = {
                (
                    str(item.get("stage") or ""),
                    str(item.get("cache_key") or ""),
                    str(item.get("output_digest") or ""),
                )
                for item in (record.get("cache_material") or {}).get(
                    "dependencies", []
                )
            }
            if dependencies == expected_dependencies:
                gates.append(record)
        return (
            max(gates, key=lambda item: str(item.get("finished_at", "")))
            if gates
            else None
        )

    @staticmethod
    def _finalize_output(
        chunk: dict[str, Any],
        original_decision: dict[str, Any],
        prosecutor_evidence: list[dict[str, Any]],
        adjudicator_evidence: list[dict[str, Any]],
        witness_gate: dict[str, Any] | None = None,
        witness_a: str | None = None,
        witness_b: str | None = None,
    ) -> dict[str, Any]:
        """Apply the deterministic acceptance policy to a model proposal."""

        decision = json.loads(json.dumps(original_decision, ensure_ascii=False))
        normalize_adjudication_status(decision)
        quorum = (witness_gate or {}).get("quorum") or (witness_gate or {}).get(
            "status", "not_recorded"
        )
        mode = (witness_gate or {}).get("mode")
        allowed_bases = list(
            (witness_gate or {}).get("allowed_base_witnesses") or []
        )
        degraded = mode == "degraded" or quorum in {
            "single_valid_a",
            "single_valid_b",
            "single_valid_witness",
        }
        automatic_acceptance_allowed = bool(
            (witness_gate or {}).get(
                "automatic_acceptance_allowed", quorum == "both_valid"
            )
        )
        decision["witness_quorum"] = quorum
        decision["automatic_acceptance_allowed"] = automatic_acceptance_allowed
        quorum_enforcement: dict[str, Any] = {
            "mode": mode or ("degraded" if degraded else "normal"),
            "quorum": quorum,
            "allowed_base_witnesses": allowed_bases,
            "automatic_acceptance_allowed": automatic_acceptance_allowed,
            "invalid_witness_output_is_evidence": False,
            "rejected_base_witness": None,
            "invalid_witness_citations": [],
            "downgraded_decision_basis_indices": [],
        }

        if degraded:
            decision["status"] = "human_review"
            decision.setdefault("human_review_requests", []).append(
                {
                    "latin": "",
                    "english": "",
                    "issue": (
                        "The chunk has a degraded single-valid witness quorum "
                        f"({quorum}); automatic acceptance is disabled."
                    ),
                    "action": (
                        "Review the valid-base draft and all substantive findings "
                        "before editorial acceptance."
                    ),
                }
            )
        elif not witness_gate or quorum != "both_valid":
            decision["status"] = "human_review"
            decision.setdefault("human_review_requests", []).append(
                {
                    "latin": "",
                    "english": "",
                    "issue": (
                        "The adjudicated draft lacks a normal both-valid witness "
                        f"quorum ({quorum})."
                    ),
                    "action": "Inspect the witness validation lineage before approval.",
                }
            )

        selected_base = (decision.get("coverage") or {}).get("base_witness")
        if degraded and selected_base not in allowed_bases:
            fallback_base = allowed_bases[0] if len(allowed_bases) == 1 else None
            fallback_text = (
                witness_a
                if fallback_base == "a"
                else witness_b if fallback_base == "b" else None
            )
            quorum_enforcement["rejected_base_witness"] = selected_base
            quorum_enforcement["fallback_base_witness"] = fallback_base
            if isinstance(fallback_text, str):
                decision["final_draft"] = fallback_text
                coverage = decision.setdefault("coverage", {})
                coverage["original_rejected_base_witness"] = selected_base
                coverage["base_witness"] = fallback_base
                coverage["applied_edits"] = []
                coverage["edit_application_mode"] = "quorum_fallback_no_model_edits"
            else:
                # A malformed historical lineage must not leave an invalid
                # witness as the displayed derived final.
                decision["final_draft"] = ""
                coverage = decision.setdefault("coverage", {})
                coverage["original_rejected_base_witness"] = selected_base
                coverage["base_witness"] = None
                coverage["applied_edits"] = []
                coverage["edit_application_mode"] = "quorum_fallback_unavailable"
            decision["status"] = "human_review"
            decision.setdefault("human_review_requests", []).append(
                {
                    "latin": "",
                    "english": "",
                    "issue": (
                        f"Adjudicator selected witness {selected_base!r}, which is "
                        f"not permitted by quorum {quorum}."
                    ),
                    "action": (
                        "Discard the model edits and review the sole valid witness "
                        f"{fallback_base!r} as the provisional base."
                    ),
                }
            )

        invalid_witnesses = set((witness_gate or {}).get("invalid_witnesses") or [])
        invalid_aliases = {
            alias
            for name in invalid_witnesses
            for alias in (
                name.casefold(),
                name.replace("_", " ").casefold(),
                name.removeprefix("witness_").casefold(),
            )
        }

        def cites_invalid(value: Any) -> bool:
            if not isinstance(value, str):
                return False
            folded = value.casefold()
            return any(
                alias in folded
                if alias.startswith("witness")
                else bool(re.search(rf"\bwitness[ _-]+{re.escape(alias)}\b", folded))
                for alias in invalid_aliases
            )

        for index, basis in enumerate(decision.get("decision_basis", [])):
            if not isinstance(basis, dict) or not cites_invalid(basis.get("claim")):
                continue
            quorum_enforcement["invalid_witness_citations"].append(
                {"location": f"decision_basis[{index}]", "witnesses": sorted(invalid_witnesses)}
            )
            basis["grade"] = "D"
            basis["evidence_ids"] = []
            quorum_enforcement["downgraded_decision_basis_indices"].append(index)
        for field, text_field in (
            ("findings", "reason"),
            ("findings", "resolution"),
            ("coverage.applied_edits", "reason"),
        ):
            items = (
                (decision.get("coverage") or {}).get("applied_edits", [])
                if field == "coverage.applied_edits"
                else decision.get(field, [])
            )
            for index, item in enumerate(items):
                if isinstance(item, dict) and cites_invalid(item.get(text_field)):
                    quorum_enforcement["invalid_witness_citations"].append(
                        {"location": f"{field}[{index}].{text_field}", "witnesses": sorted(invalid_witnesses)}
                    )
        if cites_invalid(decision.get("summary")):
            quorum_enforcement["invalid_witness_citations"].append(
                {"location": "summary", "witnesses": sorted(invalid_witnesses)}
            )
        if quorum_enforcement["invalid_witness_citations"]:
            decision["status"] = "human_review"
            decision.setdefault("human_review_requests", []).append(
                {
                    "latin": "",
                    "english": "",
                    "issue": "Adjudicator attempted to use an invalid witness as support.",
                    "action": (
                        "Ignore the invalid-witness citation and verify the claim "
                        "from visible Latin, deterministic checks, or retrieved evidence."
                    ),
                }
            )
        decision["quorum_enforcement"] = quorum_enforcement
        pending = decision.get("evidence_requests", [])
        if pending:
            decision["research_limit_reached"] = True
            if decision.get("status") in {"accepted", "corrected"}:
                decision["status"] = "human_review"
                decision.setdefault("human_review_requests", []).append(
                    {
                        "latin": "",
                        "english": "",
                        "issue": "Adjudicator requested evidence after the configured research limit",
                        "action": "Resolve the listed targeted evidence requests before approval",
                        "pending_evidence_requests": pending,
                    }
                )
        decision["evidence_requests"] = []
        final_checks = run_final_draft_checks(
            chunk,
            decision["final_draft"],
            applied_edits=decision.get("coverage", {}).get("applied_edits", []),
        )
        blocking = [
            finding
            for finding in final_checks["findings"]
            if finding.get("status") in {"warning", "failure"}
            and finding.get("severity") == "high"
        ]
        if blocking:
            decision["status"] = "human_review"
            for finding in blocking:
                evidence = finding.get("evidence", {})
                source_form = evidence.get("source_phrase") or (
                    (evidence.get("curated_mismatches") or [{}])[0].get(
                        "source_form", ""
                    )
                )
                decision.setdefault("human_review_requests", []).append(
                    {
                        "latin": source_form,
                        "english": evidence.get("matched_wrong_rendering")
                        or evidence.get("final_phrase", ""),
                        "issue": finding.get("message", ""),
                        "action": evidence.get("expected")
                        or "Resolve the deterministic high-severity finding before approval.",
                    }
                )
        all_evidence = prosecutor_evidence + adjudicator_evidence
        evidence_validation = assess_adjudication_evidence(decision, all_evidence)
        decision["evidence_validation"] = evidence_validation
        if evidence_validation["issues"]:
            decision["status"] = "human_review"
            invalid = [
                receipt
                for issue in evidence_validation["issues"]
                for receipt in issue["invalid_receipts"]
            ]
            labels = list(
                dict.fromkeys(
                    f"{item.get('evidence_id') or '[missing]'} ({item.get('status')})"
                    for item in invalid
                )
            )
            decision.setdefault("human_review_requests", []).append(
                {
                    "latin": "",
                    "english": "",
                    "issue": (
                        "Adjudicator positive evidence claims cite receipts "
                        "that cannot support them: " + ", ".join(labels)
                    ),
                    "action": (
                        "Inspect the cited receipts and revise or reject the "
                        "claim; no-hit, unavailable, invalid, error, unknown, "
                        "or research-lead receipts are not positive evidence."
                    ),
                }
            )
        unsupported_high = [
            (index, finding)
            for index, finding in enumerate(decision.get("findings", []))
            if isinstance(finding, dict)
            and finding.get("severity") == "high"
            and not evidence_validation["finding_support"].get(index)
            and not evidence_validation["valid_strong_basis"]
        ]
        if unsupported_high:
            decision["status"] = "human_review"
            for _, finding in unsupported_high:
                decision.setdefault("human_review_requests", []).append(
                    {
                        "latin": finding.get("latin", ""),
                        "english": finding.get("english", ""),
                        "issue": (
                            "High-severity correction lacks either a "
                            "source-verifiable Grade-A basis or a directly "
                            "cited supporting evidence receipt."
                        ),
                        "action": (
                            "Verify this correction against deterministic/source "
                            "evidence or a successful retrieved receipt before approval."
                        ),
                    }
                )
        decision["final_checks"] = final_checks
        enrich_adjudication_offsets(decision, chunk["target_latin"])
        validate_adjudication(decision)
        return {
            "final_status": decision["status"],
            "final_draft": decision["final_draft"],
            "decision": decision,
            "human_review_requests": decision["human_review_requests"],
            "unresolved_issues": decision["unresolved_issues"],
            "evidence_ids": [item.get("evidence_id") for item in all_evidence],
            "final_checks": final_checks,
            "witness_validation_gate": witness_gate,
            "witness_quorum": quorum,
            "witness_mode": mode,
            "permitted_base_witness_ids": allowed_bases,
            "automatic_acceptance_allowed": automatic_acceptance_allowed,
            "publication_eligible": (
                decision["status"] in {"accepted", "corrected"}
                and automatic_acceptance_allowed
            ),
            "quorum_enforcement": quorum_enforcement,
        }

    def refinalize_chunk(
        self, chunk: dict[str, Any], *, force: bool = False
    ) -> dict[str, Any]:
        """Reapply local acceptance policy to latest complete cached records.

        This path never traverses upstream stages and therefore cannot call a
        model provider. It exists specifically for policy upgrades and audits.
        """

        eligible = []
        for record in self.cache.inspect(
            chunk_id=chunk["chunk_id"], include_attempts=True
        ):
            if record.get("execution_profile", "production") != self.model_profile:
                continue
            fingerprint = (record.get("cache_material") or {}).get(
                "source_fingerprint"
            )
            if fingerprint and fingerprint != chunk.get("source_fingerprint"):
                continue
            eligible.append(record)
        adjudicator_candidates = [
            record
            for record in eligible
            if record.get("stage") == "adjudicator"
            and record.get("status") == "complete"
        ]
        if not adjudicator_candidates:
            raise ValueError("Cannot re-finalize without a complete cached adjudicator")
        adjudicator_record = max(
            adjudicator_candidates,
            key=lambda item: str(item.get("finished_at", "")),
        )
        latest, missing_dependencies = self._dependency_chain(
            eligible, adjudicator_record
        )
        required = {
            "research_prosecutor",
            "research_adjudicator",
            "adjudicator",
            "witness_a",
            "witness_b",
        }
        missing = sorted(
            stage
            for stage in required
            if latest.get(stage, {}).get("status") != "complete"
        )
        if missing or missing_dependencies:
            raise ValueError(
                "Cannot re-finalize without latest complete cached stages: "
                + ", ".join(missing)
                + ("; dependency lineage is incomplete" if missing_dependencies else "")
            )
        prosecutor_evidence = (
            latest["research_prosecutor"].get("output") or {}
        ).get("evidence", [])
        adjudicator_evidence = (
            latest["research_adjudicator"].get("output") or {}
        ).get("evidence", [])
        witness_gate_record = self._witness_gate_for_lineage(eligible, latest)
        witness_a_record = latest["witness_a"]
        witness_b_record = latest["witness_b"]
        witness_a = (witness_a_record.get("output") or {}).get("translation")
        witness_b = (witness_b_record.get("output") or {}).get("translation")
        output = lambda: (
            self._finalize_output(
                chunk,
                adjudicator_record["output"],
                prosecutor_evidence,
                adjudicator_evidence,
                (witness_gate_record or {}).get("output"),
                witness_a,
                witness_b,
            ),
            None,
            None,
            [],
            [
                {
                    "kind": "deterministic_refinalization",
                    "provider_called": False,
                    "source_adjudicator_key": adjudicator_record["cache_key"],
                }
            ],
        )
        result = self._stage(
            stage="finalize",
            chunk=chunk,
            inputs=self._finalization_inputs(
                adjudicator_record,
                prosecutor_evidence,
                adjudicator_evidence,
                witness_gate_record,
                witness_a_record,
                witness_b_record,
            ),
            dependencies=[
                adjudicator_record,
                *([witness_gate_record] if witness_gate_record else []),
                witness_a_record,
                witness_b_record,
            ],
            operation=output,
            force=force,
            retry_failed=True,
        )
        final = result.record["output"]
        return {
            "chunk_id": chunk["chunk_id"],
            "status": final["final_status"],
            "cached": result.cached,
            "provider_called": False,
            "human_review_requests": final["human_review_requests"],
            "unresolved_issues": final["unresolved_issues"],
        }

    def _validate_witnesses(
        self,
        chunk: dict[str, Any],
        records: dict[str, dict[str, Any]],
        *,
        force_stage: str | None = None,
        retry_failed: bool = False,
    ) -> None:
        validations: dict[str, dict[str, Any]] = {}
        for witness in ("witness_a", "witness_b"):
            validation_stage = f"{witness}_validation"
            witness_record = records[witness]

            def operation(
                witness: str = witness,
                witness_record: dict[str, Any] = witness_record,
            ):
                return (
                    validate_witness_record(chunk, witness_record, witness=witness),
                    None,
                    None,
                    [],
                    [
                        {
                            "kind": "deterministic_witness_validation",
                            "policy_version": WITNESS_VALIDATION_POLICY_VERSION,
                            "provider_called": False,
                            "raw_response_preserved_in": witness,
                        }
                    ],
                )

            result = self._stage(
                stage=validation_stage,
                chunk=chunk,
                inputs={
                    "witness_key": witness_record["cache_key"],
                    "policy_version": WITNESS_VALIDATION_POLICY_VERSION,
                },
                dependencies=[witness_record],
                operation=operation,
                force=force_stage == validation_stage,
                retry_failed=retry_failed,
            )
            records[validation_stage] = result.record
            validations[witness] = result.record["output"]

        receipt = witness_gate_receipt(validations)

        def gate_operation():
            if not receipt["proceed"]:
                raise WitnessGateError(receipt)
            return (
                receipt,
                None,
                None,
                [],
                [
                    {
                        "kind": "witness_validation_gate",
                        "policy_version": WITNESS_VALIDATION_POLICY_VERSION,
                        "provider_called": False,
                    }
                ],
            )

        result = self._stage(
            stage="witness_gate",
            chunk=chunk,
            inputs={
                "validation_keys": [
                    records[name]["cache_key"]
                    for name in ("witness_a_validation", "witness_b_validation")
                ],
                "policy_version": WITNESS_VALIDATION_POLICY_VERSION,
                "quorum_policy_version": WITNESS_QUORUM_POLICY_VERSION,
            },
            dependencies=[
                records["witness_a_validation"],
                records["witness_b_validation"],
            ],
            operation=gate_operation,
            force=force_stage == "witness_gate",
            retry_failed=retry_failed,
        )
        records["witness_gate"] = result.record

    def validate_cached_witnesses(
        self, chunk: dict[str, Any], *, force: bool = False
    ) -> dict[str, Any]:
        """Validate the latest compatible cached pair without provider calls."""

        eligible = [
            record
            for record in self.cache.inspect(
                chunk_id=chunk["chunk_id"], include_attempts=True
            )
            if record.get("execution_profile", "production") == self.model_profile
            and (
                not (record.get("cache_material") or {}).get("source_fingerprint")
                or (record.get("cache_material") or {}).get("source_fingerprint")
                == chunk.get("source_fingerprint")
            )
            and record.get("status") == "complete"
        ]
        candidates = {
            witness: [item for item in eligible if item.get("stage") == witness]
            for witness in ("witness_a", "witness_b")
        }
        if any(not candidates[name] for name in candidates):
            raise ValueError(
                "Cannot validate cached witnesses without complete records: "
                + ", ".join(name for name in candidates if not candidates[name])
            )
        pairs = []
        identity_keys = (
            "target_latin",
            "context_before",
            "context_after",
            "request_context_before",
            "request_context_after",
            "prompt_digest",
            "response_schema_digest",
        )
        for witness_a in candidates["witness_a"]:
            inputs_a = (witness_a.get("cache_material") or {}).get("inputs") or {}
            for witness_b in candidates["witness_b"]:
                inputs_b = (witness_b.get("cache_material") or {}).get("inputs") or {}
                if all(inputs_a.get(key) == inputs_b.get(key) for key in identity_keys):
                    pairs.append((witness_a, witness_b))
        if not pairs:
            raise ValueError("No compatible cached Witness A/B prompt pair is available")
        witness_a, witness_b = max(
            pairs,
            key=lambda pair: max(
                str(pair[0].get("finished_at", "")),
                str(pair[1].get("finished_at", "")),
            ),
        )
        records = {"witness_a": witness_a, "witness_b": witness_b}
        try:
            self._validate_witnesses(
                chunk,
                records,
                force_stage="witness_gate" if force else None,
                retry_failed=True,
            )
        except StageIncomplete as exc:
            records[exc.record["stage"]] = exc.record
        gate = records.get("witness_gate") or {}
        return {
            "chunk_id": chunk["chunk_id"],
            "status": (gate.get("output") or {}).get("status", gate.get("status")),
            "provider_called": False,
            "witness_a": (records.get("witness_a_validation") or {}).get("output"),
            "witness_b": (records.get("witness_b_validation") or {}).get("output"),
            "gate": gate.get("output"),
        }

    def run_chunk(
        self,
        chunk: dict[str, Any],
        *,
        through: str = "finalize",
        force_stage: str | None = None,
        retry_failed: bool = False,
    ) -> dict[str, Any]:
        if through not in STAGE_ORDER:
            raise ValueError(f"Unknown stage {through!r}; choose from {STAGE_ORDER}")
        stop_index = STAGE_ORDER.index(through)
        records: dict[str, dict[str, Any]] = {}

        def should_run(stage: str) -> bool:
            return STAGE_ORDER.index(stage) <= stop_index

        def force(stage: str) -> bool:
            return force_stage == stage

        try:
            if should_run("morphology"):
                morphology = self._stage(
                    stage="morphology",
                    chunk=chunk,
                    inputs={"target_latin": chunk["target_latin"], "backend": self.lexicon.contract_version},
                    dependencies=[],
                    operation=lambda: (
                        {
                            "backend": {"name": self.lexicon.backend_name, "contract": self.lexicon.contract_version},
                            "morphology": analyze_morphology(chunk["target_latin"], self.lexicon),
                            "flags": flags_to_json(analyze_chunk(chunk["target_latin"], self.lexicon)),
                        },
                        None,
                        None,
                        [],
                        [{"kind": "lexicon", "backend": self.lexicon.backend_name, "contract": self.lexicon.contract_version}],
                    ),
                    force=force("morphology"),
                    retry_failed=retry_failed,
                )
                records["morphology"] = morphology.record
            if through == "morphology":
                return self._summary(chunk, records)

            lexical = records["morphology"]["output"]
            if should_run("structural_parse"):
                spec = self._structural_model(chunk)
                prompt = structural_prompt(
                    chunk,
                    lexical["morphology"],
                    max_forms=int(
                        self.config.section("evidence").get(
                            "morphology_prompt_forms", 180
                        )
                    ),
                )
                response_schema = structural_wire_schema(chunk["target_latin"])
                result = self._stage(
                    stage="structural_parse",
                    chunk=chunk,
                    inputs={"target_latin": chunk["target_latin"], "context_before": chunk.get("context_before"), "context_after": chunk.get("context_after"), "morphology_cache_key": records["morphology"]["cache_key"], "prompt_digest": self._prompt_digest(prompt), "response_schema_digest": self._prompt_digest(json.dumps(response_schema, sort_keys=True))},
                    dependencies=[records["morphology"]],
                    operation=lambda: self._structured_call(
                        spec,
                        prompt,
                        lambda value: expand_structural_wire(
                            value, chunk["target_latin"]
                        ),
                        response_schema=response_schema,
                    ),
                    model=spec,
                    force=force("structural_parse"),
                    retry_failed=retry_failed,
                )
                records["structural_parse"] = result.record
            if through == "structural_parse":
                return self._summary(chunk, records)

            # Witness prompts deliberately depend only on source/context and
            # their own role configuration. Neither witness receives the
            # structural result or the other witness.
            for stage in ("witness_a", "witness_b"):
                if not should_run(stage):
                    continue
                spec = self._model(stage)
                prompt = witness_prompt(chunk)
                output_budget = estimate_witness_output_budget(
                    chunk,
                    prompt,
                    max_output_tokens=spec.max_output_tokens,
                    context_window=spec.context,
                )

                def witness_operation(
                    spec: ModelSpec = spec,
                    prompt: str = prompt,
                    output_budget: dict[str, Any] = output_budget,
                ):
                    if not output_budget["proceed"]:
                        raise WitnessOutputBudgetError(output_budget)
                    response = self.provider.chat(
                        spec,
                        prompt,
                        json_mode=False,
                    )
                    proposal = parse_plain_witness_proposal(response.content)
                    return (
                        proposal,
                        response.content,
                        response.used_model,
                        response.attempts,
                        [],
                    )

                result = self._stage(
                    stage=stage,
                    chunk=chunk,
                    inputs={"target_latin": chunk["target_latin"], "context_before": chunk.get("context_before"), "context_after": chunk.get("context_after"), "request_context_before": "", "request_context_after": "", "context_policy": "auxiliary_latin_withheld_from_witness", "prompt_digest": self._prompt_digest(prompt), "request_prompt": prompt, "response_contract": "witness_plain_v4", "request_schema": None, "output_budget": output_budget, "blind_to": ["other_witness", "prosecutor", "adjudicator", "external_english"]},
                    dependencies=[],
                    operation=witness_operation,
                    model=spec,
                    force=force(stage),
                    retry_failed=retry_failed,
                )
                records[stage] = result.record
                if through == stage:
                    return self._summary(chunk, records)

            if should_run("witness_a_validation"):
                self._validate_witnesses(
                    chunk,
                    records,
                    force_stage=force_stage,
                    retry_failed=retry_failed,
                )
                for stage in (
                    "witness_a_validation",
                    "witness_b_validation",
                    "witness_gate",
                ):
                    if through == stage:
                        return self._summary(chunk, records)

            witness_a = records["witness_a"]["output"]["translation"]
            witness_b = records["witness_b"]["output"]["translation"]
            witness_gate = records["witness_gate"]["output"]
            allowed_base_witnesses = list(
                witness_gate.get("allowed_base_witnesses") or []
            )
            if should_run("deterministic_checks"):
                editorial_precedents = self.editorial_memory.match(
                    chunk["target_latin"]
                )
                editorial_memory_identity = self.editorial_memory.cache_identity()

                def deterministic_checks_operation():
                    output = run_deterministic_checks(
                        chunk,
                        witness_a,
                        witness_b,
                        scripture=self.evidence.scripture,
                        witness_gate=records["witness_gate"]["output"],
                    )
                    output["editorial_precedents"] = editorial_precedents
                    output["editorial_precedent_policy"] = {
                        "role": "human_approved_project_consistency",
                        "not_source_evidence": True,
                    }
                    return (
                        output,
                        None,
                        None,
                        [],
                        [
                            {"kind": "deterministic_checks", "version": 2},
                            {
                                "kind": "editorial_precedent_index",
                                **editorial_memory_identity,
                            },
                        ],
                    )

                result = self._stage(
                    stage="deterministic_checks",
                    chunk=chunk,
                    inputs={"target_latin": chunk["target_latin"], "checks_version": CHECKS_VERSION, "witness_a_key": records["witness_a"]["cache_key"], "witness_b_key": records["witness_b"]["cache_key"], "witness_gate_key": records["witness_gate"]["cache_key"], "witness_quorum": records["witness_gate"]["output"].get("quorum"), "annotations": chunk.get("annotations", []), "page_markers": chunk.get("page_markers", []), "evidence_service": self.evidence.cache_identity(), "editorial_memory": editorial_memory_identity},
                    dependencies=[records["witness_a"], records["witness_b"], records["witness_gate"]],
                    operation=deterministic_checks_operation,
                    force=force("deterministic_checks"),
                    retry_failed=retry_failed,
                )
                records["deterministic_checks"] = result.record
            if through == "deterministic_checks":
                return self._summary(chunk, records)

            structural = records["structural_parse"]["output"]
            checks = records["deterministic_checks"]["output"]
            if should_run("prosecutor_initial"):
                spec = self._model("prosecutor")
                prompt = prosecutor_prompt(
                    chunk,
                    structural,
                    lexical,
                    checks,
                    witness_a,
                    witness_b,
                    max_evidence_requests=max(
                        0,
                        int(
                            self.config.section("evidence").get(
                                "max_requests_per_round", 6
                            )
                        ),
                    ),
                    witness_gate=witness_gate,
                )
                result = self._stage(
                    stage="prosecutor_initial",
                    chunk=chunk,
                    inputs={"prompt_digest": self._prompt_digest(prompt), "witness_quorum": witness_gate.get("quorum"), "valid_witnesses": witness_gate.get("valid_witnesses", []), "invalid_witnesses_supplied_to_model": False if witness_gate.get("mode") == "degraded" else None, "dependency_keys": [records[name]["cache_key"] for name in ("morphology", "structural_parse", "witness_a", "witness_b", "witness_gate", "deterministic_checks")]},
                    dependencies=[records[name] for name in ("morphology", "structural_parse", "witness_a", "witness_b", "witness_gate", "deterministic_checks")],
                    operation=lambda: self._structured_call(spec, prompt, validate_prosecutor),
                    model=spec,
                    force=force("prosecutor_initial"),
                    retry_failed=retry_failed,
                )
                records["prosecutor_initial"] = result.record
            if through == "prosecutor_initial":
                return self._summary(chunk, records)

            initial = records["prosecutor_initial"]["output"]
            if should_run("research_prosecutor"):
                requests = initial.get("evidence_requests", [])
                configured_rounds = self.research_round_limits["prosecutor"]

                def prosecutor_research_operation():
                    if not requests:
                        round_output = {
                            "requests": [],
                            "request_limit": max(
                                0,
                                int(
                                    self.config.section("evidence").get(
                                        "max_requests_per_round", 6
                                    )
                                ),
                            ),
                            "executed_requests": [],
                            "omitted_requests_count": 0,
                            "evidence": [],
                        }
                        mode = "not_requested"
                    elif configured_rounds < 1:
                        round_output = {
                            "requests": requests,
                            "request_limit": 0,
                            "executed_requests": [],
                            "omitted_requests_count": len(requests),
                            "evidence": [],
                        }
                        mode = "disabled_by_round_limit"
                    else:
                        round_output = self.evidence.execute_round(
                            requests,
                            requested_by="prosecutor",
                            chunk=chunk,
                        )
                        mode = "executed"
                    round_output = {
                        **round_output,
                        "round": 1,
                        "mode": mode,
                    }
                    self._require_successful_evidence_round(round_output)
                    return (
                        round_output,
                        None,
                        None,
                        [],
                        [{"kind": "evidence_service", "bounded": True}],
                    )

                result = self._stage(
                    stage="research_prosecutor",
                    chunk=chunk,
                    inputs={"orchestration_version": 2, "requests": requests, "round_limit": configured_rounds, "prosecutor_key": records["prosecutor_initial"]["cache_key"], "evidence_service": self.evidence.cache_identity()},
                    dependencies=[records["prosecutor_initial"]],
                    operation=prosecutor_research_operation,
                    force=force("research_prosecutor"),
                    retry_failed=retry_failed,
                )
                records["research_prosecutor"] = result.record
            if through == "research_prosecutor":
                return self._summary(chunk, records)

            prosecutor_evidence = records["research_prosecutor"]["output"]["evidence"]
            if should_run("prosecutor_grounded"):
                if not initial.get("evidence_requests"):
                    def grounded_without_call():
                        copied = dict(initial)
                        copied["evidence_requests"] = []
                        copied["grounding"] = {"mode": "visible_prompt_evidence_only", "evidence_ids": []}
                        return copied, None, None, [], []

                    operation = grounded_without_call
                    spec = None
                    prompt_digest = None
                else:
                    if configured_rounds < 1:
                        def no_round():
                            copied = dict(initial)
                            copied["status"] = "unresolved"
                            copied["evidence_requests"] = []
                            copied["grounding"] = {"mode": "research_round_disabled", "evidence_ids": []}
                            return copied, None, None, [], []
                        operation = no_round
                        spec = None
                        prompt_digest = None
                    else:
                        spec = self._model("prosecutor")
                        prompt = grounded_prosecutor_prompt(chunk, initial, prosecutor_evidence)
                        prompt_digest = self._prompt_digest(prompt)
                        operation = lambda: self._structured_call(spec, prompt, validate_prosecutor)
                result = self._stage(
                    stage="prosecutor_grounded",
                    chunk=chunk,
                    inputs={"initial_key": records["prosecutor_initial"]["cache_key"], "research_key": records["research_prosecutor"]["cache_key"], "round_limit": configured_rounds, "prompt_digest": prompt_digest},
                    dependencies=[records["prosecutor_initial"], records["research_prosecutor"]],
                    operation=operation,
                    model=spec,
                    force=force("prosecutor_grounded"),
                    retry_failed=retry_failed,
                )
                records["prosecutor_grounded"] = result.record
            if through == "prosecutor_grounded":
                return self._summary(chunk, records)

            grounded = records["prosecutor_grounded"]["output"]
            adjudicator_rounds = self.research_round_limits["adjudicator"]

            adjudicator_dependencies = [
                records[name]
                for name in (
                    "morphology",
                    "structural_parse",
                    "witness_a",
                    "witness_b",
                    "witness_gate",
                    "deterministic_checks",
                    "prosecutor_grounded",
                )
            ]
            if should_run("adjudicator_initial"):
                spec = self._model("adjudicator")
                response_schema = adjudication_schema(allowed_base_witnesses)
                budgeted_prompt = budgeted_adjudicator_prompt(
                    chunk,
                    witness_a,
                    witness_b,
                    structural,
                    lexical,
                    checks,
                    grounded,
                    prosecutor_evidence,
                    response_schema=response_schema,
                    budget=self.adjudicator_input_budget,
                    witness_gate=witness_gate,
                )

                def initial_adjudicator_operation():
                    if not budgeted_prompt.fits or budgeted_prompt.prompt is None:
                        raise AdjudicatorInputBudgetError(budgeted_prompt.receipt)
                    output, raw, actual_model, attempts, provenance = (
                        self._structured_call(
                            spec,
                            budgeted_prompt.prompt,
                            lambda value: expand_adjudication_wire(
                                value,
                                witness_a,
                                witness_b,
                                allowed_base_witnesses=allowed_base_witnesses,
                            ),
                            response_schema=response_schema,
                        )
                    )
                    provenance.append(
                        {
                            "kind": "adjudicator_input_budget",
                            "receipt": budgeted_prompt.receipt,
                            "provider_called": True,
                        }
                    )
                    return output, raw, actual_model, attempts, provenance

                result = self._stage(
                    stage="adjudicator_initial",
                    chunk=chunk,
                    inputs={
                        "round": 0,
                        "adjudication_contract_version": 2,
                        "witness_quorum": witness_gate.get("quorum"),
                        "allowed_base_witnesses": allowed_base_witnesses,
                        "automatic_acceptance_allowed": witness_gate.get(
                            "automatic_acceptance_allowed"
                        ),
                        "prompt_digest": (
                            self._prompt_digest(budgeted_prompt.prompt)
                            if budgeted_prompt.prompt is not None
                            else None
                        ),
                        "input_budget": budgeted_prompt.receipt,
                        "response_schema_digest": self._prompt_digest(
                            json.dumps(response_schema, sort_keys=True)
                        ),
                        "evidence_ids": [
                            item.get("evidence_id") for item in prosecutor_evidence
                        ],
                        "dependency_keys": [
                            record["cache_key"] for record in adjudicator_dependencies
                        ],
                    },
                    dependencies=adjudicator_dependencies,
                    operation=initial_adjudicator_operation,
                    model=spec,
                    force=force("adjudicator_initial"),
                    retry_failed=retry_failed,
                    recover_failed=lambda record: self._recover_adjudication_output(
                        record,
                        witness_a,
                        witness_b,
                        allowed_base_witnesses,
                    ),
                )
                records["adjudicator_initial"] = result.record
            if through == "adjudicator_initial":
                return self._summary(chunk, records)

            initial_decision = records["adjudicator_initial"]["output"]
            adjudicator_requests = initial_decision.get("evidence_requests", [])
            if should_run("research_adjudicator"):
                def adjudicator_research_operation():
                    if not adjudicator_requests:
                        round_output = {
                            "requests": [],
                            "request_limit": max(
                                0,
                                int(
                                    self.config.section("evidence").get(
                                        "max_requests_per_round", 6
                                    )
                                ),
                            ),
                            "executed_requests": [],
                            "omitted_requests_count": 0,
                            "evidence": [],
                        }
                        mode = "not_requested"
                    elif adjudicator_rounds < 1:
                        round_output = {
                            "requests": adjudicator_requests,
                            "request_limit": 0,
                            "executed_requests": [],
                            "omitted_requests_count": len(
                                adjudicator_requests
                            ),
                            "evidence": [],
                        }
                        mode = "disabled_by_round_limit"
                    else:
                        round_output = self.evidence.execute_round(
                            adjudicator_requests,
                            requested_by="adjudicator",
                            chunk=chunk,
                        )
                        mode = "executed"
                    round_output = {
                        **round_output,
                        "round": 1,
                        "adjudication_contract_version": 2,
                        "mode": mode,
                    }
                    self._require_successful_evidence_round(round_output)
                    return (
                        round_output,
                        None,
                        None,
                        [],
                        [{"kind": "evidence_service", "bounded": True}],
                    )

                research_result = self._stage(
                    stage="research_adjudicator",
                    chunk=chunk,
                    inputs={
                        "orchestration_version": 2,
                        "round": 1,
                        "round_limit": adjudicator_rounds,
                        "requests": adjudicator_requests,
                        "adjudicator_initial_key": records["adjudicator_initial"][
                            "cache_key"
                        ],
                        "evidence_service": self.evidence.cache_identity(),
                    },
                    dependencies=[records["adjudicator_initial"]],
                    operation=adjudicator_research_operation,
                    force=force("research_adjudicator"),
                    retry_failed=retry_failed,
                )
                records["research_adjudicator"] = research_result.record
            if through == "research_adjudicator":
                return self._summary(chunk, records)

            adjudicator_evidence = records["research_adjudicator"]["output"][
                "evidence"
            ]
            if should_run("adjudicator"):
                if not adjudicator_requests or adjudicator_rounds < 1:
                    def retain_initial_decision():
                        decision = json.loads(
                            json.dumps(initial_decision, ensure_ascii=False)
                        )
                        decision["grounding"] = {
                            "mode": (
                                "no_follow_up_requested"
                                if not adjudicator_requests
                                else "research_round_disabled"
                            ),
                            "evidence_ids": [],
                        }
                        return decision, None, None, [], []

                    final_operation = retain_initial_decision
                    final_spec = None
                    final_prompt_digest = None
                else:
                    final_spec = self._model("adjudicator")
                    final_response_schema = adjudication_schema(
                        allowed_base_witnesses
                    )
                    all_evidence = prosecutor_evidence + adjudicator_evidence
                    final_budgeted_prompt = budgeted_adjudicator_prompt(
                        chunk,
                        witness_a,
                        witness_b,
                        structural,
                        lexical,
                        checks,
                        grounded,
                        all_evidence,
                        response_schema=final_response_schema,
                        budget=self.adjudicator_input_budget,
                        witness_gate=witness_gate,
                    )
                    final_prompt_digest = (
                        self._prompt_digest(final_budgeted_prompt.prompt)
                        if final_budgeted_prompt.prompt is not None
                        else None
                    )

                    def guarded_final_adjudicator_operation():
                        if (
                            not final_budgeted_prompt.fits
                            or final_budgeted_prompt.prompt is None
                        ):
                            raise AdjudicatorInputBudgetError(
                                final_budgeted_prompt.receipt
                            )
                        output, raw, actual_model, attempts, provenance = (
                            self._structured_call(
                                final_spec,
                                final_budgeted_prompt.prompt,
                                lambda value: expand_adjudication_wire(
                                    value,
                                    witness_a,
                                    witness_b,
                                    allowed_base_witnesses=allowed_base_witnesses,
                                ),
                                response_schema=final_response_schema,
                            )
                        )
                        provenance.append(
                            {
                                "kind": "adjudicator_input_budget",
                                "receipt": final_budgeted_prompt.receipt,
                                "provider_called": True,
                            }
                        )
                        return output, raw, actual_model, attempts, provenance

                    final_operation = guarded_final_adjudicator_operation
                result = self._stage(
                    stage="adjudicator",
                    chunk=chunk,
                    inputs={
                        "round": 1,
                        "initial_key": records["adjudicator_initial"]["cache_key"],
                        "research_key": records["research_adjudicator"]["cache_key"],
                        "prompt_digest": final_prompt_digest,
                        "input_budget": (
                            final_budgeted_prompt.receipt
                            if final_spec is not None
                            else None
                        ),
                        "response_schema_digest": (
                            self._prompt_digest(
                                json.dumps(final_response_schema, sort_keys=True)
                            )
                            if final_spec is not None
                            else None
                        ),
                        "evidence_ids": [
                            item.get("evidence_id")
                            for item in prosecutor_evidence + adjudicator_evidence
                        ],
                        "witness_quorum": witness_gate.get("quorum"),
                        "allowed_base_witnesses": allowed_base_witnesses,
                        "automatic_acceptance_allowed": witness_gate.get(
                            "automatic_acceptance_allowed"
                        ),
                    },
                    dependencies=[
                        records["adjudicator_initial"],
                        records["research_adjudicator"],
                    ],
                    operation=final_operation,
                    model=final_spec,
                    force=force("adjudicator"),
                    retry_failed=retry_failed,
                    recover_failed=lambda record: self._recover_adjudication_output(
                        record,
                        witness_a,
                        witness_b,
                        allowed_base_witnesses,
                    ),
                )
                records["adjudicator"] = result.record
            if through == "adjudicator":
                return self._summary(chunk, records)

            if should_run("finalize"):
                original_decision = records["adjudicator"]["output"]

                def finalize_operation():
                    return (
                        self._finalize_output(
                            chunk,
                            original_decision,
                            prosecutor_evidence,
                            adjudicator_evidence,
                            records["witness_gate"]["output"],
                            witness_a,
                            witness_b,
                        ),
                        None,
                        None,
                        [],
                        [],
                    )

                result = self._stage(
                    stage="finalize",
                    chunk=chunk,
                    inputs=self._finalization_inputs(
                        records["adjudicator"],
                        prosecutor_evidence,
                        adjudicator_evidence,
                        records["witness_gate"],
                        records["witness_a"],
                        records["witness_b"],
                    ),
                    dependencies=[
                        records["adjudicator"],
                        records["witness_gate"],
                        records["witness_a"],
                        records["witness_b"],
                    ],
                    operation=finalize_operation,
                    force=force("finalize"),
                    retry_failed=retry_failed,
                )
                records["finalize"] = result.record
            return self._summary(chunk, records)
        except StageIncomplete as exc:
            records[exc.record["stage"]] = exc.record
            return self._summary(chunk, records, incomplete=True, error=str(exc))

    def run_experimental_witness(
        self,
        chunk: dict[str, Any],
        *,
        role: str = "experimental_translategemma",
        force: bool = False,
        retry_failed: bool = False,
    ) -> dict[str, Any]:
        """Run an isolated optional witness without promoting it to production."""
        spec = self._model(role)
        prompt = witness_prompt(chunk)
        stage = "experimental_witness_" + "".join(
            char if char.isalnum() or char == "_" else "_" for char in role
        )

        def operation():
            response = self.provider.chat(spec, prompt, json_mode=False)
            translation = response.content.strip()
            if not translation:
                raise ModelOutputError(
                    "Experimental witness returned an empty translation",
                    raw_response=response.content,
                    response=response,
                )
            return (
                {"translation": translation, "production_role": False},
                response.content,
                response.used_model,
                response.attempts,
                [{"kind": "experimental_witness", "not_production_input": True}],
            )

        try:
            return self._stage(
                stage=stage,
                chunk=chunk,
                inputs={
                    "target_latin": chunk["target_latin"],
                    "context_before": chunk.get("context_before"),
                    "context_after": chunk.get("context_after"),
                    "blind_to": [
                        "production_witnesses",
                        "prosecutor",
                        "adjudicator",
                        "external_english",
                    ],
                },
                dependencies=[],
                operation=operation,
                model=spec,
                force=force,
                retry_failed=retry_failed,
            ).record
        except StageIncomplete as exc:
            return exc.record

    @staticmethod
    def _prompt_digest(prompt: str) -> str:
        from .cache import canonical_digest

        return canonical_digest(prompt)

    @staticmethod
    def _summary(
        chunk: dict[str, Any],
        records: dict[str, dict[str, Any]],
        *,
        incomplete: bool = False,
        error: str | None = None,
    ) -> dict[str, Any]:
        final = records.get("finalize", {}).get("output")
        return {
            "chunk_id": chunk["chunk_id"],
            "status": "incomplete" if incomplete else (final or {}).get("final_status", "partial"),
            "completed_stages": [name for name in STAGE_ORDER if records.get(name, {}).get("status") == "complete"],
            "failed_stage": next((name for name, value in records.items() if value.get("status") != "complete"), None),
            "error": error,
            "records": records,
        }

    def assemble_audit(
        self, chunk: dict[str, Any], *, profile: str | None = None
    ) -> dict[str, Any]:
        selected_profile = profile or self.model_profile
        all_records = self.cache.inspect(
            chunk_id=chunk["chunk_id"], include_attempts=True
        )
        records = [
            record
            for record in all_records
            if (
                not (record.get("cache_material") or {}).get("source_fingerprint")
                or (record.get("cache_material") or {}).get("source_fingerprint")
                == chunk.get("source_fingerprint")
            )
            and (
                record.get("execution_profile", "production") == selected_profile
                or (
                    selected_profile == "smoke"
                    and record.get("stage") == "morphology"
                    and not record.get("model")
                )
            )
        ]
        finalize_candidates = [
            record
            for record in records
            if record.get("stage") == "finalize"
            and record.get("status") == "complete"
        ]
        if finalize_candidates:
            root = max(
                finalize_candidates,
                key=lambda item: str(item.get("finished_at", "")),
            )
            latest, missing_dependencies = self._dependency_chain(records, root)
        else:
            # Without a completed final root there is no decision lineage to
            # follow. Preserve the prior latest-stage diagnostic view.
            latest = {}
            for record in records:
                stage = str(record.get("stage") or "")
                if stage not in latest or str(record.get("finished_at", "")) > str(
                    latest[stage].get("finished_at", "")
                ):
                    latest[stage] = record
            root = None
            missing_dependencies = []
        final = latest.get("finalize", {}).get("output", {})
        witness_quorum = latest.get("witness_gate", {}).get("output", {})
        # A locally re-finalized historical run may deliberately carry an
        # incomplete witness_gate while still exposing its immutable old draft
        # as human_review. That is a policy outcome, not a missing artifact.
        pipeline_complete = all(
            latest.get(stage, {}).get("status")
            in ({"complete", "incomplete"} if stage == "witness_gate" else {"complete"})
            for stage in STAGE_ORDER
        ) and not missing_dependencies
        return {
            "schema_version": self.config.schema_version,
            "pipeline_version": self.config.pipeline_version,
            "execution_profile": selected_profile,
            "chunk_id": chunk["chunk_id"],
            "source": chunk["source"],
            "source_units": chunk["source_units"],
            "page_markers": chunk["page_markers"],
            "target_latin": chunk["target_latin"],
            "context_before": chunk["context_before"],
            "context_after": chunk["context_after"],
            "source_spans": chunk["source_spans"],
            "annotations": chunk["annotations"],
            "witness_quorum": witness_quorum,
            "automatic_acceptance_allowed": witness_quorum.get(
                "automatic_acceptance_allowed", False
            ),
            "stages": latest,
            "audit_lineage": {
                "mode": "dependency_coherent" if root else "latest_diagnostic",
                "root_stage": root.get("stage") if root else None,
                "root_cache_key": root.get("cache_key") if root else None,
                "missing_dependencies": missing_dependencies,
                "nonselected_history_count": max(0, len(records) - len(latest)),
            },
            "stage_history": sorted(
                records,
                key=lambda item: (
                    item.get("finished_at", ""),
                    item.get("stage", ""),
                    item.get("cache_key", ""),
                ),
            ),
            "final_draft": final.get("final_draft") if pipeline_complete else None,
            "final_status": (
                final.get("final_status", "incomplete")
                if pipeline_complete
                else "incomplete"
            ),
            "human_review_requests": (
                final.get("human_review_requests", []) if pipeline_complete else []
            ),
            "unresolved_issues": (
                final.get("unresolved_issues", []) if pipeline_complete else []
            ),
        }


def write_audit_jsonl(path: Path, audits: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        for audit in audits:
            handle.write(json.dumps(audit, ensure_ascii=False, separators=(",", ":")) + "\n")
    temporary.replace(path)
