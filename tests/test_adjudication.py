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
                        "claim": "A corpus occurrence supports the reading.",
                        "evidence_ids": ["ev-found"],
                    }
                ],
                "findings": [
                    {
                        "severity": "high",
                        "resolution": "Correct the reading.",
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
                }
            ],
        )
        self.assertTrue(result["valid_strong_basis"])
        self.assertTrue(result["finding_support"][0])
        self.assertEqual(result["issues"], [])


if __name__ == "__main__":
    unittest.main()
