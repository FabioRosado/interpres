from __future__ import annotations

import unittest

from interpres.challenge import apply_mutation
from interpres.checks import run_deterministic_checks, run_final_draft_checks


class ChecksTest(unittest.TestCase):
    def _chunk(self, latin: str):
        return {
            "target_latin": latin,
            "source_spans": [{"role": "target", "page": "1A"}],
            "page_markers": [{"page": "1A"}],
            "source": {"pages": ["1A"]},
            "annotations": [],
        }

    def test_negation_and_number_signals(self):
        result = run_deterministic_checks(
            self._chunk("non venit cum tribusque pueris"),
            "he came with four boys",
            "he did not come with three boys",
        )
        warnings = {(item["check"], item["evidence"].get("witness")) for item in result["findings"] if item["status"] == "warning"}
        self.assertIn(("negation", "witness_a"), warnings)
        self.assertIn(("number_words", "witness_a"), warnings)
        self.assertNotIn(("negation", "witness_b"), warnings)

    def test_page_integrity_failure(self):
        chunk = self._chunk("venit")
        chunk["page_markers"] = [{"page": "2A"}]
        result = run_deterministic_checks(chunk, "he came", "he came")
        page = next(item for item in result["findings"] if item["check"] == "page_marker_integrity")
        self.assertEqual(page["status"], "failure")

    def test_roman_numeral_date_accepts_roman_or_arabic_equivalent(self):
        result = run_deterministic_checks(
            self._chunk("anno XXXVIII venit"),
            "he came in that year",
            "he came in the year 38",
        )
        roman = [
            item
            for item in result["findings"]
            if item["check"] == "roman_numerals"
        ]
        self.assertEqual(roman[0]["status"], "warning")
        self.assertEqual(roman[0]["evidence"]["missing"][0]["arabic"], 38)
        self.assertEqual(roman[1]["status"], "pass")

    def test_additive_latin_number_accepts_english_total(self):
        result = run_deterministic_checks(
            self._chunk("decem et octo volumina"),
            "eighteen volumes",
            "18 volumes",
        )
        number_words = [
            item
            for item in result["findings"]
            if item["check"] == "number_words"
        ]
        self.assertEqual([item["status"] for item in number_words], ["pass", "pass"])
        self.assertEqual(
            number_words[0]["evidence"]["composite_equivalents"],
            [{"latin": "decem et octo", "value": 18}],
        )

    def test_curated_inflected_name_rejects_paul_for_paulae(self):
        result = run_deterministic_checks(
            self._chunk("matri tuae Paulae"),
            "to your mother Paul",
            "to your mother Paula",
        )
        curated = [
            item
            for item in result["findings"]
            if item["check"] == "proper_names"
            and item["evidence"].get("curated_mismatches")
        ]
        self.assertEqual(len(curated), 1)
        self.assertEqual(curated[0]["status"], "warning")
        self.assertEqual(curated[0]["severity"], "high")
        self.assertEqual(curated[0]["evidence"]["witness"], "witness_a")
        self.assertEqual(
            curated[0]["evidence"]["curated_mismatches"],
            [{"source_form": "paulae", "expected_any": ["paula"]}],
        )

    def test_electri_rejects_observed_lightning_rendering(self):
        result = run_deterministic_checks(
            self._chunk("electri esse in medio venti"),
            "electrum is in the midst of the wind",
            "lightning is in the midst of the wind",
        )
        traps = [
            item
            for item in result["findings"]
            if item["check"] == "known_translation_trap"
        ]
        self.assertEqual(len(traps), 1)
        self.assertEqual(traps[0]["severity"], "high")
        self.assertEqual(traps[0]["evidence"]["witness"], "witness_b")
        self.assertEqual(
            traps[0]["evidence"]["matched_wrong_rendering"], "lightning"
        )

    def test_chunk5_degraded_quorum_preserves_valid_b_lightning_trap(self):
        gate = {
            "quorum": "single_valid_b",
            "mode": "degraded",
            "valid_witnesses": ["witness_b"],
            "invalid_witnesses": ["witness_a"],
        }
        result = run_deterministic_checks(
            self._chunk("electri esse in medio venti"),
            "electrum is in the midst of the wind",
            "lightning is in the midst of the wind",
            witness_gate=gate,
        )
        trap = next(
            item
            for item in result["findings"]
            if item["check"] == "known_translation_trap"
        )
        self.assertEqual(trap["evidence"]["witness"], "witness_b")
        self.assertEqual(
            trap["evidence"]["witness_validation_role"],
            "eligible_proposal",
        )
        self.assertTrue(trap["evidence"]["may_corroborate"])
        invalid_a_finding = next(
            item
            for item in result["findings"]
            if item.get("evidence", {}).get("witness") == "witness_a"
        )
        self.assertEqual(
            invalid_a_finding["evidence"]["witness_validation_role"],
            "invalid_witness_clue_not_evidence",
        )
        self.assertFalse(invalid_a_finding["evidence"]["may_corroborate"])

    def test_final_draft_checks_block_verified_phrase_traps(self):
        result = run_final_draft_checks(
            self._chunk(
                "concaluit cor meum; silui a bonis; quatuor plagas mundi"
            ),
            (
                "my heart grew cold; I was silent among the good; "
                "the four corners of the world"
            ),
        )
        traps = [
            item
            for item in result["findings"]
            if item["check"] == "known_translation_trap"
        ]
        self.assertEqual(len(traps), 3)
        self.assertTrue(all(item["severity"] == "high" for item in traps))

    def test_final_draft_blocks_observed_chunk5_latin_copy(self):
        copied = (
            "electri esse in medio venti vel spiritus Ergo hoc sentiendum quod "
            "in medio ignis et tormentorum Dei electri similitudo sit quod est "
            "auro argentoque pretiosius ut post judicium atque tormenta quae "
            "patientibus tristia videntur et dura pretiosior electri fulgor "
            "appareat dum providentia Dei omnia gubernantur et quae putatur "
            "poena medicina est"
        )
        result = run_final_draft_checks(
            self._chunk(copied),
            copied + ". And the four living creatures appeared.",
        )
        finding = next(
            item
            for item in result["findings"]
            if item["check"] == "source_latin_copy"
        )
        self.assertEqual(finding["status"], "warning")
        self.assertEqual(finding["severity"], "high")
        self.assertGreaterEqual(finding["evidence"]["copied_word_count"], 50)

    def test_large_adjudicator_rewrite_requires_human_review_gate(self):
        old = " ".join(f"english{index}" for index in range(73))
        new = " ".join(f"replacement{index}" for index in range(51))
        result = run_final_draft_checks(
            self._chunk("latin source"),
            new,
            applied_edits=[{"old": old, "new": new, "reason": "rewrite"}],
        )
        finding = next(
            item
            for item in result["findings"]
            if item["check"] == "adjudicator_edit_scope"
        )
        self.assertEqual(finding["status"], "warning")
        self.assertEqual(finding["severity"], "high")
        self.assertEqual(
            finding["evidence"]["oversized_edits"][0]["old_word_count"], 73
        )

    def test_many_small_edits_trigger_cumulative_word_and_ratio_guard(self):
        base = " ".join(["verbum"] * 200)
        edits = [
            {"old": " ".join(["verbum"] * 10), "new": " ".join(["word"] * 10)}
            for _ in range(10)
        ]
        result = run_final_draft_checks(
            self._chunk("venit"),
            "he came",
            applied_edits=edits,
            base_witness_text=base,
            edit_budget={
                "max_words_per_edit": 48,
                "max_cumulative_words": 96,
                "max_base_replacement_ratio": 0.25,
            },
        )
        by_check = {item["check"]: item for item in result["findings"]}
        self.assertEqual(by_check["adjudicator_edit_scope"]["status"], "pass")
        cumulative = by_check["adjudicator_cumulative_edit_scope"]
        self.assertEqual(cumulative["status"], "warning")
        self.assertEqual(cumulative["severity"], "high")
        self.assertEqual(cumulative["evidence"]["cumulative_edit_words"], 100)
        self.assertEqual(cumulative["evidence"]["base_replacement_ratio"], 0.5)

        small = run_final_draft_checks(
            self._chunk("venit"),
            "he came",
            applied_edits=[{"old": "verbum unum", "new": "two words"}],
            base_witness_text=" ".join(["verbum"] * 100),
        )
        small_check = next(
            item for item in small["findings"]
            if item["check"] == "adjudicator_cumulative_edit_scope"
        )
        self.assertEqual(small_check["status"], "pass")

    def test_large_percentage_replacement_blocks_below_cumulative_word_limit(self):
        base_words = [f"base{index}" for index in range(20)]
        old = " ".join(base_words[:6])
        result = run_final_draft_checks(
            self._chunk("venit"),
            "he came",
            applied_edits=[
                {
                    "old": old,
                    "new": "one two three four five six",
                    "reason": "fixture",
                }
            ],
            base_witness_text=" ".join(base_words),
            edit_budget={
                "max_words_per_edit": 48,
                "max_cumulative_words": 96,
                "max_base_replacement_ratio": 0.25,
            },
        )
        by_check = {item["check"]: item for item in result["findings"]}
        self.assertEqual(by_check["adjudicator_edit_scope"]["status"], "pass")
        cumulative = by_check["adjudicator_cumulative_edit_scope"]
        self.assertEqual(cumulative["status"], "warning")
        self.assertEqual(cumulative["evidence"]["cumulative_edit_words"], 6)
        self.assertEqual(cumulative["evidence"]["base_replacement_ratio"], 0.3)


class ChallengeMutationTest(unittest.TestCase):
    def test_supported_mutations(self):
        self.assertNotIn("not", apply_mutation("he did not come", "remove_negation"))
        self.assertIn("four", apply_mutation("the three boys", "alter_number"))
        self.assertTrue(apply_mutation("He came.", "unsupported_certainty").startswith("Certainly"))
        swapped = apply_mutation("John saw Mary", "swap_subject_object", {"subject": "John", "object": "Mary"})
        self.assertEqual(swapped, "Mary saw John")
        self.assertIn("Psalm 23", apply_mutation("He came.", "invent_scripture_allusion"))


if __name__ == "__main__":
    unittest.main()
