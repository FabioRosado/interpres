from __future__ import annotations

import json
import unittest

from interpres.prompts import witness_prompt
from interpres.witnesses import (
    estimate_witness_output_budget,
    parse_plain_witness_proposal,
    parse_witness_proposal,
    validate_witness_record,
    witness_contract_schema,
    witness_gate_receipt,
)


def chunk(chunk_id: str = "book01-pl-0020D--pl-0021C-da3d16f9fd"):
    return {
        "chunk_id": chunk_id,
        "target_latin": "electri esse in medio venti. Liber generationis Jesu",
        "context_before": "speciem vel visionem",
        "context_after": "Christi, filii David, filii Abraham.",
        "source_units": [
            {"source_unit_id": "book01-pl-0020D", "text": "electri esse in medio venti."},
            {"source_unit_id": "book01-pl-0021C", "text": "Liber generationis Jesu"},
        ],
    }


def record(raw: str, *, limit: int, generated: int, proposal=None):
    current = chunk()
    return {
        "stage": "witness_b",
        "cache_key": "fixture",
        "status": "complete",
        "cache_material": {"inputs": {"target_latin": current["target_latin"]}},
        "model": {
            "provider": "ollama",
            "model": "fixture",
            "max_output_tokens": limit,
        },
        "provider_attempts": [
            {
                "provider": "ollama",
                "outcome": "complete",
                "done": True,
                "done_reason": "stop",
                "eval_count": generated,
            }
        ],
        "raw_response": raw,
        "output": proposal or parse_witness_proposal(raw),
    }


class WitnessBoundaryRegressionTest(unittest.TestCase):
    def test_chunk5_observed_mistral_response_is_raw_model_output_not_ui_formatting(self):
        raw = (
            "Here is the translation of the target Latin passage:\n\n---\n\n"
            "But we must understand that electrum is precious. The book of the "
            "generation of Jesus Christ, the son of David.\n\n---"
        )
        persisted = record(raw, limit=1800, generated=869)
        receipt = validate_witness_record(chunk(), persisted, witness="witness_b")

        self.assertEqual(persisted["raw_response"].strip(), persisted["output"]["translation"])
        self.assertIn("witness_response_contract", receipt["blocking_failures"])
        self.assertIn("no_commentary_or_fences", receipt["blocking_failures"])
        completion = next(
            item for item in receipt["checks"] if item["check"] == "provider_completion"
        )
        headroom = next(
            item for item in receipt["checks"] if item["check"] == "output_token_headroom"
        )
        self.assertEqual(completion["status"], "pass")
        self.assertEqual(headroom["status"], "pass")
        self.assertEqual(headroom["detail"], {"generated_tokens": 869, "configured_limit": 1800})
        self.assertFalse(receipt["eligible_as_adjudicator_base"])

    def test_chunk4_observed_plain_response_cannot_satisfy_coverage_contract(self):
        current = chunk("book01-pl-0019D--pl-0020C-bd858d24fd")
        current["target_latin"] = "Hebraicum RUA accipitur. ut putaremus speciem vel visionem"
        current["source_units"] = [
            {"source_unit_id": "book01-pl-0019D", "text": "Hebraicum RUA accipitur."},
            {"source_unit_id": "book01-pl-0020C", "text": "ut putaremus speciem vel visionem"},
        ]
        persisted = record(
            "The Hebrew word RUA is understood. We might think it the appearance "
            "or vision of electrum in the wind, which is light to believers.",
            limit=1800,
            generated=911,
        )
        persisted["cache_material"]["inputs"]["target_latin"] = current["target_latin"]
        receipt = validate_witness_record(current, persisted, witness="witness_b")

        self.assertIn("witness_response_contract", receipt["blocking_failures"])
        self.assertIn("expected_source_units", receipt["blocking_failures"])
        self.assertFalse(receipt["valid"])

    def test_valid_full_context_contract_has_ordered_boundary_receipts(self):
        current = chunk()
        translation = "Electrum is in the wind. The book of the generation of Jesus"
        contract = {
            "translation": translation,
            "source_mappings": [
                {
                    "source_unit_id": "book01-pl-0020D",
                    "english_end_quote": "Electrum is in the wind.",
                },
                {
                    "source_unit_id": "book01-pl-0021C",
                    "english_end_quote": "The book of the generation of Jesus",
                },
            ],
            "omissions": [],
            "uncertainties": [],
        }
        raw = json.dumps(contract)
        receipt = validate_witness_record(
            current,
            record(raw, limit=1800, generated=80),
            witness="witness_b",
        )
        self.assertTrue(receipt["valid"])
        self.assertTrue(receipt["eligible_as_adjudicator_base"])

    def test_explicit_witness_quorum_states_and_permissions(self):
        cases = [
            (True, True, "both_valid", "normal", ["a", "b"], True),
            (True, False, "single_valid_a", "degraded", ["a"], False),
            (False, True, "single_valid_b", "degraded", ["b"], False),
            (False, False, "both_invalid", "blocked", [], False),
        ]
        for valid_a, valid_b, quorum, mode, allowed, automatic in cases:
            with self.subTest(quorum=quorum):
                gate = witness_gate_receipt(
                    {
                        "witness_a": {
                            "valid": valid_a,
                            "blocking_failures": [] if valid_a else ["omission"],
                        },
                        "witness_b": {
                            "valid": valid_b,
                            "blocking_failures": [] if valid_b else ["contract"],
                        },
                    }
                )
                self.assertEqual(gate["quorum"], quorum)
                self.assertEqual(gate["mode"], mode)
                self.assertEqual(gate["allowed_base_witnesses"], allowed)
                self.assertEqual(gate["automatic_acceptance_allowed"], automatic)
                self.assertEqual(gate["proceed"], quorum != "both_invalid")
                self.assertFalse(gate["invalid_witness_may_support_evidence_grade"])

    def test_segment_contract_emits_translation_once(self):
        segment = witness_contract_schema(chunk())["properties"]["segments"][
            "items"
        ]
        self.assertEqual(
            segment["required"], ["source_unit_id", "translation"]
        )
        self.assertNotIn("source_mappings", witness_contract_schema(chunk())["properties"])
        self.assertNotIn("translation", witness_contract_schema(chunk())["properties"])

    def test_segment_contract_derives_continuous_translation_and_offsets(self):
        current = chunk()
        contract = {
            "segments": [
                {
                    "source_unit_id": "book01-pl-0020D",
                    "translation": "Electrum is in the wind.",
                },
                {
                    "source_unit_id": "book01-pl-0021C",
                    "translation": "The book of the generation of Jesus",
                },
            ],
            "omissions": [],
            "uncertainties": [],
        }
        persisted = record(json.dumps(contract), limit=1800, generated=80)
        persisted["cache_material"]["inputs"].update(
            {"request_context_before": "", "request_context_after": ""}
        )
        receipt = validate_witness_record(current, persisted, witness="witness_b")
        self.assertTrue(receipt["valid"])
        self.assertEqual(
            persisted["output"]["translation"],
            "Electrum is in the wind. The book of the generation of Jesus",
        )
        spans = next(
            item["detail"]["spans"]
            for item in receipt["checks"]
            if item["check"] == "ordered_translation_mappings"
        )
        self.assertEqual([item["source_unit_id"] for item in spans], [
            "book01-pl-0020D", "book01-pl-0021C"
        ])
        self.assertEqual(spans[0]["start"], 0)
        self.assertEqual(spans[-1]["end"], len(persisted["output"]["translation"]))

    def test_live_chunk5_style_abbreviated_or_latin_segments_fail(self):
        current = chunk()
        contract = {
            "segments": [
                {
                    "source_unit_id": "book01-pl-0020D",
                    "translation": "Electrum is in the wind.",
                },
                {
                    "source_unit_id": "book01-pl-0021C",
                    "translation": "Liber generationis Jesu",
                },
            ],
            "omissions": [],
            "uncertainties": [],
        }
        persisted = record(json.dumps(contract), limit=1500, generated=80)
        persisted["cache_material"]["inputs"].update(
            {"request_context_before": "", "request_context_after": ""}
        )
        receipt = validate_witness_record(current, persisted, witness="witness_a")
        self.assertIn("per_source_unit_copy_signal", receipt["blocking_failures"])

    def test_live_chunk5_missing_terminal_jesus_and_second_matthew_fails(self):
        current = {
            **chunk(),
            "target_latin": (
                "quos nos in commentariorum Matthaei secuti sumus: Matthaei, "
                "quod quasi hominem descripserit: Liber generationis Jesu"
            ),
            "source_units": [
                {
                    "source_unit_id": "book01-pl-0021C",
                    "text": (
                        "quos nos in commentariorum Matthaei secuti sumus: "
                        "Matthaei, quod quasi hominem descripserit: "
                        "Liber generationis Jesu"
                    ),
                }
            ],
        }
        contract = {
            "segments": [
                {
                    "source_unit_id": "book01-pl-0021C",
                    "translation": "Some designate Matthew, because he described a man:",
                }
            ],
            "omissions": [],
            "uncertainties": [],
        }
        persisted = record(json.dumps(contract), limit=1500, generated=80)
        persisted["cache_material"]["inputs"].update(
            {
                "target_latin": current["target_latin"],
                "request_context_before": "",
                "request_context_after": "",
            }
        )
        receipt = validate_witness_record(current, persisted, witness="witness_a")
        self.assertIn(
            "per_source_unit_name_multiplicity", receipt["blocking_failures"]
        )
        detail = next(
            item["detail"]
            for item in receipt["checks"]
            if item["check"] == "per_source_unit_name_multiplicity"
        )
        self.assertEqual(
            {item["source_form"] for item in detail["segments"][0]["missing"]},
            {"matthaei", "jesu"},
        )

    def test_plain_v4_chunk5_name_multiplicity_catches_observed_json_omission(self):
        current = {
            **chunk(),
            "target_latin": (
                "quos nos in commentariorum Matthaei secuti sumus: Matthaei, "
                "quod quasi hominem descripserit: Liber generationis Jesu"
            ),
            "source_units": [
                {
                    "source_unit_id": "book01-pl-0021C",
                    "text": (
                        "quos nos in commentariorum Matthaei secuti sumus: "
                        "Matthaei, quod quasi hominem descripserit: "
                        "Liber generationis Jesu"
                    ),
                }
            ],
        }
        raw = "Some think these animals designate Matthew: The book of Jesus"
        persisted = record(
            raw,
            limit=1500,
            generated=690,
            proposal=parse_plain_witness_proposal(raw),
        )
        persisted["cache_material"]["inputs"].update(
            {
                "target_latin": current["target_latin"],
                "request_context_before": "",
                "request_context_after": "",
            }
        )
        receipt = validate_witness_record(current, persisted, witness="witness_a")
        self.assertIn("whole_target_name_multiplicity", receipt["blocking_failures"])

    def test_complete_plain_v4_proposal_can_pass_without_provider_mappings(self):
        current = chunk()
        raw = "Electrum is in the midst of the wind. The book of the generation of Jesus"
        persisted = record(
            raw,
            limit=1500,
            generated=80,
            proposal=parse_plain_witness_proposal(raw),
        )
        persisted["cache_material"]["inputs"].update(
            {"request_context_before": "", "request_context_after": ""}
        )
        receipt = validate_witness_record(current, persisted, witness="witness_a")
        self.assertTrue(receipt["valid"])
        mapping_checks = {
            item["check"]: item
            for item in receipt["checks"]
            if item["check"]
            in {"expected_source_units", "ordered_translation_mappings"}
        }
        self.assertEqual(mapping_checks["expected_source_units"]["status"], "failure")
        self.assertFalse(mapping_checks["expected_source_units"]["blocking"])
        self.assertFalse(mapping_checks["ordered_translation_mappings"]["blocking"])

    def test_plain_v4_does_not_silently_accept_json_envelope(self):
        raw = json.dumps(
            {
                "translation": (
                    "Electrum is in the wind. The book of the generation of Jesus"
                )
            }
        )
        persisted = record(
            raw,
            limit=1500,
            generated=80,
            proposal=parse_plain_witness_proposal(raw),
        )
        persisted["cache_material"]["inputs"].update(
            {"request_context_before": "", "request_context_after": ""}
        )
        receipt = validate_witness_record(chunk(), persisted, witness="witness_a")
        self.assertIn("plain_text_response_shape", receipt["blocking_failures"])

    def test_modernization_witness_blocks_archaic_introduction(self):
        current = {
            **chunk(),
            "source_text": "For he says that God has made this manifest and will show mercy.",
            "target_latin": "For he says that God has made this manifest and will show mercy.",
            "task_type": "modernization",
            "project": {"task_type": "modernization"},
            "checks": {
                "archaic_residue_terms": ["saith", "hath", "shew"],
            },
            "source_units": [
                {
                    "source_unit_id": "book01-homily-001-section-001",
                    "text": "For he says that God has made this manifest and will show mercy.",
                }
            ],
        }
        raw = "For he saith that God hath made this manifest and will shew mercy."
        persisted = record(
            raw,
            limit=1500,
            generated=80,
            proposal=parse_plain_witness_proposal(raw),
        )
        persisted["cache_material"]["inputs"] = {
            "source_text": current["source_text"],
            "request_context_before": "",
            "request_context_after": "",
        }

        receipt = validate_witness_record(current, persisted, witness="witness_a")

        self.assertIn("no_archaic_introduction", receipt["blocking_failures"])
        detail = next(
            item["detail"]
            for item in receipt["checks"]
            if item["check"] == "no_archaic_introduction"
        )
        self.assertEqual(detail["introduced_terms"], ["hath", "saith", "shew"])
        self.assertFalse(receipt["eligible_as_adjudicator_base"])

    def test_modernization_witness_blocks_quoted_archaic_introduction(self):
        current = {
            **chunk(),
            "source_text": '"He says"',
            "target_latin": '"He says"',
            "task_type": "modernization",
            "project": {"task_type": "modernization"},
            "checks": {
                "archaic_residue_terms": ["saith"],
            },
            "source_units": [
                {
                    "source_unit_id": "book01-homily-001-section-001",
                    "text": '"He says"',
                }
            ],
        }
        raw = '"He saith"'
        persisted = record(
            raw,
            limit=1500,
            generated=80,
            proposal=parse_plain_witness_proposal(raw),
        )
        persisted["cache_material"]["inputs"] = {
            "source_text": current["source_text"],
            "request_context_before": "",
            "request_context_after": "",
        }

        receipt = validate_witness_record(current, persisted, witness="witness_a")

        self.assertIn("no_archaic_introduction", receipt["blocking_failures"])

    def test_repeated_final_marker_is_disambiguated_by_output_boundary(self):
        current = {
            **chunk(),
            "target_latin": "prima visio. ultima visio.",
            "source_units": [
                {"source_unit_id": "u1", "text": "prima visio."},
                {"source_unit_id": "u2", "text": "ultima visio."},
            ],
        }
        translation = "The first vision. The final vision"
        contract = {
            "translation": translation,
            "source_mappings": [
                {"source_unit_id": "u1", "english_end_quote": "vision."},
                {"source_unit_id": "u2", "english_end_quote": "vision"},
            ],
            "omissions": [],
            "uncertainties": [],
        }
        persisted = record(json.dumps(contract), limit=1800, generated=50)
        persisted["cache_material"]["inputs"]["target_latin"] = current[
            "target_latin"
        ]
        receipt = validate_witness_record(current, persisted, witness="witness_b")
        self.assertTrue(receipt["valid"])

    def test_genuinely_ambiguous_intermediate_marker_fails_closed(self):
        current = {
            **chunk(),
            "target_latin": "prima visio. altera visio. secunda pars. ultima pars.",
            "source_units": [
                {"source_unit_id": "u1", "text": "prima visio."},
                {"source_unit_id": "u2", "text": "altera visio. secunda pars."},
                {"source_unit_id": "u3", "text": "ultima pars."},
            ],
        }
        contract = {
            "translation": "First vision. Another vision. Second part. Final part.",
            "source_mappings": [
                {"source_unit_id": "u1", "english_end_quote": "vision"},
                {"source_unit_id": "u2", "english_end_quote": "Second part."},
                {"source_unit_id": "u3", "english_end_quote": "Final part."},
            ],
            "omissions": [],
            "uncertainties": [],
        }
        persisted = record(json.dumps(contract), limit=1800, generated=60)
        persisted["cache_material"]["inputs"]["target_latin"] = current[
            "target_latin"
        ]
        receipt = validate_witness_record(current, persisted, witness="witness_b")
        self.assertIn("ordered_translation_mappings", receipt["blocking_failures"])

    def test_chunk4_style_context_before_translation_is_blocked(self):
        current = {
            **chunk(),
            "target_latin": "Hebraicum RUA spiritus anima vel ventus accipitur.",
            "context_before": (
                "Aquila ventum turbinis, Symmachus flatum, Theodotion spiritum "
                "tempestatis interpretatur."
            ),
            "context_after": "",
            "source_units": [
                {
                    "source_unit_id": "target-u1",
                    "text": "Hebraicum RUA spiritus anima vel ventus accipitur.",
                }
            ],
        }
        translation = (
            "Aquila calls it a whirlwind, while Symmachus and Theodotion call it "
            "the breath and spirit of a storm."
        )
        contract = {
            "translation": translation,
            "source_mappings": [
                {
                    "source_unit_id": "target-u1",
                    "english_end_quote": "spirit of a storm.",
                }
            ],
            "omissions": [],
            "uncertainties": [],
        }
        persisted = record(json.dumps(contract), limit=1800, generated=80)
        persisted["cache_material"]["inputs"]["target_latin"] = current[
            "target_latin"
        ]
        receipt = validate_witness_record(current, persisted, witness="witness_a")
        self.assertIn("no_context_leakage", receipt["blocking_failures"])
        leakage = next(
            item["detail"]
            for item in receipt["checks"]
            if item["check"] == "no_context_leakage"
        )
        self.assertGreaterEqual(leakage["matched_distinctive_anchor_count"], 2)
        self.assertFalse(receipt["eligible_as_adjudicator_base"])

    def test_missing_or_context_only_source_id_fails_coverage(self):
        current = chunk()
        translation = "Electrum is in the wind. The book concerns Jesus"
        for ids in (
            ["book01-pl-0020D"],
            ["book01-pl-0020D", "context-after-only"],
        ):
            contract = {
                "translation": translation,
                "source_mappings": [
                    {
                        "source_unit_id": unit_id,
                        "english_end_quote": (
                            "in the wind." if index == 0 else "concerns Jesus"
                        ),
                    }
                    for index, unit_id in enumerate(ids)
                ],
                "omissions": [],
                "uncertainties": [],
            }
            receipt = validate_witness_record(
                current,
                record(json.dumps(contract), limit=1800, generated=80),
                witness="witness_b",
            )
            self.assertIn("expected_source_units", receipt["blocking_failures"])

    def test_meta_commentary_inside_translation_is_not_silently_stripped(self):
        current = {
            **chunk(),
            "target_latin": "electri esse",
            "source_units": [{"source_unit_id": "u1", "text": "electri esse"}],
        }
        translation = "Here is the translation of the target Latin passage: electrum exists"
        contract = {
            "translation": translation,
            "source_mappings": [
                {"source_unit_id": "u1", "english_end_quote": "electrum exists"}
            ],
            "omissions": [],
            "uncertainties": [],
        }
        persisted = record(json.dumps(contract), limit=1800, generated=50)
        persisted["cache_material"]["inputs"]["target_latin"] = current[
            "target_latin"
        ]
        receipt = validate_witness_record(current, persisted, witness="witness_b")
        self.assertIn("no_commentary_or_fences", receipt["blocking_failures"])
        self.assertEqual(persisted["output"]["translation"], translation)

    def test_compact_contract_budget_fits_chunk5_and_preflight_blocks_small_limit(self):
        current = chunk()
        prompt = witness_prompt(current)
        fits = estimate_witness_output_budget(
            current, prompt, max_output_tokens=1500, context_window=8192
        )
        blocked = estimate_witness_output_budget(
            current, prompt, max_output_tokens=100, context_window=8192
        )
        self.assertTrue(fits["proceed"])
        self.assertLess(fits["max_compact_contract_tokens"], 300)
        self.assertFalse(blocked["proceed"])
        self.assertIn("output budget", blocked["failure_reason"])

    def test_prompt_has_closed_target_and_read_only_boundaries(self):
        current = chunk()
        prompt = witness_prompt(current)
        self.assertIn("</TARGET_LATIN>", prompt)
        self.assertNotIn("<SOURCE_UNIT", prompt)
        self.assertIn(current["target_latin"], prompt)
        self.assertNotIn("speciem vel visionem", prompt)
        self.assertNotIn("filii David", prompt)
        self.assertNotIn("READ_ONLY_CONTEXT", prompt)
        self.assertIn("Do not return JSON", prompt)
        self.assertIn("Do not infer or continue text beyond", prompt)


if __name__ == "__main__":
    unittest.main()
