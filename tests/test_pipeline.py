from __future__ import annotations

import copy
import json
import re
import tempfile
import unittest
from pathlib import Path

from glossary import MorphologicalCandidate, Sense, WordAnalysis

from jerome_pipeline.cache import stage_record, utc_now
from jerome_pipeline.config import PipelineConfig, load_config
from jerome_pipeline.pipeline import EvidenceFirstPipeline
from jerome_pipeline.prompts import (
    adjudicator_prompt,
    budgeted_adjudicator_prompt,
    prosecutor_prompt,
)
from jerome_pipeline.providers import ProviderResponse
from jerome_pipeline.schemas import adjudication_schema


class FakeLexicon:
    backend_name = "fake_lexicon"
    contract_version = "fake/v1"

    def analyze_word(self, word: str) -> WordAnalysis:
        return WordAnalysis(
            token=word,
            senses=[Sense(lemma=word, pos="x", gloss=word)],
            candidates=[MorphologicalCandidate(lemma=word, pos="x")],
            found=True,
        )


class FakeProvider:
    def __init__(self):
        self.calls: list[str] = []
        self.response_schemas: list[tuple[str, dict | None]] = []
        self.witness_number = 0

    def chat(
        self,
        spec,
        prompt: str,
        *,
        json_mode: bool,
        response_schema=None,
    ):
        self.calls.append(spec.role)
        self.response_schemas.append((spec.role, response_schema))
        if spec.role == "structural_parser":
            content = json.dumps(
                {
                    "sentences": [
                        {
                            "id": 1,
                            "verbs": [{"form": "venit", "lemma": "venio", "mood": "indicative", "tense": "perfect", "voice": "active"}],
                            "subject": {"text": "implicit", "uncertain": True},
                            "objects": [],
                            "clauses": [],
                            "attachments": [],
                            "referents": [],
                            "idioms": [],
                            "alternatives": [],
                        }
                    ],
                    "intrinsic": [],
                    "context": [],
                    "unverified": [],
                }
            )
        elif spec.role in {"witness_a", "witness_b"}:
            self.witness_number += 1
            # Each prompt contains source/context only. No other output leaks.
            self.assert_witness_blind(prompt)
            translation = "He did not come." if spec.role == "witness_a" else "He has not come."
            unit_ids = re.findall(r'<SOURCE_UNIT id="([^"]+)">', prompt)
            content = json.dumps(
                {
                    "translation": translation,
                    "source_mappings": [
                        {
                            "source_unit_id": unit_id,
                            "english_end_quote": translation,
                        }
                        for unit_id in unit_ids
                    ],
                    "omissions": [],
                    "uncertainties": [],
                }
            )
        elif spec.role == "prosecutor":
            content = json.dumps({"status": "no_issue_found", "summary": "No grounded issue found.", "challenges": [], "evidence_requests": []})
        elif spec.role == "adjudicator":
            content = json.dumps(
                {
                    "status": "accepted",
                    "base_witness": "a",
                    "edits": [],
                    "summary": "Visible evidence converges without proving correctness.",
                    "coverage": {"all_clauses_accounted_for": True, "omissions_corrected": []},
                    "findings": [],
                    "unresolved_issues": [],
                    "human_review_requests": [],
                    "evidence_requests": [],
                    "decision_basis": [{"grade": "C", "claim": "Latin negation is represented", "evidence_ids": []}],
                }
            )
        else:
            raise AssertionError(spec.role)
        return ProviderResponse(content=content, seconds=0.01, used_model=spec.cache_identity(), attempts=[{"provider": "fake", "outcome": "complete", "done": True, "done_reason": "stop", "eval_count": 10}], fallback_used=False)

    @staticmethod
    def assert_witness_blind(prompt: str):
        for forbidden in ("WITNESS A", "WITNESS B", "PROSECUTOR REPORT", "BLIND STRUCTURAL PARSE"):
            if forbidden in prompt:
                raise AssertionError(f"Witness prompt leaked {forbidden}")


class EvidenceRequestingProvider(FakeProvider):
    def __init__(self):
        super().__init__()
        self.prosecutor_calls = 0
        self.adjudicator_calls = 0

    def chat(
        self,
        spec,
        prompt: str,
        *,
        json_mode: bool,
        response_schema=None,
    ):
        if spec.role not in {"prosecutor", "adjudicator"}:
            return super().chat(
                spec,
                prompt,
                json_mode=json_mode,
                response_schema=response_schema,
            )
        self.calls.append(spec.role)
        if spec.role == "prosecutor":
            self.prosecutor_calls += 1
            if "RETRIEVED EVIDENCE RECEIPTS" not in prompt:
                value = {
                    "status": "requires_evidence",
                    "summary": "The visible negation merits a corpus check.",
                    "challenges": [
                        {
                            "latin": "non venit",
                            "type": "internal_consistency",
                            "severity": "medium",
                            "witness_target": "both",
                            "claim": "Confirm the phrase rather than relying on agreement.",
                            "visible_basis": "Both witnesses preserve non.",
                            "requires_external_evidence": True,
                        }
                    ],
                    "evidence_requests": [
                        {
                            "kind": "jerome_phrase",
                            "query": "non venit",
                            "reason": "Find an inspectable Jerome occurrence.",
                        }
                    ],
                }
            else:
                value = {
                    "status": "grounded_challenge",
                    "summary": "The retrieved occurrence confirms inspectable usage.",
                    "challenges": [
                        {
                            "latin": "non venit",
                            "type": "internal_consistency",
                            "severity": "low",
                            "witness_target": "both",
                            "claim": "Negation is visibly represented.",
                            "visible_basis": "Retrieved receipt supports the phrase.",
                            "requires_external_evidence": False,
                        }
                    ],
                    "evidence_requests": [],
                }
        else:
            self.adjudicator_calls += 1
            value = {
                "status": "accepted",
                "base_witness": "a",
                "edits": [],
                "summary": "Visible evidence accounts for the negation.",
                "coverage": {
                    "all_clauses_accounted_for": True,
                    "omissions_corrected": [],
                },
                "findings": [],
                "unresolved_issues": [],
                "human_review_requests": [],
                "evidence_requests": (
                    [
                        {
                            "kind": "glossary",
                            "query": "venit",
                            "reason": "Confirm the deterministic lexical candidate.",
                        }
                    ]
                    if self.adjudicator_calls == 1
                    else []
                ),
                "decision_basis": [
                    {
                        "grade": "A",
                        "claim": "The deterministic evidence preserves non.",
                        "evidence_ids": [],
                    }
                ],
            }
        return ProviderResponse(
            content=json.dumps(value),
            seconds=0.01,
            used_model=spec.cache_identity(),
            attempts=[{"provider": "fake", "outcome": "complete"}],
            fallback_used=False,
        )


class InvalidStructuralProvider(FakeProvider):
    def chat(
        self,
        spec,
        prompt: str,
        *,
        json_mode: bool,
        response_schema=None,
    ):
        if spec.role == "structural_parser":
            self.calls.append(spec.role)
            return ProviderResponse(
                content='{"sentences": [',
                seconds=0.01,
                used_model=spec.cache_identity(),
                attempts=[{"provider": "fake", "outcome": "complete"}],
                fallback_used=False,
            )
        return super().chat(
            spec,
            prompt,
            json_mode=json_mode,
            response_schema=response_schema,
        )


class InferenceOnlyHighAdjudicatorProvider(FakeProvider):
    def chat(
        self,
        spec,
        prompt: str,
        *,
        json_mode: bool,
        response_schema=None,
    ):
        if spec.role == "adjudicator":
            self.calls.append(spec.role)
            value = {
                "status": "corrected",
                "base_witness": "a",
                "edits": [],
                "summary": "A high-severity lexical conclusion based on inference.",
                "coverage": {
                    "all_clauses_accounted_for": True,
                    "omissions_corrected": [],
                },
                "findings": [
                    {
                        "latin": "non venit",
                        "english": "He did not come.",
                        "type": "lexical",
                        "severity": "high",
                        "resolution": "Retain the inferred wording.",
                        "reason": "Model inference only.",
                        "evidence_ids": [],
                    }
                ],
                "unresolved_issues": [],
                "human_review_requests": [],
                "evidence_requests": [],
                "decision_basis": [
                    {
                        "grade": "C",
                        "claim": "The visible wording suggests this reading.",
                        "evidence_ids": [],
                    }
                ],
            }
            return ProviderResponse(
                content=json.dumps(value),
                seconds=0.01,
                used_model=spec.cache_identity(),
                attempts=[{"provider": "fake", "outcome": "complete"}],
                fallback_used=False,
            )
        return super().chat(
            spec,
            prompt,
            json_mode=json_mode,
            response_schema=response_schema,
        )


class ObservedLimitTruncationProvider(FakeProvider):
    def chat(
        self,
        spec,
        prompt: str,
        *,
        json_mode: bool,
        response_schema=None,
    ):
        if spec.role == "structural_parser":
            self.calls.append(spec.role)
            fixture = (
                Path(__file__).parent
                / "fixtures"
                / "structural_qwen35_token_limit.txt"
            ).read_text(encoding="utf-8")
            return ProviderResponse(
                content=fixture,
                seconds=133.733,
                used_model=spec.cache_identity(),
                attempts=[
                    {
                        "provider": "ollama",
                        "model": "qwen3.5:9b",
                        "outcome": "complete",
                        "done_reason": "length",
                        "eval_count": 5200,
                    }
                ],
                fallback_used=False,
                metadata={"done_reason": "length", "eval_count": 5200},
            )
        return super().chat(
            spec,
            prompt,
            json_mode=json_mode,
            response_schema=response_schema,
        )


class ExplodingConcordance:
    def exact(self, query: str, *, normalized: bool, limit: int):
        raise OSError("fixture concordance read failure")

    def lemma(self, lemma: str, *, limit: int):
        raise OSError("fixture concordance read failure")


class PipelineVerticalTest(unittest.TestCase):
    @staticmethod
    def chunk():
        return {
            "chunk_id": "book01-test",
            "id": "book01-test",
            "book": 1,
            "target_latin": "non venit",
            "context_before": "",
            "context_after": "",
            "source_fingerprint": "abc",
            "source": {"pages": ["0001A"], "source_unit_ids": ["u1"]},
            "source_spans": [{"role": "target", "source_unit_id": "u1", "page": "0001A", "clean_start": 0, "clean_end": 9}],
            "page_markers": [{"page": "0001A", "raw": "[page 0001A]"}],
            "source_units": [{"source_unit_id": "u1", "text": "non venit"}],
            "annotations": [],
        }

    def test_unsupported_research_round_count_is_rejected_up_front(self):
        with tempfile.TemporaryDirectory() as directory:
            base = load_config()
            data = copy.deepcopy(base.data)
            data["paths"]["cache"] = str(Path(directory) / "cache")
            data["evidence"]["prosecutor_research_rounds"] = 2
            config = PipelineConfig(path=base.path, root=base.root, data=data)
            with self.assertRaisesRegex(ValueError, "supports only 0 or 1"):
                EvidenceFirstPipeline(
                    config,
                    lexicon=FakeLexicon(),
                    provider=FakeProvider(),
                )

    def test_structural_output_headroom_only_changes_large_production_input(self):
        config = load_config()
        pipeline = EvidenceFirstPipeline(
            config,
            lexicon=FakeLexicon(),
            provider=FakeProvider(),
        )
        small = self.chunk()
        large = self.chunk()
        large["target_latin"] = " ".join(
            f"Sententia {index}." for index in range(1, 13)
        )

        self.assertEqual(pipeline._structural_model(small).max_output_tokens, 5200)
        self.assertEqual(pipeline._structural_model(large).max_output_tokens, 7200)

        smoke = EvidenceFirstPipeline(
            config,
            lexicon=FakeLexicon(),
            provider=FakeProvider(),
            model_profile="smoke",
        )
        self.assertEqual(smoke._structural_model(large).max_output_tokens, 5200)

    def test_adjudicator_prompt_keeps_witnesses_and_excludes_full_morphology(self):
        prompt = adjudicator_prompt(
            self.chunk(),
            "WITNESS_A_SENTINEL",
            "WITNESS_B_SENTINEL",
            {
                "sentences": [
                    {
                        "latin": "non venit",
                        "main_verbs": [],
                        "subject": {},
                        "alternatives": [],
                    }
                ],
                "intrinsic_ambiguity": [],
                "context_dependent": [],
                "unverified_analyses": [],
            },
            {
                "flags": [
                    {
                        "token": "non",
                        "offset": 0,
                        "flag_type": "known_trap",
                        "senses": [],
                        "note": "relevant",
                    }
                ],
                "morphology": [
                    {"unbounded": "FULL_MORPHOLOGY_SENTINEL" * 10000}
                ],
            },
            {"summary": {}, "findings": [], "limits": "fixture"},
            {"challenges": [], "evidence_requests": []},
            [],
        )
        self.assertIn("WITNESS_A_SENTINEL", prompt)
        self.assertIn("WITNESS_B_SENTINEL", prompt)
        self.assertNotIn("FULL_MORPHOLOGY_SENTINEL", prompt)
        self.assertLess(len(prompt), 12000)

    def test_live_prosecutor_regression_compacts_input_and_bounds_output(self):
        structural = {
            "sentences": [
                {
                    "latin": f"sententia {index}",
                    "main_verbs": [
                        {
                            "form": "est",
                            "lemma": "sum",
                            "mood": "indicative",
                            "tense": "present",
                            "voice": "active",
                            "basis": "blind structural model constrained by morphology",
                        }
                    ],
                    "subject": {
                        "text": "implicit",
                        "basis": "blind structural model",
                        "uncertain": False,
                    },
                    "objects": [],
                    "subordinate_clauses": [],
                    "attachments": [],
                    "referents": [],
                    "idioms": [],
                    "alternatives": [],
                }
                for index in range(25)
            ],
            "intrinsic_ambiguity": [],
            "context_dependent": [],
            "unverified_analyses": [],
        }
        flags = [
            {
                "token": f"forma{index}",
                "offset": index,
                "flag_type": "not_found",
                "senses": [],
                "note": "Not resolved by the deterministic backend.",
            }
            for index in range(96)
        ]
        prompt = prosecutor_prompt(
            self.chunk(),
            structural,
            {"flags": flags},
            {"summary": {}, "findings": [], "limits": "fixture"},
            "Witness A",
            "Witness B",
            max_evidence_requests=6,
        )

        dense_structural = json.dumps(
            structural,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        pretty_structural = json.dumps(
            structural,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
        self.assertIn(dense_structural, prompt)
        self.assertNotIn(pretty_structural, prompt)
        self.assertIn("at most 12 distinct substantive challenges", prompt)
        self.assertIn("at most 6 evidence requests", prompt)
        self.assertIn("Emit minified JSON on one line", prompt)

    def test_adjudicator_budget_compacts_lower_priority_material_and_preserves_core(self):
        challenge_claim = "Witness A reverses the decisive Latin polarity."
        decisive_text = (
            "concaluit cor meum means the heart grew hot; "
            + ("decisive source wording " * 38)
        )
        structural = {
            "sentences": [
                {
                    "latin": "concaluit cor meum " + ("structura " * 500),
                    "main_verbs": [
                        {
                            "form": "concaluit",
                            "lemma": "concaleo",
                            "mood": "indicative",
                            "tense": "perfect",
                            "voice": "active",
                        }
                    ],
                    "subject": {"text": "cor"},
                    "alternatives": [],
                }
                for _ in range(12)
            ],
            "intrinsic_ambiguity": [],
            "context_dependent": [],
            "unverified_analyses": [],
        }
        prosecutor = {
            "status": "grounded_challenge",
            "summary": "A high-severity objection survives grounding.",
            "challenges": [
                {
                    "latin": "concaluit cor meum",
                    "type": "lexical",
                    "severity": "high",
                    "witness_target": "witness_a",
                    "claim": challenge_claim,
                    "visible_basis": "Receipt ev-decisive confirms the source reading.",
                    "requires_external_evidence": False,
                }
            ],
            "evidence_requests": [],
        }
        evidence = [
            {
                "evidence_id": "ev-decisive",
                "request": {
                    "kind": "jerome_phrase",
                    "query": "concaluit cor meum",
                    "reason": "Resolve the polarity.",
                },
                "status": "found",
                "evidence_class": "retrieved_evidence",
                "results": [
                    {
                        "text": decisive_text,
                        "provenance": {
                            "source_unit_id": "u1",
                            "page": "0001A",
                        },
                    }
                ],
            }
        ]
        result = budgeted_adjudicator_prompt(
            self.chunk(),
            "WITNESS_A_COMPLETE",
            "WITNESS_B_COMPLETE",
            structural,
            {"flags": [], "morphology": []},
            {
                "summary": {"warning": 1},
                "findings": [
                    {
                        "check": "known_translation_trap",
                        "status": "warning",
                        "severity": "high",
                        "message": "Polarity reversal",
                        "evidence": {
                            "source_phrase": "concaluit cor meum",
                            "witness": "witness_a",
                        },
                    }
                ],
                "limits": "deterministic signals only",
            },
            prosecutor,
            evidence,
            response_schema=adjudication_schema(),
            budget={
                "max_prompt_utf8_bytes": 16000,
                "max_request_utf8_bytes": 20000,
                "max_estimated_prompt_tokens": 5400,
                "estimator_bytes_per_token": 3.0,
            },
        )
        self.assertTrue(result.fits)
        self.assertIsNotNone(result.prompt)
        prompt = result.prompt or ""
        for mandatory in (
            self.chunk()["target_latin"],
            "WITNESS_A_COMPLETE",
            "WITNESS_B_COMPLETE",
            challenge_claim,
            "ev-decisive",
            decisive_text,
        ):
            self.assertIn(mandatory, prompt)
        self.assertIn(
            "structural_uncertainty_and_challenged_verbs_only",
            result.receipt["compaction_steps"],
        )
        self.assertLessEqual(
            result.receipt["final"]["estimated_prompt_tokens"], 5400
        )

    def test_adjudicator_dense_json_regression_preserves_live_mandatory_core(self):
        chunk = self.chunk()
        chunk["target_latin"] = " ".join(["latinum"] * 275)
        challenges = []
        evidence = []
        for index in range(9):
            evidence_id = f"ev-live-{index}"
            challenges.append(
                {
                    "latin": f"latinum {index}",
                    "type": "lexical",
                    "severity": "high" if index < 3 else "medium",
                    "witness_target": "both",
                    "claim": f"MANDATORY_CLAIM_{index} " + ("substantive objection " * 18),
                    "visible_basis": f"Receipt {evidence_id} " + ("visible grounded basis " * 22),
                    "requires_external_evidence": False,
                }
            )
            if index < 3:
                evidence.append(
                    {
                        "evidence_id": evidence_id,
                        "request": {
                            "kind": "jerome_phrase",
                            "query": f"latinum {index}",
                            "reason": "Resolve a high-severity objection.",
                        },
                        "status": "found",
                        "evidence_class": "retrieved_evidence",
                        "results": [
                            {
                                "text": f"DECISIVE_TEXT_{index} "
                                + ("source wording " * 480),
                                "provenance": {"source_unit_id": f"u{index}"},
                            }
                        ],
                    }
                )
        checks = {
            "summary": {"warning": 6},
            "findings": [
                {
                    "check": "known_translation_trap",
                    "status": "warning",
                    "severity": "high",
                    "message": f"Mandatory deterministic finding {index}",
                    "evidence": {
                        "source_phrase": f"latinum {index}",
                        "expected": "required rendering",
                        "witness": "both",
                    },
                }
                for index in range(6)
            ],
            "limits": "fixture",
        }
        result = budgeted_adjudicator_prompt(
            chunk,
            " ".join(["WITNESS_A_COMPLETE"] * 115),
            " ".join(["WITNESS_B_COMPLETE"] * 115),
            {
                "sentences": [],
                "intrinsic_ambiguity": [],
                "context_dependent": [],
                "unverified_analyses": [],
            },
            {"flags": []},
            checks,
            {
                "status": "grounded_challenge",
                "summary": "Verbose live-style challenge set.",
                "challenges": challenges,
                "evidence_requests": [],
            },
            evidence,
            response_schema=adjudication_schema(),
            budget={
                "max_prompt_utf8_bytes": 45000,
                "max_request_utf8_bytes": 52000,
                "max_estimated_prompt_tokens": 15000,
                "estimator_bytes_per_token": 3.0,
            },
        )
        self.assertTrue(result.fits)
        self.assertEqual(
            result.receipt["serialization"],
            "dense_json",
            result.receipt,
        )
        self.assertIn(
            "dense_json_encoding_without_semantic_loss",
            result.receipt["compaction_steps"],
        )
        prompt = result.prompt or ""
        for index in range(9):
            self.assertIn(f"MANDATORY_CLAIM_{index}", prompt)
        for index in range(3):
            self.assertIn(f"DECISIVE_TEXT_{index}", prompt)

    def test_failed_adjudicator_raw_response_is_revalidated_without_provider(self):
        raw = json.dumps(
            {
                "status": "corrected",
                "base_witness": "b",
                "edits": [
                    {
                        "old": "despised and contemptuous",
                        "new": "despised and contemptible",
                        "reason": "Correct the adjective.",
                        "evidence_ids": [],
                    },
                    {
                        "old": "is despised and contemptuous by all heretics",
                        "new": "is spurned and despised by all heretics",
                        "reason": "Restore the passive sense.",
                        "evidence_ids": [],
                    },
                ],
                "summary": "Observed overlapping-edit response.",
                "coverage": {
                    "all_clauses_accounted_for": True,
                    "omissions_corrected": [],
                },
                "findings": [],
                "unresolved_issues": [],
                "human_review_requests": [],
                "evidence_requests": [],
                "decision_basis": [],
            }
        )
        recovered = EvidenceFirstPipeline._recover_adjudication_output(
            {
                "status": "failed",
                "raw_response": raw,
                "model": {"model": "fixture"},
                "provider_attempts": [{"outcome": "complete"}],
                "error": {"category": "invalid_model_output"},
            },
            "Unused witness.",
            (
                "The name is despised and contemptuous. The Creator is despised "
                "and contemptuous by all heretics."
            ),
        )
        self.assertIsNotNone(recovered)
        output, recovered_raw, _, attempts, provenance = recovered or (None,) * 5
        self.assertEqual(recovered_raw, raw)
        self.assertEqual(attempts, [{"outcome": "complete"}])
        self.assertEqual(
            output["coverage"]["edit_application_mode"],
            "specificity_fallback",
        )
        self.assertFalse(provenance[0]["provider_called"])

    def test_inference_only_high_severity_adjudication_forces_human_review(self):
        with tempfile.TemporaryDirectory() as directory:
            base = load_config()
            data = copy.deepcopy(base.data)
            data["paths"]["cache"] = str(Path(directory) / "cache")
            data["paths"]["concordance"] = str(Path(directory) / "missing.jsonl")
            config = PipelineConfig(path=base.path, root=base.root, data=data)
            pipeline = EvidenceFirstPipeline(
                config,
                lexicon=FakeLexicon(),
                provider=InferenceOnlyHighAdjudicatorProvider(),
            )

            result = pipeline.run_chunk(self.chunk())

            self.assertEqual(result["status"], "human_review")
            final = result["records"]["finalize"]["output"]
            self.assertTrue(
                any(
                    "lacks either a" in item.get("issue", "")
                    for item in final["human_review_requests"]
                )
            )

    def test_observed_chunk5_proposal_fails_closed_without_mutating_it(self):
        latin = (
            "electri esse in medio venti vel spiritus Ergo hoc sentiendum quod "
            "in medio ignis et tormentorum Dei electri similitudo sit quod est "
            "auro argentoque pretiosius ut post judicium atque tormenta quae "
            "patientibus tristia videntur et dura pretiosior electri fulgor "
            "appareat dum providentia Dei omnia gubernantur et quae putatur "
            "poena medicina est"
        )
        old = " ".join(f"english{index}" for index in range(73))
        decision = {
            "status": "corrected",
            "final_draft": latin + ". And the four living creatures appeared.",
            "summary": "Observed live proposal.",
            "coverage": {
                "all_clauses_accounted_for": True,
                "omissions_corrected": [],
                "base_witness": "b",
                "applied_edits": [
                    {
                        "old": old,
                        "new": latin,
                        "reason": "Restore an alleged omission.",
                        "evidence_ids": [],
                    }
                ],
            },
            "findings": [
                {
                    "latin": "electri",
                    "english": "electrum",
                    "severity": "high",
                    "resolution": "Use electrum.",
                    "evidence_ids": ["ev-observed-no-hit"],
                }
            ],
            "unresolved_issues": [{"latin": "electri"}],
            "human_review_requests": [],
            "evidence_requests": [],
            "decision_basis": [
                {
                    "grade": "B",
                    "claim": "The receipt proves electrum.",
                    "evidence_ids": ["ev-observed-no-hit"],
                }
            ],
        }
        original = copy.deepcopy(decision)
        output = EvidenceFirstPipeline._finalize_output(
            {**self.chunk(), "target_latin": latin},
            decision,
            [
                {
                    "evidence_id": "ev-observed-no-hit",
                    "status": "no_evidence_found",
                    "evidence_class": "retrieved_evidence",
                    "results": [],
                }
            ],
            [],
        )
        self.assertEqual(decision, original)
        self.assertEqual(output["final_status"], "human_review")
        checks = {
            item["check"]: item
            for item in output["final_checks"]["findings"]
        }
        self.assertEqual(checks["source_latin_copy"]["severity"], "high")
        self.assertEqual(checks["adjudicator_edit_scope"]["severity"], "high")
        self.assertTrue(output["decision"]["evidence_validation"]["issues"])

    def test_adjudicator_budget_fails_closed_before_provider_call(self):
        with tempfile.TemporaryDirectory() as directory:
            base = load_config()
            data = copy.deepcopy(base.data)
            data["paths"]["cache"] = str(Path(directory) / "cache")
            data["paths"]["concordance"] = str(Path(directory) / "missing.jsonl")
            data["adjudicator_input_budget"] = {
                "max_prompt_utf8_bytes": 500,
                "max_request_utf8_bytes": 1000,
                "max_estimated_prompt_tokens": 100,
                "estimator_bytes_per_token": 3.0,
            }
            config = PipelineConfig(path=base.path, root=base.root, data=data)
            provider = FakeProvider()
            pipeline = EvidenceFirstPipeline(
                config,
                lexicon=FakeLexicon(),
                provider=provider,
            )
            result = pipeline.run_chunk(self.chunk())
            self.assertEqual(result["status"], "incomplete")
            self.assertEqual(result["failed_stage"], "adjudicator_initial")
            failed = result["records"]["adjudicator_initial"]
            self.assertEqual(
                failed["error"]["category"],
                "adjudicator_input_budget_exceeded",
            )
            self.assertFalse(failed["output"]["input_budget"]["fits"])
            self.assertNotIn("adjudicator", provider.calls)
            self.assertEqual(failed["provider_attempts"], [])

    def test_complete_chunk_and_cached_resume_without_live_models(self):
        with tempfile.TemporaryDirectory() as directory:
            base = load_config()
            data = copy.deepcopy(base.data)
            data["paths"]["cache"] = str(Path(directory) / "cache")
            data["paths"]["concordance"] = str(Path(directory) / "missing-concordance.jsonl")
            config = PipelineConfig(path=base.path, root=base.root, data=data)
            provider = FakeProvider()
            pipeline = EvidenceFirstPipeline(config, lexicon=FakeLexicon(), provider=provider)
            chunk = self.chunk()
            first = pipeline.run_chunk(chunk)
            self.assertEqual(first["status"], "accepted")
            self.assertEqual(first["completed_stages"], [
                "morphology", "structural_parse", "witness_a", "witness_b", "witness_a_validation", "witness_b_validation", "witness_gate", "deterministic_checks", "prosecutor_initial", "research_prosecutor", "prosecutor_grounded", "adjudicator_initial", "research_adjudicator", "adjudicator", "finalize"
            ])
            call_count = len(provider.calls)
            second = pipeline.run_chunk(chunk)
            self.assertEqual(second["status"], "accepted")
            self.assertEqual(len(provider.calls), call_count)
            audit = pipeline.assemble_audit(chunk)
            self.assertEqual(audit["final_status"], "accepted")
            self.assertEqual(audit["execution_profile"], "production")
            self.assertEqual(audit["final_draft"], "He did not come.")
            self.assertEqual(audit["stages"]["structural_parse"]["output"]["sentences"][0]["latin"], "non venit")
            adjudicator_schemas = [
                schema
                for role, schema in provider.response_schemas
                if role == "adjudicator"
            ]
            self.assertEqual(len(adjudicator_schemas), 1)
            self.assertEqual(
                set(adjudicator_schemas[0]["required"]),
                {
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
                },
            )

            call_count = len(provider.calls)
            refinalized = pipeline.refinalize_chunk(chunk, force=True)
            self.assertEqual(refinalized["status"], "accepted")
            self.assertFalse(refinalized["provider_called"])
            self.assertEqual(len(provider.calls), call_count)
            latest_finalize = pipeline.cache.inspect(
                chunk_id=chunk["chunk_id"], stage="finalize"
            )[0]
            self.assertFalse(
                latest_finalize["provenance"][0]["provider_called"]
            )

    def test_audit_follows_final_dependency_chain_not_newer_orphan_stage(self):
        with tempfile.TemporaryDirectory() as directory:
            base = load_config()
            data = copy.deepcopy(base.data)
            data["paths"]["cache"] = str(Path(directory) / "cache")
            data["paths"]["concordance"] = str(
                Path(directory) / "missing-concordance.jsonl"
            )
            config = PipelineConfig(path=base.path, root=base.root, data=data)
            pipeline = EvidenceFirstPipeline(
                config, lexicon=FakeLexicon(), provider=FakeProvider()
            )
            chunk = self.chunk()
            pipeline.run_chunk(chunk)
            original = pipeline.assemble_audit(chunk)["stages"][
                "prosecutor_initial"
            ]

            orphan_key, orphan_material = pipeline.cache.key(
                stage="prosecutor_initial",
                chunk=chunk,
                pipeline_version=config.pipeline_version,
                schema_version=config.schema_version,
                prompt_version=config.prompt_version,
                inputs={"orphan": True},
            )
            orphan = stage_record(
                stage="prosecutor_initial",
                chunk_id=chunk["chunk_id"],
                cache_key=orphan_key,
                cache_material=orphan_material,
                pipeline_version=config.pipeline_version,
                schema_version=config.schema_version,
                prompt_version=config.prompt_version,
                status="complete",
                started_at=utc_now(),
                output={
                    "status": "no_issue_found",
                    "summary": "ORPHAN_SENTINEL",
                    "challenges": [],
                    "evidence_requests": [],
                },
            )
            orphan["execution_profile"] = "production"
            pipeline.cache.save(orphan)

            audit = pipeline.assemble_audit(chunk)
            self.assertEqual(audit["audit_lineage"]["mode"], "dependency_coherent")
            self.assertEqual(
                audit["stages"]["prosecutor_initial"]["cache_key"],
                original["cache_key"],
            )
            self.assertTrue(
                any(
                    (record.get("output") or {}).get("summary")
                    == "ORPHAN_SENTINEL"
                    for record in audit["stage_history"]
                )
            )

    def test_bounded_prosecutor_and_adjudicator_evidence_rounds_end_to_end(self):
        with tempfile.TemporaryDirectory() as directory:
            base = load_config()
            data = copy.deepcopy(base.data)
            cache = Path(directory) / "cache"
            concordance = Path(directory) / "concordance.jsonl"
            concordance.write_text(
                json.dumps(
                    {
                        "source_unit_id": "u-evidence",
                        "book": 1,
                        "page": "0001A",
                        "text": "non venit",
                        "normalized": "non uenit",
                        "lemmas": ["venio"],
                        "source_fingerprint": "fixture",
                        "provenance": {
                            "corpus": "fixture",
                            "work": "fixture",
                            "source_unit_id": "u-evidence",
                            "page": "0001A",
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            data["paths"]["cache"] = str(cache)
            data["paths"]["concordance"] = str(concordance)
            config = PipelineConfig(path=base.path, root=base.root, data=data)
            provider = EvidenceRequestingProvider()
            pipeline = EvidenceFirstPipeline(
                config,
                lexicon=FakeLexicon(),
                provider=provider,
            )
            result = pipeline.run_chunk(self.chunk())
            self.assertEqual(result["status"], "accepted")
            records = result["records"]
            self.assertEqual(
                records["research_prosecutor"]["output"]["mode"],
                "executed",
            )
            self.assertEqual(
                records["research_prosecutor"]["output"]["evidence"][0]["status"],
                "found",
            )
            self.assertEqual(
                records["prosecutor_grounded"]["output"]["status"],
                "grounded_challenge",
            )
            self.assertEqual(
                records["research_adjudicator"]["output"]["mode"], "executed"
            )
            self.assertEqual(
                records["research_adjudicator"]["output"]["evidence"][0]["status"],
                "found",
            )
            self.assertEqual(provider.prosecutor_calls, 2)
            self.assertEqual(provider.adjudicator_calls, 2)

            call_count = len(provider.calls)
            resumed = pipeline.run_chunk(self.chunk())
            self.assertEqual(resumed["status"], "accepted")
            self.assertEqual(len(provider.calls), call_count)

            forced = pipeline.run_chunk(
                self.chunk(), force_stage="research_adjudicator"
            )
            self.assertEqual(forced["status"], "accepted")
            # The forced receipt has a new retrieval timestamp/output digest,
            # so only its dependent final adjudicator call is invalidated.
            self.assertEqual(len(provider.calls), call_count + 1)
            self.assertEqual(provider.prosecutor_calls, 2)
            self.assertEqual(provider.adjudicator_calls, 3)
            archived = list(
                (cache / "stages" / "research_adjudicator" / "book01-test").glob(
                    "*.attempt-*.json"
                )
            )
            self.assertEqual(len(archived), 1)

    def test_zero_prosecutor_round_records_disabled_without_lookup(self):
        with tempfile.TemporaryDirectory() as directory:
            base = load_config()
            data = copy.deepcopy(base.data)
            data["paths"]["cache"] = str(Path(directory) / "cache")
            data["paths"]["concordance"] = str(
                Path(directory) / "missing-concordance.jsonl"
            )
            data["evidence"]["prosecutor_research_rounds"] = 0
            config = PipelineConfig(path=base.path, root=base.root, data=data)
            provider = EvidenceRequestingProvider()
            pipeline = EvidenceFirstPipeline(
                config,
                lexicon=FakeLexicon(),
                provider=provider,
            )
            result = pipeline.run_chunk(
                self.chunk(), through="prosecutor_grounded"
            )
            research = result["records"]["research_prosecutor"]["output"]
            grounded = result["records"]["prosecutor_grounded"]["output"]
            self.assertEqual(research["mode"], "disabled_by_round_limit")
            self.assertEqual(research["evidence"], [])
            self.assertEqual(research["omitted_requests_count"], 1)
            self.assertEqual(grounded["status"], "unresolved")
            self.assertEqual(provider.prosecutor_calls, 1)

    def test_evidence_execution_error_fails_stage_and_preserves_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            base = load_config()
            data = copy.deepcopy(base.data)
            data["paths"]["cache"] = str(Path(directory) / "cache")
            data["paths"]["concordance"] = str(
                Path(directory) / "missing-concordance.jsonl"
            )
            config = PipelineConfig(path=base.path, root=base.root, data=data)
            pipeline = EvidenceFirstPipeline(
                config,
                lexicon=FakeLexicon(),
                provider=EvidenceRequestingProvider(),
            )
            pipeline.evidence.concordance = ExplodingConcordance()  # type: ignore[assignment]
            result = pipeline.run_chunk(
                self.chunk(), through="research_prosecutor"
            )
            self.assertEqual(result["status"], "incomplete")
            self.assertEqual(result["failed_stage"], "research_prosecutor")
            failed = result["records"]["research_prosecutor"]
            self.assertEqual(failed["status"], "failed")
            self.assertEqual(
                failed["error"]["category"], "evidence_retrieval_failed"
            )
            self.assertEqual(failed["output"]["evidence"][0]["status"], "error")
            self.assertIn(
                "fixture concordance read failure",
                failed["output"]["evidence"][0]["message"],
            )

    def test_smoke_profile_is_lightweight_and_isolated_from_production_audit(self):
        with tempfile.TemporaryDirectory() as directory:
            base = load_config()
            data = copy.deepcopy(base.data)
            data["paths"]["cache"] = str(Path(directory) / "cache")
            data["paths"]["concordance"] = str(Path(directory) / "missing.jsonl")
            config = PipelineConfig(path=base.path, root=base.root, data=data)
            smoke = config.model("prosecutor", profile="smoke")
            production = config.model("prosecutor")
            self.assertEqual(smoke.model, "qwen3.5:9b")
            self.assertIsNone(smoke.fallback)
            self.assertNotEqual(smoke.cache_identity(), production.cache_identity())

            pipeline = EvidenceFirstPipeline(
                config,
                lexicon=FakeLexicon(),
                provider=FakeProvider(),
                model_profile="smoke",
            )
            pipeline.run_chunk(self.chunk())
            smoke_audit = pipeline.assemble_audit(self.chunk())
            production_audit = pipeline.assemble_audit(
                self.chunk(), profile="production"
            )
            self.assertEqual(smoke_audit["final_status"], "accepted")
            self.assertEqual(smoke_audit["execution_profile"], "smoke")
            self.assertEqual(production_audit["final_status"], "incomplete")

    def test_invalid_live_shape_is_cached_as_failure_with_raw_response(self):
        with tempfile.TemporaryDirectory() as directory:
            base = load_config()
            data = copy.deepcopy(base.data)
            data["paths"]["cache"] = str(Path(directory) / "cache")
            data["paths"]["concordance"] = str(Path(directory) / "missing.jsonl")
            config = PipelineConfig(path=base.path, root=base.root, data=data)
            pipeline = EvidenceFirstPipeline(
                config,
                lexicon=FakeLexicon(),
                provider=InvalidStructuralProvider(),
            )
            result = pipeline.run_chunk(self.chunk(), through="structural_parse")
            self.assertEqual(result["status"], "incomplete")
            failed = result["records"]["structural_parse"]
            self.assertEqual(failed["status"], "failed")
            self.assertEqual(failed["error"]["category"], "invalid_model_output")
            self.assertEqual(failed["raw_response"], '{"sentences": [')

    def test_observed_token_limit_failure_is_classified_as_truncation(self):
        with tempfile.TemporaryDirectory() as directory:
            base = load_config()
            data = copy.deepcopy(base.data)
            data["paths"]["cache"] = str(Path(directory) / "cache")
            data["paths"]["concordance"] = str(Path(directory) / "missing.jsonl")
            config = PipelineConfig(path=base.path, root=base.root, data=data)
            pipeline = EvidenceFirstPipeline(
                config,
                lexicon=FakeLexicon(),
                provider=ObservedLimitTruncationProvider(),
            )
            result = pipeline.run_chunk(self.chunk(), through="structural_parse")
            failed = result["records"]["structural_parse"]
            self.assertEqual(failed["status"], "failed")
            self.assertEqual(failed["error"]["category"], "output_truncated")
            self.assertIn("5200 generated tokens", failed["error"]["message"])
            self.assertTrue(failed["raw_response"].rstrip().endswith('"idioms": [],'))


if __name__ == "__main__":
    unittest.main()
