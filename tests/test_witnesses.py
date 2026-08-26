from __future__ import annotations

import json
import unittest

from jerome_pipeline.prompts import witness_prompt
from jerome_pipeline.witnesses import (
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
        self.assertIn("structured_contract", receipt["blocking_failures"])
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

        self.assertIn("structured_contract", receipt["blocking_failures"])
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

    def test_single_valid_witness_fails_closed_before_prosecution(self):
        gate = witness_gate_receipt(
            {
                "witness_a": {"valid": True, "blocking_failures": []},
                "witness_b": {"valid": False, "blocking_failures": ["structured_contract"]},
            }
        )
        self.assertEqual(gate["status"], "single_valid_witness")
        self.assertFalse(gate["proceed"])
        self.assertEqual(gate["allowed_base_witnesses"], ["a"])
        self.assertIn("fail_closed_before_prosecution", gate["behavior"])

    def test_compact_contract_caps_mapping_markers(self):
        mapping = witness_contract_schema(chunk())["properties"]["source_mappings"][
            "items"
        ]
        self.assertEqual(
            mapping["required"], ["source_unit_id", "english_end_quote"]
        )
        self.assertEqual(
            mapping["properties"]["english_end_quote"]["maxLength"], 100
        )
        self.assertNotIn("english_start_quote", mapping["properties"])

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

    def test_prompt_has_closed_target_and_read_only_boundaries(self):
        prompt = witness_prompt(chunk())
        self.assertIn("</READ_ONLY_CONTEXT_BEFORE>", prompt)
        self.assertIn("</TARGET_LATIN>", prompt)
        self.assertIn("</READ_ONLY_CONTEXT_AFTER>", prompt)
        self.assertIn('<SOURCE_UNIT id="book01-pl-0021C">', prompt)
        self.assertIn("never complete it from the read-only context", prompt)


if __name__ == "__main__":
    unittest.main()
