from __future__ import annotations

import unittest

from jerome_pipeline.adjudication import assess_adjudication_evidence


class AdjudicationEvidencePolicyTest(unittest.TestCase):
    def test_no_hit_receipt_cannot_support_grade_b_or_high_finding(self):
        decision = {
            "coverage": {"applied_edits": []},
            "decision_basis": [
                {
                    "grade": "B",
                    "claim": "electri is decisively electrum",
                    "evidence_ids": ["ev-observed-no-hit"],
                }
            ],
            "findings": [
                {
                    "severity": "high",
                    "resolution": "Use electrum.",
                    "evidence_ids": ["ev-observed-no-hit"],
                }
            ],
        }
        result = assess_adjudication_evidence(
            decision,
            [
                {
                    "evidence_id": "ev-observed-no-hit",
                    "status": "no_evidence_found",
                    "evidence_class": "retrieved_evidence",
                    "results": [],
                }
            ],
        )
        self.assertFalse(result["valid_strong_basis"])
        self.assertFalse(result["finding_support"][0])
        self.assertEqual(len(result["issues"]), 2)
        self.assertTrue(
            all(
                issue["invalid_receipts"][0]["status"]
                == "no_evidence_found"
                for issue in result["issues"]
            )
        )

    def test_found_non_lead_receipt_can_support_positive_claim(self):
        result = assess_adjudication_evidence(
            {
                "coverage": {"applied_edits": []},
                "decision_basis": [
                    {
                        "grade": "B",
                        "claim": "A corpus occurrence supports electri.",
                        "evidence_ids": ["ev-found"],
                    }
                ],
                "findings": [
                    {
                        "severity": "high",
                        "latin": "electri",
                        "resolution": "Correct electri.",
                        "evidence_ids": ["ev-found"],
                    }
                ],
            },
            [
                {
                    "evidence_id": "ev-found",
                    "status": "found",
                    "evidence_class": "retrieved_evidence",
                    "results": [{"text": "inspectable source"}],
                    "request": {
                        "kind": "jerome_phrase",
                        "query": "electri",
                        "reason": "Test the electri lexical finding",
                    },
                }
            ],
        )
        self.assertTrue(result["valid_strong_basis"])
        self.assertTrue(result["finding_support"][0])
        self.assertEqual(result["issues"], [])

    def test_grade_a_is_specific_and_model_label_alone_is_insufficient(self):
        decision = {
            "coverage": {"applied_edits": []},
            "decision_basis": [
                {
                    "grade": "A",
                    "claim": "The model declares the whole translation proven.",
                    "evidence_ids": [],
                }
            ],
            "findings": [
                {
                    "severity": "high",
                    "latin": "electri",
                    "resolution": "Use electrum for electri.",
                    "evidence_ids": ["det-electri"],
                },
                {
                    "severity": "high",
                    "latin": "Matthaei",
                    "resolution": "Restore an unrelated clause.",
                    "evidence_ids": [],
                },
            ],
        }
        result = assess_adjudication_evidence(
            decision,
            [],
            deterministic_findings=[
                {
                    "finding_id": "det-electri",
                    "check": "known_translation_trap",
                    "status": "warning",
                    "severity": "high",
                    "message": "electri was rendered as lightning",
                    "evidence": {
                        "source_phrase": "electri",
                        "expected": "electrum",
                    },
                }
            ],
        )
        self.assertFalse(result["basis_support"][0]["supported"])
        self.assertTrue(result["finding_support"][0])
        self.assertFalse(result["finding_support"][1])

    def test_grade_b_receipt_for_one_claim_cannot_support_another(self):
        receipt = {
            "evidence_id": "ev-electri",
            "status": "found",
            "evidence_class": "retrieved_evidence",
            "results": [{"text": "electri corpus occurrence"}],
            "request": {
                "kind": "jerome_phrase",
                "query": "electri",
                "reason": "Resolve the electri lexical issue",
            },
        }
        result = assess_adjudication_evidence(
            {
                "coverage": {"applied_edits": []},
                "decision_basis": [],
                "findings": [
                    {
                        "severity": "high",
                        "latin": "electri",
                        "resolution": "Use electrum.",
                        "evidence_ids": ["ev-electri"],
                    },
                    {
                        "severity": "high",
                        "latin": "Matthaei",
                        "resolution": "Restore a clause.",
                        "evidence_ids": ["ev-electri"],
                    },
                ],
            },
            [receipt],
        )
        self.assertTrue(result["finding_support"][0])
        self.assertFalse(result["finding_support"][1])
        self.assertEqual(
            result["issues"][0]["invalid_receipts"][0]["status"],
            "irrelevant_to_claim",
        )

    def test_unapproved_receipt_origin_cannot_support_a_positive_claim(self):
        result = assess_adjudication_evidence(
            {
                "coverage": {"applied_edits": []},
                "decision_basis": [],
                "findings": [
                    {
                        "severity": "high",
                        "latin": "electri",
                        "resolution": "Use electrum.",
                        "evidence_ids": ["ev-unapproved"],
                    }
                ],
            },
            [
                {
                    "evidence_id": "ev-unapproved",
                    "request": {
                        "kind": "web_research",
                        "query": "electri",
                        "reason": "Unverified web lead.",
                    },
                    "status": "found",
                    "evidence_class": "retrieved_evidence",
                    "results": [{"text": "unverified result"}],
                }
            ],
        )
        self.assertFalse(result["finding_support"][0])
        self.assertEqual(
            result["issues"][0]["invalid_receipts"][0]["status"],
            "found",
        )

    def test_grade_a_requires_explicit_deterministic_finding_reference(self):
        """Grade A decision_basis must cite deterministic finding_id in evidence_ids."""
        result = assess_adjudication_evidence(
            {
                "coverage": {"applied_edits": []},
                "decision_basis": [
                    {
                        "grade": "A",
                        "claim": "electri is a material term.",
                        "evidence_ids": [],
                    }
                ],
                "findings": [],
            },
            [],
            deterministic_findings=[
                {
                    "finding_id": "det-electri",
                    "check": "known_translation_trap",
                    "status": "warning",
                    "severity": "high",
                    "message": "electri was rendered as lightning",
                    "evidence": {"source_phrase": "electri", "expected": "electrum"},
                }
            ],
        )
        # No explicit reference -> unsupported
        self.assertFalse(result["basis_support"][0]["supported"])
        self.assertEqual(result["basis_support"][0]["deterministic_finding_ids"], [])

    def test_grade_a_explicit_deterministic_reference_supported(self):
        """Grade A with explicit deterministic finding_id in evidence_ids is supported."""
        result = assess_adjudication_evidence(
            {
                "coverage": {"applied_edits": []},
                "decision_basis": [
                    {
                        "grade": "A",
                        "claim": "electri is a material term.",
                        "evidence_ids": ["det-electri"],
                    }
                ],
                "findings": [],
            },
            [],
            deterministic_findings=[
                {
                    "finding_id": "det-electri",
                    "check": "known_translation_trap",
                    "status": "warning",
                    "severity": "high",
                    "message": "electri was rendered as lightning",
                    "evidence": {"source_phrase": "electri", "expected": "electrum"},
                }
            ],
        )
        self.assertTrue(result["basis_support"][0]["supported"])
        self.assertEqual(result["basis_support"][0]["deterministic_finding_ids"], ["det-electri"])

    def test_grade_a_nonexistent_finding_id_not_supported(self):
        """Grade A referencing nonexistent finding_id is not supported."""
        result = assess_adjudication_evidence(
            {
                "coverage": {"applied_edits": []},
                "decision_basis": [
                    {
                        "grade": "A",
                        "claim": "electri is a material term.",
                        "evidence_ids": ["det-nonexistent"],
                    }
                ],
                "findings": [],
            },
            [],
            deterministic_findings=[
                {
                    "finding_id": "det-electri",
                    "check": "known_translation_trap",
                    "status": "warning",
                    "severity": "high",
                    "message": "electri was rendered as lightning",
                    "evidence": {"source_phrase": "electri", "expected": "electrum"},
                }
            ],
        )
        self.assertFalse(result["basis_support"][0]["supported"])
        self.assertEqual(result["basis_support"][0]["deterministic_finding_ids"], [])

    def test_grade_a_keyword_overlap_without_explicit_id_not_supported(self):
        """Keyword overlap without explicit finding_id must not support Grade A."""
        result = assess_adjudication_evidence(
            {
                "coverage": {"applied_edits": []},
                "decision_basis": [
                    {
                        "grade": "A",
                        "claim": "The electri term is wrongly translated as lightning.",
                        "evidence_ids": [],
                    }
                ],
                "findings": [],
            },
            [],
            deterministic_findings=[
                {
                    "finding_id": "det-electri",
                    "check": "known_translation_trap",
                    "status": "warning",
                    "severity": "high",
                    "message": "electri was rendered as lightning",
                    "evidence": {"source_phrase": "electri", "expected": "electrum"},
                }
            ],
        )
        # Claim contains "electri" "lightning" keywords matching deterministic finding
        # But no explicit evidence_ids -> must NOT be supported
        self.assertFalse(result["basis_support"][0]["supported"])
        self.assertEqual(result["basis_support"][0]["deterministic_finding_ids"], [])

    def test_finding_explicit_deterministic_reference_supported(self):
        """Adjudicator finding with explicit deterministic finding_id is supported."""
        result = assess_adjudication_evidence(
            {
                "coverage": {"applied_edits": []},
                "decision_basis": [],
                "findings": [
                    {
                        "severity": "high",
                        "latin": "electri",
                        "resolution": "Use electrum.",
                        "evidence_ids": ["det-electri"],
                    }
                ],
            },
            [],
            deterministic_findings=[
                {
                    "finding_id": "det-electri",
                    "check": "known_translation_trap",
                    "status": "warning",
                    "severity": "high",
                    "message": "electri was rendered as lightning",
                    "evidence": {"source_phrase": "electri", "expected": "electrum"},
                }
            ],
        )
        self.assertTrue(result["finding_support"][0])
        self.assertEqual(result["finding_support_detail"][0]["deterministic_finding_ids"], ["det-electri"])

    def test_finding_unrelated_deterministic_not_supported(self):
        """Finding with evidence_ids referencing nonexistent deterministic finding is not supported."""
        result = assess_adjudication_evidence(
            {
                "coverage": {"applied_edits": []},
                "decision_basis": [],
                "findings": [
                    {
                        "severity": "high",
                        "latin": "Matthaei",
                        "resolution": "Fix name.",
                        "evidence_ids": ["det-nonexistent"],
                    }
                ],
            },
            [],
            deterministic_findings=[
                {
                    "finding_id": "det-electri",
                    "check": "known_translation_trap",
                    "status": "warning",
                    "severity": "high",
                    "message": "electri was rendered as lightning",
                    "evidence": {"source_phrase": "electri", "expected": "electrum"},
                }
            ],
        )
        # Citing nonexistent finding_id -> not supported
        self.assertFalse(result["finding_support"][0])
        self.assertEqual(result["finding_support_detail"][0]["deterministic_finding_ids"], [])


if __name__ == "__main__":
    unittest.main()
