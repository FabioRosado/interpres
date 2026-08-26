from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

from jerome_pipeline.config import PipelineConfig, load_config
from jerome_pipeline.editorial import (
    EditorialMemoryIndex,
    EditorialRevisionConflict,
    EditorialRevisionStore,
    text_digest,
)
from jerome_pipeline.pipeline import EvidenceFirstPipeline
from jerome_pipeline.prompts import (
    budgeted_adjudicator_prompt,
    prosecutor_prompt,
)
from jerome_pipeline.schemas import adjudication_schema
from tests.test_pipeline import FakeLexicon, FakeProvider


def pipeline_chunk() -> dict:
    return {
        "chunk_id": "book01-test",
        "id": "book01-test",
        "book": 1,
        "target_latin": "non venit",
        "context_before": "",
        "context_after": "",
        "source_fingerprint": "abc",
        "source": {"pages": ["0001A"], "source_unit_ids": ["u1"]},
        "source_spans": [
            {
                "role": "target",
                "source_unit_id": "u1",
                "page": "0001A",
                "clean_start": 0,
                "clean_end": 9,
            }
        ],
        "page_markers": [{"page": "0001A", "raw": "[page 0001A]"}],
        "source_units": [{"source_unit_id": "u1", "text": "non venit"}],
        "annotations": [],
    }


class EditorialRevisionStoreTest(unittest.TestCase):
    @staticmethod
    def machine() -> dict:
        final = "He did not come."
        return {
            "final_status": "accepted",
            "final_draft": final,
            "final_draft_digest": text_digest(final),
            "pipeline_version": "fixture",
            "prompt_version": "fixture-prompt",
            "source_fingerprint": "fixture-source",
        }

    @staticmethod
    def issues() -> list[dict]:
        return [
            {
                "issue_id": "prosecutor:negation-1",
                "origin": "prosecutor",
                "type": "negation",
                "latin": "non venit",
                "source_unit_ids": ["u1"],
            }
        ]

    def payload(self, *, state: str, base_revision_id=None, reusable=False) -> dict:
        return {
            "state": state,
            "translation": "He certainly did not come.",
            "base_revision_id": base_revision_id,
            "machine_final_digest": self.machine()["final_draft_digest"],
            "issue_resolutions": [
                {
                    "issue_id": "prosecutor:negation-1",
                    "outcome": "resolved",
                    "note": "Project rendering approved by the editor.",
                    "reusable": reusable,
                    "approved_english": "did not come" if reusable else "",
                }
            ],
        }

    def test_each_save_creates_a_new_file_and_never_rewrites_prior_revision(self):
        with tempfile.TemporaryDirectory() as directory:
            store = EditorialRevisionStore(Path(directory))
            first = store.save(
                book=1,
                chunk_id="book01-test",
                payload=self.payload(state="draft"),
                machine=self.machine(),
                issues=self.issues(),
            )
            paths = sorted(Path(directory).rglob("revision-*.json"))
            self.assertEqual(len(paths), 1)
            first_bytes = paths[0].read_bytes()
            second = store.save(
                book=1,
                chunk_id="book01-test",
                payload=self.payload(
                    state="approved", base_revision_id=first["revision_id"]
                ),
                machine=self.machine(),
                issues=self.issues(),
            )
            paths = sorted(Path(directory).rglob("revision-*.json"))
            self.assertEqual(len(paths), 2)
            self.assertEqual(paths[0].read_bytes(), first_bytes)
            self.assertNotEqual(first["revision_id"], second["revision_id"])
            self.assertEqual(second["revision_number"], 2)

    def test_stale_editorial_base_and_changed_machine_final_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            store = EditorialRevisionStore(Path(directory))
            first = store.save(
                book=1,
                chunk_id="book01-test",
                payload=self.payload(state="draft"),
                machine=self.machine(),
                issues=self.issues(),
            )
            with self.assertRaises(EditorialRevisionConflict):
                store.save(
                    book=1,
                    chunk_id="book01-test",
                    payload=self.payload(state="draft", base_revision_id=None),
                    machine=self.machine(),
                    issues=self.issues(),
                )
            changed = self.payload(
                state="draft", base_revision_id=first["revision_id"]
            )
            changed["machine_final_digest"] = "stale-machine"
            with self.assertRaises(EditorialRevisionConflict):
                store.save(
                    book=1,
                    chunk_id="book01-test",
                    payload=changed,
                    machine=self.machine(),
                    issues=self.issues(),
                )

    def test_only_approved_opt_in_resolution_enters_editorial_memory(self):
        with tempfile.TemporaryDirectory() as directory:
            store = EditorialRevisionStore(Path(directory))
            draft = store.save(
                book=1,
                chunk_id="book01-test",
                payload=self.payload(state="draft", reusable=True),
                machine=self.machine(),
                issues=self.issues(),
            )
            memory = EditorialMemoryIndex(Path(directory))
            self.assertEqual(memory.match("Et non venit ad eos."), [])
            store.save(
                book=1,
                chunk_id="book01-test",
                payload=self.payload(
                    state="approved",
                    base_revision_id=draft["revision_id"],
                    reusable=True,
                ),
                machine=self.machine(),
                issues=self.issues(),
            )
            matches = memory.match("Et non venit ad eos.")
            self.assertEqual(len(matches), 1)
            self.assertEqual(matches[0]["approved_english"], "did not come")
            self.assertEqual(matches[0]["evidence_class"], "editorial_precedent")
            self.assertIn("not lexical", matches[0]["limits"])
            self.assertEqual(memory.match("nonn venit ad eos"), [])


class EditorialPipelineIntegrationTest(unittest.TestCase):
    def test_editorial_precedent_is_visible_to_reviewers_with_correct_limits(self):
        chunk = pipeline_chunk()
        precedent = {
            "precedent_id": "precedent-fixture",
            "evidence_class": "editorial_precedent",
            "latin": "non venit",
            "approved_english": "did not come",
            "limits": "Human-approved project wording; not lexical proof.",
        }
        checks = {
            "summary": {},
            "findings": [],
            "limits": "fixture",
            "editorial_precedents": [precedent],
            "editorial_precedent_policy": {
                "role": "human_approved_project_consistency",
                "not_source_evidence": True,
            },
        }
        structural = {
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
        }
        prosecutor = prosecutor_prompt(
            chunk,
            structural,
            {"flags": []},
            checks,
            "He did not come.",
            "He has not come.",
        )
        self.assertIn("precedent-fixture", prosecutor)
        self.assertIn("not lexical proof", prosecutor)
        adjudicator = budgeted_adjudicator_prompt(
            chunk,
            "He did not come.",
            "He has not come.",
            structural,
            {"flags": []},
            checks,
            {"status": "no_issue_found", "challenges": []},
            [],
            response_schema=adjudication_schema(),
            budget={
                "max_prompt_utf8_bytes": 45_000,
                "max_request_utf8_bytes": 52_000,
                "max_estimated_prompt_tokens": 15_000,
                "estimator_bytes_per_token": 3.0,
            },
        )
        self.assertTrue(adjudicator.fits)
        self.assertIn("precedent-fixture", adjudicator.prompt or "")
        self.assertIn("never overrule", adjudicator.prompt or "")

    def test_approved_precedent_invalidates_checks_not_blind_witnesses(self):
        with tempfile.TemporaryDirectory() as directory:
            base = load_config()
            data = copy.deepcopy(base.data)
            data["paths"]["cache"] = str(Path(directory) / "cache")
            data["paths"]["concordance"] = str(
                Path(directory) / "missing-concordance.jsonl"
            )
            data["paths"]["editorial_reviews"] = str(
                Path(directory) / "editorial-reviews"
            )
            config = PipelineConfig(path=base.path, root=base.root, data=data)
            provider = FakeProvider()
            chunk = pipeline_chunk()
            first_pipeline = EvidenceFirstPipeline(
                config, lexicon=FakeLexicon(), provider=provider
            )
            first = first_pipeline.run_chunk(
                chunk, through="deterministic_checks"
            )
            first_checks = first["records"]["deterministic_checks"]
            self.assertEqual(first_checks["output"]["editorial_precedents"], [])
            calls_after_first = list(provider.calls)

            machine = {
                "final_status": "accepted",
                "final_draft": "He did not come.",
                "final_draft_digest": text_digest("He did not come."),
            }
            EditorialRevisionStore(config.path_value("editorial_reviews")).save(
                book=1,
                chunk_id="book01-prior",
                payload={
                    "state": "approved",
                    "translation": "He did not come.",
                    "base_revision_id": None,
                    "machine_final_digest": machine["final_draft_digest"],
                    "issue_resolutions": [
                        {
                            "issue_id": "human_review:negation",
                            "outcome": "resolved",
                            "note": "Approved project wording.",
                            "reusable": True,
                            "approved_english": "did not come",
                        }
                    ],
                },
                machine=machine,
                issues=[
                    {
                        "issue_id": "human_review:negation",
                        "origin": "human_review",
                        "type": "negation",
                        "latin": "non venit",
                        "source_unit_ids": ["prior-u1"],
                    }
                ],
            )

            second_pipeline = EvidenceFirstPipeline(
                config, lexicon=FakeLexicon(), provider=provider
            )
            second = second_pipeline.run_chunk(
                chunk, through="deterministic_checks"
            )
            second_checks = second["records"]["deterministic_checks"]
            self.assertNotEqual(first_checks["cache_key"], second_checks["cache_key"])
            self.assertEqual(len(second_checks["output"]["editorial_precedents"]), 1)
            self.assertEqual(provider.calls, calls_after_first)


if __name__ == "__main__":
    unittest.main()
