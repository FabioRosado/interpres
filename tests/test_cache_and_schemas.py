from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from interpres.cache import StageCache, stage_record, utc_now
from interpres.schemas import (
    PROSECUTOR_CHALLENGE_TYPES,
    SchemaValidationError,
    adjudication_schema,
    expand_adjudication_wire,
    expand_structural_wire,
    parse_json_response,
    structural_wire_schema,
    validate_adjudication,
    validate_evidence_request,
    validate_prosecutor,
)


class CacheTest(unittest.TestCase):
    def test_dependency_output_changes_downstream_key(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = StageCache(Path(directory))
            chunk = {"chunk_id": "c1", "source_fingerprint": "source"}
            dependency_a = {"stage": "witness_a", "cache_key": "same", "status": "complete", "output": {"translation": "A"}}
            dependency_b = {"stage": "witness_a", "cache_key": "same", "status": "complete", "output": {"translation": "B"}}
            first, _ = cache.key(stage="adjudicator", chunk=chunk, pipeline_version="p", schema_version=1, prompt_version="v", inputs={}, dependencies=[dependency_a])
            second, _ = cache.key(stage="adjudicator", chunk=chunk, pipeline_version="p", schema_version=1, prompt_version="v", inputs={}, dependencies=[dependency_b])
            self.assertNotEqual(first, second)

    def test_round_trip_and_attempt_archive(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = StageCache(Path(directory))
            record = stage_record(stage="x", chunk_id="c", cache_key="k", cache_material={"inputs": {}}, pipeline_version="p", schema_version=1, prompt_version="v", status="complete", started_at=utc_now(), output={"value": 1})
            path = cache.save(record)
            self.assertEqual(cache.load("x", "c", "k")["output"], {"value": 1})
            cache.save({**record, "output": {"value": 2}})
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["output"], {"value": 2})
            self.assertEqual(len(list(path.parent.glob("*.attempt-*.json"))), 1)


class SchemaTest(unittest.TestCase):
    def test_defensive_json_parsing(self):
        self.assertEqual(parse_json_response("```json\n{\"a\":1}\n```"), {"a": 1})
        self.assertEqual(parse_json_response("prefix {\"a\":2} suffix"), {"a": 2})

    def test_invalid_prosecutor_rejected(self):
        with self.assertRaises(SchemaValidationError):
            validate_prosecutor({"status": "proved_correct", "summary": "", "challenges": [], "evidence_requests": []})

    def test_prosecutor_status_and_request_kind_consistency(self):
        with self.assertRaisesRegex(SchemaValidationError, "at least one precise challenge"):
            validate_prosecutor(
                {
                    "status": "grounded_challenge",
                    "summary": "Claims a challenge but supplies none.",
                    "challenges": [],
                    "evidence_requests": [],
                }
            )
        with self.assertRaisesRegex(SchemaValidationError, "unsupported"):
            validate_evidence_request(
                {
                    "kind": "hebrew_greek",
                    "query": "ruach Ezekiel 1:4",
                    "reason": "Observed unsupported live request.",
                }
            )

    def test_four_decision_states_and_precision_requirements(self):
        base = {
            "final_draft": "draft",
            "summary": "summary",
            "coverage": {"all_clauses_accounted_for": True, "omissions_corrected": []},
            "findings": [],
            "unresolved_issues": [],
            "human_review_requests": [],
            "evidence_requests": [],
            "decision_basis": [],
        }
        for status in ("accepted", "corrected"):
            self.assertEqual(validate_adjudication({**base, "status": status})["status"], status)
        self.assertEqual(validate_adjudication({**base, "status": "unresolved", "unresolved_issues": [{"latin": "x"}]})["status"], "unresolved")
        self.assertEqual(validate_adjudication({**base, "status": "human_review", "human_review_requests": [{"action": "inspect x"}]})["status"], "human_review")
        with self.assertRaises(SchemaValidationError):
            validate_adjudication({**base, "status": "human_review"})
        with self.assertRaisesRegex(SchemaValidationError, "cannot contain"):
            validate_adjudication(
                {
                    **base,
                    "status": "corrected",
                    "unresolved_issues": [{"latin": "electri"}],
                }
            )

    def test_wire_status_fails_closed_when_model_reports_unresolved_item(self):
        wire = {
            "status": "corrected",
            "base_witness": "b",
            "edits": [],
            "summary": "Model incorrectly calls an unresolved decision corrected.",
            "coverage": {
                "all_clauses_accounted_for": True,
                "omissions_corrected": [],
            },
            "findings": [],
            "unresolved_issues": [
                {
                    "latin": "electri",
                    "english": "electrum",
                    "alternatives": ["amber"],
                    "missing_evidence": "A decisive source",
                }
            ],
            "human_review_requests": [],
            "evidence_requests": [],
            "decision_basis": [],
        }
        expanded = expand_adjudication_wire(wire, "Witness A.", "Witness B.")
        self.assertEqual(expanded["status"], "unresolved")

    def test_adjudication_wire_schema_rejects_observed_generic_shape(self):
        schema = adjudication_schema()
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(
            set(schema["required"]),
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
        observed_generic_fields = {
            "verdict",
            "confidence",
            "reasoning",
            "key_differences",
        }
        self.assertTrue(observed_generic_fields.isdisjoint(schema["required"]))
        self.assertEqual(schema["properties"]["edits"]["maxItems"], 12)

    def test_adjudication_contract_is_constrained_by_witness_quorum(self):
        schema = adjudication_schema(["b"])
        self.assertEqual(
            schema["properties"]["base_witness"]["enum"], ["b"]
        )
        wire = {
            "status": "accepted",
            "base_witness": "a",
            "edits": [],
            "summary": "malicious invalid-base selection",
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
        with self.assertRaisesRegex(
            SchemaValidationError, "not permitted by the deterministic witness quorum"
        ):
            expand_adjudication_wire(
                wire,
                "invalid witness A",
                "valid witness B",
                allowed_base_witnesses=["b"],
            )
        with self.assertRaises(ValueError):
            adjudication_schema([])

    def test_adjudication_wire_preserves_base_and_applies_exact_edits(self):
        wire = {
            "status": "accepted",
            "base_witness": "a",
            "edits": [
                {
                    "old": "cold",
                    "new": "hot",
                    "reason": "correct polarity",
                    "evidence_ids": [],
                }
            ],
            "summary": "complete",
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
        expanded = expand_adjudication_wire(
            wire,
            "My heart grew cold. The final sentence remains.",
            "My heart was warm.",
        )
        self.assertEqual(
            expanded["final_draft"],
            "My heart grew hot. The final sentence remains.",
        )
        self.assertEqual(expanded["status"], "corrected")
        self.assertEqual(
            expanded["coverage"]["base_witness"],
            "a",
        )
        self.assertEqual(len(expanded["coverage"]["applied_edits"]), 1)
        with self.assertRaisesRegex(SchemaValidationError, "exactly once"):
            expand_adjudication_wire(
                {
                    **wire,
                    "edits": [
                        {
                            **wire["edits"][0],
                            "old": "missing",
                        }
                    ],
                },
                "My heart grew cold. The final sentence remains.",
                "My heart was warm.",
            )

    def test_adjudication_wire_removes_known_provider_preface(self):
        wire = {
            "status": "accepted",
            "base_witness": "b",
            "edits": [],
            "summary": "complete",
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
        expanded = expand_adjudication_wire(
            wire,
            "Witness A.",
            "Here is the translation of the target Latin passage:\n\nWitness B.",
        )
        self.assertEqual(expanded["final_draft"], "Witness B.")
        self.assertTrue(expanded["coverage"]["base_wrapper_removed"])

    def test_adjudication_wire_reorders_only_specific_overlapping_edits(self):
        wire = {
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
                    "reason": "Restore the passive infinitives.",
                    "evidence_ids": [],
                },
            ],
            "summary": "Overlapping corrections.",
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
        expanded = expand_adjudication_wire(
            wire,
            "Unused witness.",
            (
                "The name is despised and contemptuous. The Creator is despised "
                "and contemptuous by all heretics."
            ),
        )
        self.assertEqual(
            expanded["final_draft"],
            (
                "The name is despised and contemptible. The Creator is spurned "
                "and despised by all heretics."
            ),
        )
        self.assertEqual(
            expanded["coverage"]["edit_application_mode"],
            "specificity_fallback",
        )
        self.assertEqual(
            [item["model_order"] for item in expanded["coverage"]["applied_edits"]],
            [1, 0],
        )

        with self.assertRaisesRegex(SchemaValidationError, "found 2"):
            expand_adjudication_wire(
                {**wire, "edits": [wire["edits"][0]]},
                "Unused witness.",
                "despised and contemptuous; despised and contemptuous",
            )

    def test_compact_structural_wire_restores_exact_latin_and_rejects_gaps(self):
        target = "Non venit. Eustochium rogat."
        sentence = lambda identifier, verb, lemma, subject: {
            "id": identifier,
            "verbs": [
                {
                    "form": verb,
                    "lemma": lemma,
                    "mood": "indicative",
                    "tense": "present",
                    "voice": "active",
                }
            ],
            "subject": {"text": subject, "uncertain": False},
            "objects": [],
            "clauses": [],
            "attachments": [],
            "referents": [],
            "idioms": [],
            "alternatives": [],
        }
        wire = {
            "sentences": [
                sentence(1, "venit", "venio", "implicit"),
                sentence(2, "rogat", "rogo", "Eustochium"),
            ],
            "intrinsic": [],
            "context": [],
            "unverified": [],
        }
        expanded = expand_structural_wire(wire, target)
        self.assertEqual(
            [item["latin"] for item in expanded["sentences"]],
            ["Non venit.", "Eustochium rogat."],
        )
        self.assertEqual(
            expanded["sentences"][0]["main_verbs"][0]["basis"],
            "blind structural model constrained by morphology",
        )
        schema = structural_wire_schema(target)
        self.assertEqual(schema["properties"]["sentences"]["minItems"], 2)
        self.assertEqual(
            schema["properties"]["sentences"]["items"]["properties"]["verbs"]["maxItems"],
            6,
        )
        broken = {**wire, "sentences": [wire["sentences"][0], wire["sentences"][0]]}
        with self.assertRaisesRegex(SchemaValidationError, "duplicated"):
            expand_structural_wire(broken, target)
        too_many_verbs = json.loads(json.dumps(wire))
        too_many_verbs["sentences"][0]["verbs"] *= 7
        with self.assertRaisesRegex(SchemaValidationError, "maximum is 6"):
            expand_structural_wire(too_many_verbs, target)

    def _base_prosecutor(self) -> dict[str, Any]:
        return {
            "status": "grounded_challenge",
            "summary": "Test prosecutor response.",
            "challenges": [
                {
                    "latin": "non venit",
                    "type": "negation",
                    "severity": "medium",
                    "witness_target": "both",
                    "claim": "Negation may be misrepresented.",
                    "visible_basis": "Both witnesses show non.",
                    "requires_external_evidence": True,
                }
            ],
            "evidence_requests": [],
        }

    def test_prosecutor_exactly_15_challenges_valid(self):
        base = self._base_prosecutor()
        base["challenges"] = [
            {
                "latin": f"test {i}",
                "type": "negation",
                "severity": "low",
                "witness_target": "both",
                "claim": f"Challenge {i}.",
                "visible_basis": "Test basis.",
                "requires_external_evidence": False,
            }
            for i in range(15)
        ]
        validate_prosecutor(base)

    def test_prosecutor_16_challenges_invalid(self):
        base = self._base_prosecutor()
        base["challenges"] = [
            {
                "latin": f"test {i}",
                "type": "negation",
                "severity": "low",
                "witness_target": "both",
                "claim": f"Challenge {i}.",
                "visible_basis": "Test basis.",
                "requires_external_evidence": False,
            }
            for i in range(16)
        ]
        with self.assertRaisesRegex(SchemaValidationError, "maximum is 15"):
            validate_prosecutor(base)

    def test_prosecutor_zero_challenges_valid(self):
        base = self._base_prosecutor()
        base["status"] = "no_issue_found"
        base["challenges"] = []
        validate_prosecutor(base)

    def test_prosecutor_zero_challenges_invalid_for_grounded_challenge(self):
        base = self._base_prosecutor()
        base["challenges"] = []
        with self.assertRaisesRegex(SchemaValidationError, "at least one precise challenge"):
            validate_prosecutor(base)

    def test_prosecutor_unsupported_challenge_type_invalid(self):
        base = self._base_prosecutor()
        base["challenges"][0]["type"] = "unsupported_type"
        with self.assertRaisesRegex(SchemaValidationError, "unsupported"):
            validate_prosecutor(base)

    def test_prosecutor_allowed_challenge_types_valid(self):
        for challenge_type in PROSECUTOR_CHALLENGE_TYPES:
            base = self._base_prosecutor()
            base["challenges"][0]["type"] = challenge_type
            validate_prosecutor(base)

    def test_prosecutor_witness_target_invalid_in_single_valid_b(self):
        base = self._base_prosecutor()
        gate = {
            "quorum": "single_valid_b",
            "mode": "degraded",
            "valid_witnesses": ["witness_b"],
            "invalid_witnesses": ["witness_a"],
        }
        base["challenges"][0]["witness_target"] = "witness_a"
        with self.assertRaisesRegex(SchemaValidationError, "not permitted by the current witness quorum"):
            validate_prosecutor(base, witness_gate=gate)

    def test_prosecutor_witness_target_invalid_in_single_valid_a(self):
        base = self._base_prosecutor()
        gate = {
            "quorum": "single_valid_a",
            "mode": "degraded",
            "valid_witnesses": ["witness_a"],
            "invalid_witnesses": ["witness_b"],
        }
        base["challenges"][0]["witness_target"] = "witness_b"
        with self.assertRaisesRegex(SchemaValidationError, "not permitted by the current witness quorum"):
            validate_prosecutor(base, witness_gate=gate)

    def test_prosecutor_witness_target_valid_in_both_valid(self):
        base = self._base_prosecutor()
        gate = {
            "quorum": "both_valid",
            "mode": "normal",
            "valid_witnesses": ["witness_a", "witness_b"],
            "invalid_witnesses": [],
        }
        for target in ("witness_a", "witness_b", "both", "final_question"):
            base["challenges"][0]["witness_target"] = target
            validate_prosecutor(base, witness_gate=gate)

    def test_prosecutor_witness_target_valid_in_single_valid_b(self):
        base = self._base_prosecutor()
        gate = {
            "quorum": "single_valid_b",
            "mode": "degraded",
            "valid_witnesses": ["witness_b"],
            "invalid_witnesses": ["witness_a"],
        }
        for target in ("witness_b", "both", "final_question"):
            base["challenges"][0]["witness_target"] = target
            validate_prosecutor(base, witness_gate=gate)

    def test_prosecutor_witness_target_valid_in_single_valid_a(self):
        base = self._base_prosecutor()
        gate = {
            "quorum": "single_valid_a",
            "mode": "degraded",
            "valid_witnesses": ["witness_a"],
            "invalid_witnesses": ["witness_b"],
        }
        for target in ("witness_a", "both", "final_question"):
            base["challenges"][0]["witness_target"] = target
            validate_prosecutor(base, witness_gate=gate)

    def test_adjudication_repeated_phrase_ambiguous_edit_rejected(self):
        """Ambiguous repeated-span edits must be rejected; model must use unique spans."""
        base_witness = "light appears. light is good."
        decision = {
            "status": "corrected",
            "base_witness": "a",
            "edits": [{"old": "light", "new": "lux", "reason": "Latin term", "evidence_ids": []}],
            "summary": "Fix term",
            "coverage": {"all_clauses_accounted_for": True, "omissions_corrected": []},
            "findings": [],
            "unresolved_issues": [],
            "human_review_requests": [],
            "evidence_requests": [],
            "decision_basis": [],
        }
        with self.assertRaisesRegex(SchemaValidationError, "must match the evolving base exactly once; found 2"):
            expand_adjudication_wire(decision, witness_a=base_witness, witness_b="irrelevant", allowed_base_witnesses=["a"])

    def test_adjudication_repeated_phrase_disambiguated_edit_accepted(self):
        """Disambiguated repeated-span edits (with sufficient context) must be accepted."""
        base_witness = "The man saw the light. The light was bright."
        decision = {
            "status": "corrected",
            "base_witness": "a",
            "edits": [{"old": "The man saw the light.", "new": "The man beheld the light.", "reason": "Precise verb", "evidence_ids": []}],
            "summary": "Fix verb",
            "coverage": {"all_clauses_accounted_for": True, "omissions_corrected": []},
            "findings": [],
            "unresolved_issues": [],
            "human_review_requests": [],
            "evidence_requests": [],
            "decision_basis": [],
        }
        result = expand_adjudication_wire(decision, witness_a=base_witness, witness_b="irrelevant", allowed_base_witnesses=["a"])
        self.assertEqual(result["final_draft"], "The man beheld the light. The light was bright.")
        self.assertEqual(len(result["coverage"]["applied_edits"]), 1)

    def test_adjudication_sequential_edits_evolving_base(self):
        """Sequential edits apply against the evolving base, not the original."""
        base_witness = "He did not come. He has not arrived."
        decision = {
            "status": "corrected",
            "base_witness": "a",
            "edits": [
                {"old": "He did not come.", "new": "He did not arrive.", "reason": "Consistent verb", "evidence_ids": []},
                {"old": "He has not arrived.", "new": "He has not come.", "reason": "Second verb aligned", "evidence_ids": []},
            ],
            "summary": "Align verbs",
            "coverage": {"all_clauses_accounted_for": True, "omissions_corrected": []},
            "findings": [],
            "unresolved_issues": [],
            "human_review_requests": [],
            "evidence_requests": [],
            "decision_basis": [],
        }
        result = expand_adjudication_wire(decision, witness_a=base_witness, witness_b="irrelevant", allowed_base_witnesses=["a"])
        self.assertEqual(result["final_draft"], "He did not arrive. He has not come.")
        self.assertEqual(len(result["coverage"]["applied_edits"]), 2)
        # Verify second edit matched evolving base (after first edit)
        applied = result["coverage"]["applied_edits"]
        self.assertEqual(applied[0]["application_order"], 0)
        self.assertEqual(applied[1]["application_order"], 1)

    def test_adjudication_sequential_edits_stale_reference_rejected(self):
        """Sequential edits using stale (original) reference must be rejected."""
        # "C" appears twice in original, but only once in evolving base after first edit
        base_witness = "A C B C"
        decision = {
            "status": "corrected",
            "base_witness": "a",
            "edits": [
                {"old": "B", "new": "X", "reason": "Fix B", "evidence_ids": []},
                {"old": "C", "new": "Y", "reason": "Fix C", "evidence_ids": []},
            ],
            "summary": "Fix",
            "coverage": {"all_clauses_accounted_for": True, "omissions_corrected": []},
            "findings": [],
            "unresolved_issues": [],
            "human_review_requests": [],
            "evidence_requests": [],
            "decision_basis": [],
        }
        # After first edit: "A C X C" -> "C" appears twice (found 2) -> rejected
        with self.assertRaisesRegex(SchemaValidationError, "must match the evolving base exactly once; found 2"):
            expand_adjudication_wire(decision, witness_a=base_witness, witness_b="irrelevant", allowed_base_witnesses=["a"])

    def test_adjudication_sequential_edits_unique_context_accepted(self):
        """Sequential edits with unique context in evolving base are accepted."""
        base_witness = "A C B D C"
        decision = {
            "status": "corrected",
            "base_witness": "a",
            "edits": [
                {"old": "B", "new": "X", "reason": "Fix B", "evidence_ids": []},
                {"old": "D C", "new": "Y Z", "reason": "Fix D C", "evidence_ids": []},
            ],
            "summary": "Fix",
            "coverage": {"all_clauses_accounted_for": True, "omissions_corrected": []},
            "findings": [],
            "unresolved_issues": [],
            "human_review_requests": [],
            "evidence_requests": [],
            "decision_basis": [],
        }
        # After first edit: "A C X D C" -> "D C" occurs once
        result = expand_adjudication_wire(decision, witness_a=base_witness, witness_b="irrelevant", allowed_base_witnesses=["a"])
        self.assertEqual(result["final_draft"], "A C X Y Z")
        self.assertEqual(len(result["coverage"]["applied_edits"]), 2)


if __name__ == "__main__":
    unittest.main()
