from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from jerome_pipeline.cache import StageCache
from jerome_pipeline.config import PipelineConfig, load_config
from jerome_pipeline.pipeline import STAGE_ORDER
from jerome_pipeline.review import ReviewRepository, build_review_view
from jerome_pipeline.review_server import start_review_server


def record(
    stage: str,
    output: object,
    *,
    status: str = "complete",
    error: dict | None = None,
) -> dict:
    return {
        "schema_version": 1,
        "pipeline_version": "fixture",
        "prompt_version": "fixture-prompt",
        "stage": stage,
        "chunk_id": "book01-fixture",
        "cache_key": f"cache-{stage}",
        "input_digest": f"input-{stage}",
        "cache_material": {
            "source_fingerprint": "fixture-source",
            "inputs": {"prompt_digest": f"prompt-{stage}"},
            "dependencies": [],
        },
        "status": status,
        "started_at": "2026-08-25T10:00:00Z",
        "finished_at": "2026-08-25T10:00:01Z",
        "model": (
            {
                "provider": "fixture",
                "model": f"fixture-{stage}",
                "temperature": 0,
                "context": 8192,
                "max_output_tokens": 100,
            }
            if stage
            in {
                "structural_parse",
                "witness_a",
                "witness_b",
                "prosecutor_initial",
                "prosecutor_grounded",
                "adjudicator_initial",
            }
            else None
        ),
        "provider_attempts": [],
        "output": output,
        "raw_response": json.dumps(output) if output is not None else None,
        "error": error,
        "provenance": [],
        "execution_profile": "production",
    }


def fixture_audit(status: str = "corrected") -> dict:
    witness_a = "My heart grew cold. He did not come."
    witness_b = "My heart grew hot. He has not come."
    final = "My heart grew hot. He did not come."
    applied = []
    findings = []
    unresolved = []
    human_review = []
    if status == "corrected":
        applied = [
            {
                "old": "grew cold",
                "new": "grew hot",
                "reason": "Restore the polarity of concaluit.",
                "evidence_ids": ["ev-fixture"],
                "start_before": 9,
                "end_before": 18,
            }
        ]
        findings = [
            {
                "latin": "concaluit cor meum",
                "english": "My heart grew hot",
                "type": "lexical",
                "severity": "high",
                "resolution": "Corrected",
                "reason": "The source expresses heat.",
                "evidence_ids": ["ev-fixture"],
                "latin_locator": {
                    "start": 0,
                    "end": 18,
                    "matches": 1,
                    "ambiguous": False,
                },
            }
        ]
    elif status in {"unresolved", "human_review"}:
        final = witness_a
        unresolved = [
            {
                "latin": "non venit",
                "english": "He did not come",
                "alternatives": ["did not come", "has not come"],
                "missing_evidence": "Tense requires review.",
                "latin_locator": {
                    "start": 20,
                    "end": 29,
                    "matches": 1,
                    "ambiguous": False,
                },
            }
        ]
        if status == "human_review":
            human_review = [
                {
                    "latin": "non venit",
                    "english": "He did not come",
                    "issue": "Tense remains disputed.",
                    "action": "Inspect the surrounding chronology.",
                    "latin_locator": {
                        "start": 20,
                        "end": 29,
                        "matches": 1,
                        "ambiguous": False,
                    },
                }
            ]
    elif status == "accepted":
        final = witness_b

    decision = {
        "status": status,
        "summary": "Fixture decision with explicit provenance.",
        "coverage": {
            "all_clauses_accounted_for": True,
            "omissions_corrected": [],
            "base_witness": "a" if status != "accepted" else "b",
            "base_wrapper_removed": False,
            "applied_edits": applied,
        },
        "findings": findings,
        "unresolved_issues": unresolved,
        "human_review_requests": human_review,
        "evidence_requests": [],
        "decision_basis": [
            {
                "grade": "B",
                "claim": "The receipt supports the lexical sense.",
                "evidence_ids": ["ev-fixture"],
            }
        ],
        "final_draft": final,
    }
    stages = {
        "morphology": record(
            "morphology",
            {
                "backend": {"name": "fixture"},
                "morphology": [
                    {
                        "token": "concaluit",
                        "offset": 0,
                        "found": True,
                        "candidates": [{"lemma": "concaleo", "pos": "v"}],
                    }
                ],
                "flags": [
                    {
                        "token": "concaluit",
                        "offset": 0,
                        "flag_type": "known_trap",
                        "senses": ["grow hot"],
                        "note": "Polarity trap",
                    }
                ],
            },
        ),
        "structural_parse": record(
            "structural_parse",
            {
                "sentences": [
                    {
                        "latin": "concaluit cor meum. non venit.",
                        "main_verbs": [
                            {"form": "concaluit", "lemma": "concaleo"},
                            {"form": "venit", "lemma": "venio"},
                        ],
                        "alternatives": [],
                    }
                ],
                "intrinsic_ambiguity": [],
                "context_dependent": [],
                "unverified_analyses": [],
            },
        ),
        "witness_a": record("witness_a", {"translation": witness_a}),
        "witness_b": record("witness_b", {"translation": witness_b}),
        "witness_a_validation": record(
            "witness_a_validation",
            {
                "valid": True,
                "eligible_as_adjudicator_base": True,
                "blocking_failures": [],
                "checks": [],
            },
        ),
        "witness_b_validation": record(
            "witness_b_validation",
            {
                "valid": True,
                "eligible_as_adjudicator_base": True,
                "blocking_failures": [],
                "checks": [],
            },
        ),
        "witness_gate": record(
            "witness_gate",
            {
                "status": "both_valid",
                "proceed": True,
                "valid_witnesses": ["witness_a", "witness_b"],
                "invalid_witnesses": [],
                "allowed_base_witnesses": ["a", "b"],
            },
        ),
        "deterministic_checks": record(
            "deterministic_checks",
            {
                "summary": {"pass": 1, "warning": 1, "failure": 0},
                "findings": [
                    {
                        "check": "known_translation_trap",
                        "status": "warning",
                        "severity": "high",
                        "message": "Witness A reverses concaluit.",
                        "evidence": {
                            "source_phrase": "concaluit cor meum",
                            "matched_wrong_rendering": "grew cold",
                            "witness": "witness_a",
                        },
                    },
                    {
                        "check": "coverage_signal",
                        "status": "pass",
                        "severity": "low",
                        "message": "Length signal passes.",
                        "evidence": {"witness": "witness_b"},
                    },
                ],
                "limits": "Signals are conservative.",
            },
        ),
        "prosecutor_initial": record(
            "prosecutor_initial",
            {
                "status": "requires_evidence",
                "summary": "Polarity requires evidence.",
                "challenges": [
                    {
                        "latin": "concaluit cor meum",
                        "type": "lexical",
                        "severity": "high",
                        "witness_target": "witness_a",
                        "claim": "Witness A reverses the thermal polarity.",
                        "visible_basis": "The visible Latin suggests heat.",
                        "requires_external_evidence": True,
                    }
                ],
                "evidence_requests": [
                    {
                        "kind": "jerome_phrase",
                        "query": "concaluit cor meum",
                        "reason": "Verify the sense.",
                    }
                ],
            },
        ),
        "research_prosecutor": record(
            "research_prosecutor",
            {
                "mode": "executed",
                "requests": [],
                "evidence": [
                    {
                        "evidence_id": "ev-fixture",
                        "grade": "B",
                        "request": {
                            "kind": "jerome_phrase",
                            "query": "concaluit cor meum",
                            "reason": "Verify the sense.",
                        },
                        "requested_by": "prosecutor",
                        "status": "found",
                        "evidence_class": "retrieved_evidence",
                        "retrieved_at": "2026-08-25T10:00:00Z",
                        "results": [
                            {
                                "text": "concaluit cor meum intra me",
                                "score": 1.0,
                                "provenance": {
                                    "corpus": "fixture corpus",
                                    "source_unit_id": "u1",
                                    "page": "0001A",
                                },
                            }
                        ],
                    }
                ],
            },
        ),
        "prosecutor_grounded": record(
            "prosecutor_grounded",
            {
                "status": "grounded_challenge",
                "summary": "The polarity objection is supported.",
                "challenges": [
                    {
                        "latin": "concaluit cor meum",
                        "type": "lexical",
                        "severity": "high",
                        "witness_target": "witness_a",
                        "claim": "Witness A reverses the thermal polarity.",
                        "visible_basis": "Receipt ev-fixture contains the source phrase.",
                        "requires_external_evidence": False,
                    }
                ],
                "evidence_requests": [],
            },
        ),
        "adjudicator_initial": record("adjudicator_initial", decision),
        "research_adjudicator": record(
            "research_adjudicator",
            {"mode": "not_requested", "requests": [], "evidence": []},
        ),
        "adjudicator": record("adjudicator", decision),
        "finalize": record(
            "finalize",
            {
                "final_status": status,
                "final_draft": final,
                "source_mappings": [
                    {
                        "source_unit_id": "u1",
                        "english_start_quote": "My heart grew hot.",
                        "english_end_quote": "My heart grew hot.",
                    },
                    {
                        "source_unit_id": "u2",
                        "english_start_quote": "He did not come.",
                        "english_end_quote": "He did not come.",
                    },
                ],
                "decision": decision,
                "human_review_requests": human_review,
                "unresolved_issues": unresolved,
                "evidence_ids": ["ev-fixture"],
                "final_checks": {
                    "summary": {"pass": 3, "warning": 0, "failure": 0},
                    "findings": [],
                },
            },
        ),
    }
    return {
        "schema_version": 1,
        "pipeline_version": "fixture",
        "execution_profile": "production",
        "chunk_id": "book01-fixture",
        "book": 1,
        "source": {
            "pages": ["0001A", "0001B"],
            "pl_start": "0001A",
            "pl_end": "0001B",
            "source_unit_ids": ["u1", "u2"],
        },
        "source_units": [
            {
                "source_unit_id": "u1",
                "book": 1,
                "page": "0001A",
                "clean_start": 0,
                "clean_end": 19,
                "text": "concaluit cor meum.",
            },
            {
                "source_unit_id": "u2",
                "book": 1,
                "page": "0001B",
                "clean_start": 20,
                "clean_end": 30,
                "text": "non venit.",
            },
        ],
        "page_markers": [],
        "target_latin": "concaluit cor meum. non venit.",
        "context_before": "",
        "context_after": "",
        "source_spans": [
            {"role": "target", "source_unit_id": "u1", "clean_start": 0, "clean_end": 19},
            {"role": "target", "source_unit_id": "u2", "clean_start": 20, "clean_end": 30},
        ],
        "annotations": [],
        "stages": stages,
        "stage_history": list(stages.values()),
        "final_draft": final,
        "final_status": status,
        "human_review_requests": human_review,
        "unresolved_issues": unresolved,
    }


class ReviewViewModelTest(unittest.TestCase):
    def test_degraded_witness_quorum_is_explicit_in_review_contract(self):
        audit = fixture_audit("human_review")
        gate = {
            "quorum": "single_valid_b",
            "status": "single_valid_b",
            "mode": "degraded",
            "degraded_reason": "Witness A failed deterministic validation.",
            "valid_witnesses": ["witness_b"],
            "invalid_witnesses": ["witness_a"],
            "allowed_base_witnesses": ["b"],
            "automatic_acceptance_allowed": False,
            "invalid_witness_output_role": "non_authoritative_clue_not_evidence",
        }
        audit["stages"]["witness_gate"] = record("witness_gate", gate)
        audit["stages"]["witness_a_validation"]["output"].update(
            {"valid": False, "eligible_as_adjudicator_base": False}
        )
        audit["stages"]["witness_b_validation"]["output"].update(
            {"valid": True, "eligible_as_adjudicator_base": True}
        )

        view = build_review_view(audit)

        self.assertEqual(view["chunk"]["witness_quorum"], "single_valid_b")
        self.assertEqual(view["chunk"]["witness_mode"], "degraded")
        self.assertFalse(view["chunk"]["automatic_acceptance_allowed"])
        self.assertEqual(
            view["witness_quorum"]["invalid_witness_output_role"],
            "non_authoritative_clue_not_evidence",
        )
        self.assertEqual(
            view["witnesses"][0]["authority_role"],
            "non_authoritative_clue_not_evidence",
        )
        self.assertFalse(view["witnesses"][0]["may_corroborate"])
        self.assertEqual(
            view["witnesses"][1]["authority_role"],
            "eligible_translation_proposal",
        )

    def test_compact_witness_mapping_is_normalized_for_ui_highlighting(self):
        audit = fixture_audit("corrected")
        audit["stages"]["witness_a"]["output"]["source_mappings"] = [
            {"source_unit_id": "u1", "english_end_quote": "grew cold."}
        ]
        audit["stages"]["witness_a_validation"]["output"]["checks"] = [
            {
                "check": "ordered_translation_mappings",
                "status": "pass",
                "detail": {
                    "spans": [
                        {"source_unit_id": "u1", "start": 0, "end": 14}
                    ]
                },
            }
        ]
        view = build_review_view(audit)
        self.assertEqual(
            view["witnesses"][0]["source_mappings"],
            [
                {
                    "source_unit_id": "u1",
                    "end_marker": "grew cold.",
                    "translation_start": 0,
                    "translation_end": 14,
                    "validation_status": "pass",
                }
            ],
        )

    def test_successful_corrected_chunk_exposes_evidence_edits_and_coverage(self):
        view = build_review_view(fixture_audit("corrected"))
        self.assertEqual(view["chunk"]["final_status"], "corrected")
        self.assertEqual(view["chunk"]["source_unit_count"], 2)
        self.assertEqual(view["chunk"]["counts"]["adjudicator_edits"], 1)
        self.assertTrue(view["witnesses"][0]["validation_recorded"])
        self.assertTrue(view["witnesses"][0]["eligible_as_adjudicator_base"])
        self.assertEqual(view["adjudicator"]["edits"][0]["old"], "grew cold")
        self.assertTrue(view["adjudicator"]["edits"][0]["applied"])
        self.assertEqual(
            view["adjudicator"]["findings"][0]["source_unit_ids"], ["u1"]
        )
        self.assertEqual(view["evidence"]["receipts"][0]["grade"], "B")
        self.assertEqual(
            view["evidence"]["receipts"][0]["results"][0]["provenance"][
                "source_unit_id"
            ],
            "u1",
        )
        self.assertTrue(view["verification"]["coverage_assertion"])
        self.assertEqual(view["verification"]["source_units_total"], 2)
        self.assertTrue(any(item["kind"] == "insert" for item in view["final"]["diff"]))
        self.assertEqual(
            view["review_links"]["persisted"]["final_mapped_source_unit_ids"],
            ["u1", "u2"],
        )
        self.assertIn(
            view["adjudicator"]["edits"][0]["edit_id"],
            view["review_links"]["persisted"]["edit_ids"],
        )

    def test_accepted_chunk_has_complete_status_and_no_edits(self):
        view = build_review_view(fixture_audit("accepted"))
        self.assertEqual(view["chunk"]["final_status"], "accepted")
        self.assertEqual(view["adjudicator"]["edits"], [])
        self.assertEqual(view["final"]["base_witness"], "b")
        self.assertTrue(view["final"]["available"])

    def test_missing_or_failed_upstream_stage_forces_incomplete(self):
        for stage, replacement in (
            ("structural_parse", None),
            (
                "structural_parse",
                record(
                    "structural_parse",
                    None,
                    status="failed",
                    error={"category": "invalid_model_output", "message": "truncated"},
                ),
            ),
            ("witness_b", None),
            ("adjudicator", None),
        ):
            with self.subTest(stage=stage, replacement=bool(replacement)):
                audit = fixture_audit("corrected")
                if replacement is None:
                    audit["stages"].pop(stage)
                else:
                    audit["stages"][stage] = replacement
                view = build_review_view(audit)
                self.assertEqual(view["chunk"]["final_status"], "incomplete")
                states = {item["stage"]: item["state"] for item in view["verification"]["incomplete_stages"]}
                self.assertIn(stage, states)

    def test_ambiguous_edit_failure_is_explicit(self):
        audit = fixture_audit("corrected")
        audit["stages"].pop("finalize")
        audit["stages"]["adjudicator"] = record(
            "adjudicator",
            None,
            status="failed",
            error={
                "category": "invalid_model_output",
                "message": "adjudication edit 0.old must match exactly once; found 2",
            },
        )
        view = build_review_view(audit)
        self.assertEqual(view["chunk"]["final_status"], "incomplete")
        self.assertIsNotNone(view["adjudicator"]["edit_validation_error"])
        self.assertEqual(
            view["verification"]["exact_edit_validation"], "failed_ambiguous"
        )
        self.assertIsNone(view["final"]["translation"])

    def test_unresolved_and_human_review_remain_distinct(self):
        unresolved = build_review_view(fixture_audit("unresolved"))
        human = build_review_view(fixture_audit("human_review"))
        self.assertEqual(unresolved["chunk"]["final_status"], "unresolved")
        self.assertEqual(len(unresolved["adjudicator"]["unresolved_issues"]), 1)
        self.assertEqual(human["chunk"]["final_status"], "human_review")
        self.assertEqual(len(human["adjudicator"]["human_review_requests"]), 1)
        self.assertEqual(
            human["adjudicator"]["human_review_requests"][0]["source_unit_ids"],
            ["u2"],
        )

    def test_view_model_does_not_depend_on_raw_artifact_filename(self):
        left = fixture_audit("corrected")
        right = copy.deepcopy(left)
        for item in left["stages"].values():
            item["artifact_path"] = "cache/location/one.json"
        for item in right["stages"].values():
            item["artifact_path"] = "renamed/location/two.json"
        self.assertEqual(build_review_view(left), build_review_view(right))

    def test_review_links_make_missing_relationships_explicit(self):
        audit = fixture_audit("corrected")
        audit["stages"]["finalize"]["output"]["source_mappings"] = []

        view = build_review_view(audit)

        self.assertTrue(view["review_links"]["unavailable"]["final_source_mappings"])
        self.assertTrue(
            view["review_links"]["unavailable"][
                "prosecutor_initial_grounded_equivalence"
            ]
        )
        self.assertIn(
            "u1", view["review_links"]["persisted"]["finding_source_unit_ids"]
        )

    def test_review_view_carries_base_witness_mapping_when_final_quotes_still_match(self):
        audit = fixture_audit("accepted")
        audit["stages"]["finalize"]["output"]["source_mappings"] = []
        audit["stages"]["witness_b"]["output"]["source_mappings"] = [
            {
                "source_unit_id": "u1",
                "english_end_quote": "My heart grew hot.",
            },
            {
                "source_unit_id": "u2",
                "english_end_quote": "He has not come.",
            },
        ]

        view = build_review_view(audit)

        self.assertTrue(view["final"]["mapping_available"])
        self.assertEqual(
            view["review_links"]["persisted"]["final_mapped_source_unit_ids"],
            ["u1", "u2"],
        )
        self.assertEqual(
            view["final"]["source_mappings"][0]["mapping_confidence"],
            "carried_forward_exact_boundary_quotes",
        )
        self.assertEqual(view["final"]["source_mappings"][0]["english_start_offset"], 0)
        self.assertEqual(
            view["final"]["source_mappings"][0]["english_end_offset"],
            len("My heart grew hot."),
        )
        self.assertEqual(
            view["final"]["source_mappings"][1]["english_start_offset"],
            len("My heart grew hot."),
        )

    def test_review_view_does_not_carry_base_mapping_when_final_quotes_changed(self):
        audit = fixture_audit("accepted")
        audit["stages"]["finalize"]["output"]["source_mappings"] = []
        audit["stages"]["witness_b"]["output"]["source_mappings"] = [
            {
                "source_unit_id": "u1",
                "english_start_quote": "My heart grew cold.",
                "english_end_quote": "My heart grew cold.",
            }
        ]

        view = build_review_view(audit)

        self.assertFalse(view["final"]["mapping_available"])
        self.assertTrue(view["review_links"]["unavailable"]["final_source_mappings"])


class ReviewRepositoryTest(unittest.TestCase):
    def config(self, directory: str) -> PipelineConfig:
        base = load_config()
        data = copy.deepcopy(base.data)
        data["paths"]["artifacts"] = str(Path(directory) / "artifacts")
        data["paths"]["cache"] = str(Path(directory) / "cache")
        return PipelineConfig(path=base.path, root=Path(directory), data=data)

    def write_fixture(self, config: PipelineConfig) -> tuple[Path, Path]:
        audit = fixture_audit("corrected")
        chunk = {
            "chunk_id": audit["chunk_id"],
            "book": 1,
            "source": audit["source"],
            "source_units": audit["source_units"],
            "page_markers": audit["page_markers"],
            "target_latin": audit["target_latin"],
            "context_before": audit["context_before"],
            "context_after": audit["context_after"],
            "source_spans": audit["source_spans"],
            "annotations": audit["annotations"],
            "source_fingerprint": "fixture-source",
        }
        chunks_path = config.path_value("artifacts") / "book01" / "chunks.jsonl"
        chunks_path.parent.mkdir(parents=True, exist_ok=True)
        chunks_path.write_text(json.dumps(chunk) + "\n", encoding="utf-8")
        cache = StageCache(config.path_value("cache"))
        for stage_record in audit["stages"].values():
            cache.save(stage_record)
        return chunks_path, config.path_value("cache")

    @staticmethod
    def tree_digest(root: Path) -> str:
        digest = hashlib.sha256()
        for path in sorted(item for item in root.rglob("*") if item.is_file()):
            digest.update(str(path.relative_to(root)).encode("utf-8"))
            digest.update(path.read_bytes())
        return digest.hexdigest()

    def test_malformed_artifacts_are_reported_without_hiding_valid_chunk(self):
        with tempfile.TemporaryDirectory() as directory:
            config = self.config(directory)
            chunks_path, cache_root = self.write_fixture(config)
            with chunks_path.open("a", encoding="utf-8") as handle:
                handle.write('{"broken":\n')
            broken = cache_root / "stages" / "structural_parse" / "broken" / "bad.json"
            broken.parent.mkdir(parents=True, exist_ok=True)
            broken.write_text('{"also":', encoding="utf-8")
            overview = ReviewRepository(config).list_chunks()
            self.assertEqual(len(overview["chunks"]), 1)
            self.assertGreaterEqual(len(overview["artifact_errors"]), 2)
            kinds = {item["artifact_kind"] for item in overview["artifact_errors"]}
            self.assertEqual(kinds, {"chunks", "stage_cache"})

    def test_repository_reads_without_mutating_machine_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            config = self.config(directory)
            chunks_path, cache_root = self.write_fixture(config)
            roots = [chunks_path.parent, cache_root]
            before = [self.tree_digest(root) for root in roots]
            repository = ReviewRepository(config)
            overview = repository.list_chunks()
            view = repository.get_chunk(overview["chunks"][0]["chunk_id"])
            self.assertIsNotNone(view)
            after = [self.tree_digest(root) for root in roots]
            self.assertEqual(before, after)

    def test_repository_ignores_newer_records_for_stale_source(self):
        with tempfile.TemporaryDirectory() as directory:
            config = self.config(directory)
            self.write_fixture(config)
            stale = record(
                "finalize",
                {
                    "final_draft": "A stale translation for different Latin.",
                    "final_status": "accepted",
                    "human_review_requests": [],
                    "unresolved_issues": [],
                },
            )
            stale["cache_key"] = "cache-finalize-stale-source"
            stale["finished_at"] = "2026-08-25T11:00:01Z"
            stale["cache_material"]["source_fingerprint"] = "stale-source"
            StageCache(config.path_value("cache")).save(stale)

            view = ReviewRepository(config).get_chunk("book01-fixture")

            self.assertIsNotNone(view)
            self.assertNotEqual(
                view["machine"]["final_draft"],
                "A stale translation for different Latin.",
            )
            self.assertEqual(view["chunk"]["final_status"], "corrected")

    def test_http_api_serves_editor_and_only_allows_revision_creation(self):
        with tempfile.TemporaryDirectory() as directory:
            config = self.config(directory)
            chunks_path, cache_root = self.write_fixture(config)
            machine_before = [
                self.tree_digest(chunks_path.parent),
                self.tree_digest(cache_root),
            ]
            running = start_review_server(config, port=0)
            try:
                with urllib.request.urlopen(running.url + "api/chunks", timeout=5) as response:
                    payload = json.loads(response.read())
                self.assertEqual(payload["chunks"][0]["final_status"], "corrected")
                with urllib.request.urlopen(running.url, timeout=5) as response:
                    html = response.read().decode("utf-8")
                with urllib.request.urlopen(running.url + "styles.css", timeout=5) as response:
                    css = response.read().decode("utf-8")
                self.assertIn("Editorial desk", html)
                self.assertIn("Decision trail", html)
                self.assertIn("[hidden] { display: none !important; }", css)
                self.assertIn('id="layer-controls"', html)
                self.assertIn('id="mode-clean"', html)
                self.assertIn('id="selected-context"', html)
                for section_id in (
                    "edit-workspace",
                    "decision-witnesses",
                    "decision-challenges",
                    "decision-adjudicator",
                    "decision-final",
                    "decision-verification",
                    "decision-evidence",
                    "decision-structural",
                    "decision-morphology",
                    "decision-provenance",
                ):
                    self.assertIn(f'id="{section_id}"', html)
                chunk_id = payload["chunks"][0]["chunk_id"]
                with urllib.request.urlopen(
                    running.url + f"api/chunks/{chunk_id}", timeout=5
                ) as response:
                    view = json.loads(response.read())
                self.assertIn("review_links", view)
                issue = next(
                    item
                    for item in view["issues"]["items"]
                    if item["reusable_eligible"]
                )
                create = urllib.request.Request(
                    running.url
                    + f"api/chunks/{chunk_id}/editorial/revisions",
                    data=json.dumps(
                        {
                            "state": "draft",
                            "translation": view["machine"]["final_draft"]
                            + " Editorial.",
                            "base_revision_id": None,
                            "machine_final_digest": view["machine"][
                                "final_draft_digest"
                            ],
                            "issue_resolutions": [
                                {
                                    "issue_id": issue["issue_id"],
                                    "outcome": "deferred",
                                    "note": "Review later.",
                                    "reusable": False,
                                    "approved_english": "",
                                }
                            ],
                        }
                    ).encode("utf-8"),
                    method="POST",
                    headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(create, timeout=5) as response:
                    saved = json.loads(response.read())
                self.assertEqual(saved["revision"]["revision_number"], 1)
                self.assertEqual(saved["revision"]["editorial"]["state"], "draft")
                self.assertEqual(
                    machine_before,
                    [
                        self.tree_digest(chunks_path.parent),
                        self.tree_digest(cache_root),
                    ],
                )
                self.assertEqual(
                    len(
                        list(
                            config.path_value("editorial_reviews").rglob(
                                "revision-*.json"
                            )
                        )
                    ),
                    1,
                )
                request = urllib.request.Request(
                    running.url + "api/chunks",
                    data=b"{}",
                    method="POST",
                    headers={"Content-Type": "application/json"},
                )
                with self.assertRaises(urllib.error.HTTPError) as caught:
                    urllib.request.urlopen(request, timeout=5)
                self.assertEqual(caught.exception.code, 405)
                error = json.loads(caught.exception.read())
                self.assertEqual(error["error"], "machine_artifacts_immutable")
            finally:
                running.stop()


class ReviewerUISelectionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        root = Path(__file__).resolve().parents[1]
        cls.app_js = (root / "jerome_pipeline" / "reviewer_ui" / "app.js").read_text(
            encoding="utf-8"
        )
        cls.css = (root / "jerome_pipeline" / "reviewer_ui" / "styles.css").read_text(
            encoding="utf-8"
        )

    def test_source_unit_selection_can_select_mapped_machine_final_span(self):
        self.assertIn("add(annotationRecord({\n      id: `source-map:${unit.source_unit_id}`", self.app_js)
        self.assertIn("type: \"source_mapping\"", self.app_js)
        self.assertIn("sourceUnitIds: [unit.source_unit_id]", self.app_js)
        self.assertIn("annotationRange(text, annotation, options)", self.app_js)
        self.assertIn("annotation.raw?.english_start_quote", self.app_js)
        self.assertIn("annotation.raw?.english_end_quote", self.app_js)
        self.assertIn("annotation.raw?.english_start_offset", self.app_js)
        self.assertIn("annotation.raw?.english_end_offset", self.app_js)
        self.assertIn("No persisted final-source mapping for this source unit", self.app_js)
        self.assertIn("refreshSelectedTextSurfaces();", self.app_js)
        self.assertIn("renderMachineFinal();", self.app_js)
        self.assertIn("#machine-final .annotation.selected-source", self.app_js)
        self.assertIn(
            "targetMatchesAnnotation(state.selectedReviewTarget, annotation)",
            self.app_js,
        )
        self.assertIn(
            "targetMatchesAnnotation(state.selectedReviewTarget, primary) ? \"selected selected-source\"",
            self.app_js,
        )
        self.assertIn(".annotation.selected-source", self.css)

    def test_degraded_quorum_and_invalid_clue_are_visible(self):
        self.assertIn("Witness quorum degraded", self.app_js)
        self.assertIn("Automatic acceptance disabled", self.app_js)
        self.assertIn("Non-authoritative clue only", self.app_js)
        self.assertIn("not evidence or corroboration", self.app_js)
        self.assertIn("invalid-witness", self.app_js)
        self.assertIn(".witness-card.invalid-witness", self.css)

    def test_source_selection_highlight_survives_layer_toggle_and_moves_or_clears(self):
        self.assertIn(
            "if (!state.layers[annotation.layer] && !targetMatchesAnnotation(state.selectedReviewTarget, annotation)) continue;",
            self.app_js,
        )
        self.assertIn("selectUnit(state.selectedUnit === id ? null : id)", self.app_js)
        self.assertIn("selectReviewTarget(null", self.app_js)
        self.assertIn("element.classList.toggle(\"selected\", targetMatchesAnnotation(target, annotation))", self.app_js)
        self.assertIn("selected-mapping-missing", self.app_js)


if __name__ == "__main__":
    unittest.main()
