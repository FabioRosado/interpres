from __future__ import annotations

import unittest

from jerome_pipeline.reports import compare_legacy


class LegacyComparisonReportTest(unittest.TestCase):
    def test_both_explicit_evidence_rounds_are_exposed(self):
        audit = {
            "chunk_id": "book01-test",
            "target_latin": "non venit",
            "final_status": "accepted",
            "stages": {
                "prosecutor_initial": {
                    "output": {
                        "evidence_requests": [
                            {"kind": "jerome_phrase", "query": "non venit"}
                        ]
                    }
                },
                "research_prosecutor": {
                    "output": {"evidence": [{"evidence_id": "ev-p"}]}
                },
                "prosecutor_grounded": {
                    "output": {"status": "grounded_challenge"}
                },
                "adjudicator_initial": {
                    "output": {
                        "evidence_requests": [
                            {"kind": "glossary", "query": "venit"}
                        ]
                    }
                },
                "research_adjudicator": {
                    "output": {"evidence": [{"evidence_id": "ev-a"}]}
                },
                "adjudicator": {"output": {"status": "accepted"}},
                "finalize": {
                    "output": {
                        "final_status": "accepted",
                        "human_review_requests": [],
                    }
                },
            },
        }
        result = compare_legacy(
            [audit],
            qwen_path=None,
            mistral_path=None,
            prosecutor_path=None,
            review_path=None,
        )[0]
        self.assertEqual(
            result["new_evidence_requests"]["prosecutor"][0]["query"],
            "non venit",
        )
        self.assertEqual(
            result["new_evidence_requests"]["adjudicator"][0]["query"],
            "venit",
        )
        self.assertEqual(
            result["new_retrieved_evidence"]["prosecutor"][0]["evidence_id"],
            "ev-p",
        )
        self.assertEqual(
            result["new_retrieved_evidence"]["adjudicator"][0]["evidence_id"],
            "ev-a",
        )


if __name__ == "__main__":
    unittest.main()
