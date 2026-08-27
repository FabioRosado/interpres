from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from glossary import MorphologicalCandidate, Sense, WordAnalysis
from interpres.challenge import challenge_metrics, run_challenges
from interpres.config import PipelineConfig, load_config
from interpres.evidence import build_concordance, build_retrieval_index
from interpres.providers import ProviderResponse


class ChallengeLexicon:
    backend_name = "challenge_fixture_lexicon"
    contract_version = "challenge-fixture/v1"

    def analyze_word(self, word: str) -> WordAnalysis:
        return WordAnalysis(
            token=word,
            senses=[Sense(lemma=word, pos="x", gloss=word)],
            candidates=[MorphologicalCandidate(lemma=word, pos="x")],
            found=True,
        )


class StagedChallengeProvider:
    def __init__(self):
        self.calls: list[str] = []
        self.prompts: list[str] = []

    def chat(
        self,
        spec,
        prompt: str,
        *,
        json_mode: bool,
        response_schema=None,
    ) -> ProviderResponse:
        self.calls.append(spec.role)
        self.prompts.append(prompt)
        if spec.role in {"witness_a", "witness_b"}:
            raise AssertionError("challenge candidate injection did not intercept witness")
        if spec.role == "structural_parser":
            value = {
                "sentences": [
                    {
                        "id": 1,
                        "verbs": [],
                        "subject": {"text": "cor meum", "uncertain": False},
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
        elif spec.role == "prosecutor":
            value = {
                "status": "grounded_challenge",
                "summary": "The candidate reverses the visible lexical polarity.",
                "challenges": [
                    {
                        "latin": "concaluit",
                        "type": "lexical",
                        "severity": "high",
                        "witness_target": "both",
                        "claim": "Both frozen candidates render heating as cooling.",
                        "visible_basis": "The supplied lexical evidence contradicts cold.",
                        "requires_external_evidence": False,
                    }
                ],
                "evidence_requests": [],
            }
        elif spec.role == "adjudicator":
            value = {
                "status": "corrected",
                "base_witness": "a",
                "edits": [
                    {
                        "old": "cold",
                        "new": "hot",
                        "reason": "Correct the visible polarity reversal.",
                        "evidence_ids": [],
                    }
                ],
                "summary": "The agreed candidate contained a lexical reversal.",
                "coverage": {
                    "all_clauses_accounted_for": True,
                    "omissions_corrected": [],
                },
                "findings": [
                    {
                        "latin": "concaluit",
                        "english": "grew hot",
                        "type": "lexical",
                        "severity": "high",
                        "resolution": "corrected",
                        "reason": "Visible lexical evidence defeats witness agreement.",
                        "evidence_ids": [],
                    }
                ],
                "unresolved_issues": [],
                "human_review_requests": [],
                "evidence_requests": [],
                "decision_basis": [
                    {
                        "grade": "A",
                        "claim": "The visible lexical candidate supports heat.",
                        "evidence_ids": [],
                    }
                ],
            }
        else:
            raise AssertionError(spec.role)
        return ProviderResponse(
            content=json.dumps(value),
            seconds=0.01,
            used_model=spec.cache_identity(),
            attempts=[{"provider": "fixture", "outcome": "complete"}],
            fallback_used=False,
        )


class ChallengePipelineTest(unittest.TestCase):
    def test_full_pipeline_injects_agreed_candidate_and_is_resumable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            challenge_set = root / "challenge.jsonl"
            challenge_set.write_text(
                json.dumps(
                    {
                        "case_id": "agreed-wrong-lexical",
                        "latin": "concaluit cor meum",
                        "candidate_english": "my heart grew cold",
                        "source": {
                            "book": 1,
                            "page": "0016A",
                            "kind": "fixture",
                        },
                        "mutation": "plausible_wrong_lexical_sense",
                        "expected_error_types": ["lexical"],
                        "clean": False,
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            source_file = root / "book1.txt"
            source_file.write_text(
                "LIBER PRIMUS.\n\n"
                "-----------------------------[page 0016A]------------------------------\n"
                "concaluit cor meum intra me, et in meditatione mea exarsit ignis\n",
                encoding="utf-8",
            )
            base = load_config()
            data = copy.deepcopy(base.data)
            data["source"]["books"] = {"1": str(source_file)}
            data["paths"]["artifacts"] = str(root / "artifacts")
            data["paths"]["cache"] = str(root / "cache")
            data["paths"]["concordance"] = str(root / "concordance.jsonl")
            data["paths"]["retrieval_index"] = str(root / "retrieval-index.json")
            data["paths"]["challenge_set"] = str(challenge_set)
            data["paths"]["challenge_results"] = str(root / "results.jsonl")
            config = PipelineConfig(path=base.path, root=base.root, data=data)
            build_concordance(config, backend=ChallengeLexicon(), include_lemmas=False)
            build_retrieval_index(config)
            provider = StagedChallengeProvider()

            first = run_challenges(
                config,
                lexicon=ChallengeLexicon(),
                provider=provider,
                full_pipeline=True,
            )
            self.assertEqual(first[0]["pipeline_status"], "human_review")
            self.assertEqual(
                first[0]["candidate_injected_into"], ["witness_a", "witness_b"]
            )
            self.assertEqual(first[0]["planted_detected"], ["lexical"])
            self.assertEqual(
                first[0]["stage_first_detected"]["lexical"],
                "prosecutor_initial",
            )
            self.assertNotIn("witness_a", provider.calls)
            self.assertNotIn("witness_b", provider.calls)
            first_call_count = len(provider.calls)

            second = run_challenges(
                config,
                lexicon=ChallengeLexicon(),
                provider=provider,
                full_pipeline=True,
            )
            self.assertEqual(len(provider.calls), first_call_count)
            self.assertEqual(second[0]["planted_detected"], ["lexical"])
            metrics = challenge_metrics(second)
            self.assertEqual(metrics["full_pipeline_completed_cases"], 1)
            self.assertEqual(metrics["full_pipeline_failures"], 0)
            self.assertTrue((root / "results.jsonl").exists())


if __name__ == "__main__":
    unittest.main()
