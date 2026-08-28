from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from interpres.cache import StageCache, canonical_digest
from interpres.config import PipelineConfig, load_config
from interpres.review import ReviewRepository, build_review_view
from interpres.review_server import start_review_server


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

    def test_markdown_and_human_annotations_round_trip_append_only(self):
        with tempfile.TemporaryDirectory() as directory:
            config = self.config(directory)
            self.write_fixture(config)
            repository = ReviewRepository(config)
            view = repository.get_chunk("book01-fixture")
            self.assertIsNotNone(view)
            machine_text = view["machine"]["final_draft"]
            selected_text = machine_text[:8]
            annotation = {
                "annotation_id": "annotation-round-trip",
                "kind": "translation_decision",
                "text": "Keep this rendering for the published edition.",
                "target": {
                    "surface": "editorial",
                    "start": 0,
                    "end": len(selected_text),
                    "selected_text": selected_text,
                },
                "source_unit_ids": ["u1"],
                "created_at": "2026-08-27T12:00:00Z",
                "updated_at": "2026-08-27T12:00:00Z",
            }
            first = repository.save_editorial_revision(
                "book01-fixture",
                {
                    "state": "draft",
                    "translation": f"# Heading\n\n{machine_text}",
                    "content_format": "markdown",
                    "annotations": [{
                        **annotation,
                        "target": {
                            **annotation["target"],
                            "start": 11,
                            "end": 11 + len(selected_text),
                        },
                    }],
                    "base_revision_id": None,
                    "machine_final_digest": view["machine"]["final_draft_digest"],
                    "issue_resolutions": [],
                },
            )
            self.assertEqual(first["revision"]["editorial"]["content_format"], "markdown")
            self.assertEqual(first["revision"]["editorial"]["annotations"][0]["span_status"], "valid")

            updated_annotation = {
                **first["revision"]["editorial"]["annotations"][0],
                "text": "Updated private publication note.",
                "updated_at": "2026-08-27T12:05:00Z",
            }
            second = repository.save_editorial_revision(
                "book01-fixture",
                {
                    "state": "draft",
                    "translation": f"Changed # Heading\n\n{machine_text}",
                    "content_format": "markdown",
                    "annotations": [updated_annotation],
                    "base_revision_id": first["revision"]["revision_id"],
                    "machine_final_digest": view["machine"]["final_draft_digest"],
                    "issue_resolutions": [],
                },
            )
            self.assertEqual(second["revision"]["editorial"]["annotations"][0]["span_status"], "stale")
            self.assertEqual(second["revision"]["editorial"]["annotations"][0]["text"], "Updated private publication note.")

            third = repository.save_editorial_revision(
                "book01-fixture",
                {
                    "state": "draft",
                    "translation": f"Changed # Heading\n\n{machine_text}",
                    "content_format": "markdown",
                    "annotations": [],
                    "base_revision_id": second["revision"]["revision_id"],
                    "machine_final_digest": view["machine"]["final_draft_digest"],
                    "issue_resolutions": [],
                },
            )
            self.assertEqual(third["editorial"]["revision_count"], 3)
            self.assertEqual(third["revision"]["editorial"]["annotations"], [])
            reloaded = repository.get_chunk("book01-fixture")
            self.assertEqual(reloaded["editorial"]["latest"]["editorial"]["content_format"], "markdown")
            self.assertNotIn("annotations", reloaded["machine"])
            self.assertNotIn("annotations", reloaded["evidence"])

    def test_legacy_editorial_revision_defaults_to_plain_text(self):
        with tempfile.TemporaryDirectory() as directory:
            config = self.config(directory)
            self.write_fixture(config)
            repository = ReviewRepository(config)
            view = repository.get_chunk("book01-fixture")
            saved = repository.save_editorial_revision(
                "book01-fixture",
                {
                    "state": "draft",
                    "translation": view["machine"]["final_draft"],
                    "base_revision_id": None,
                    "machine_final_digest": view["machine"]["final_draft_digest"],
                    "issue_resolutions": [],
                },
            )
            self.assertEqual(saved["revision"]["editorial"]["content_format"], "plain_text")
            self.assertEqual(saved["editorial"]["latest"]["editorial"]["annotations"], [])

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

    def test_repository_uses_newest_coherent_witness_branch_not_old_final(self):
        with tempfile.TemporaryDirectory() as directory:
            config = self.config(directory)
            chunk = {
                "chunk_id": "book01-fixture",
                "book": 1,
                "source": {},
                "source_units": [],
                "page_markers": [],
                "target_latin": "electri esse in medio",
                "context_before": "",
                "context_after": "",
                "source_spans": [],
                "annotations": [],
                "source_fingerprint": "fixture-source",
            }

            def linked(stage, key, output, finished, dependencies=()):
                value = record(stage, output)
                value["cache_key"] = key
                value["finished_at"] = finished
                value["cache_material"]["dependencies"] = [
                    {
                        "stage": item["stage"],
                        "cache_key": item["cache_key"],
                        "output_digest": canonical_digest(item.get("output")),
                    }
                    for item in dependencies
                ]
                return value

            old_a = linked("witness_a", "old-a", {"translation": "Old A"}, "2026-01-01T01:00:00Z")
            old_b = linked("witness_b", "old-b", {"translation": "Old B"}, "2026-01-01T01:00:01Z")
            old_av = linked("witness_a_validation", "old-av", {"valid": True}, "2026-01-01T01:00:02Z", [old_a])
            old_bv = linked("witness_b_validation", "old-bv", {"valid": True}, "2026-01-01T01:00:02Z", [old_b])
            old_gate = linked("witness_gate", "old-gate", {"quorum": "both_valid", "mode": "normal"}, "2026-01-01T01:00:03Z", [old_av, old_bv])
            old_checks = linked("deterministic_checks", "old-checks", {"findings": []}, "2026-01-01T01:00:04Z", [old_gate])
            old_prosecutor = linked("prosecutor_initial", "old-prosecutor", {"summary": "old"}, "2026-01-01T01:00:05Z", [old_checks])
            old_adjudicator = linked("adjudicator", "old-adjudicator", {"final_draft": "Old machine final"}, "2026-01-01T01:00:06Z", [old_prosecutor])
            old_final = linked("finalize", "old-final", {"final_draft": "Old machine final", "final_status": "accepted"}, "2026-01-01T01:00:07Z", [old_adjudicator, old_gate])

            new_a = linked("witness_a", "new-a", {"translation": "Invalid new A"}, "2026-01-02T01:00:00Z")
            new_b = linked("witness_b", "new-b", {"translation": "Valid new B"}, "2026-01-02T01:00:01Z")
            new_av = linked("witness_a_validation", "new-av", {"valid": False}, "2026-01-02T01:00:02Z", [new_a])
            new_bv = linked("witness_b_validation", "new-bv", {"valid": True}, "2026-01-02T01:00:02Z", [new_b])
            new_gate = linked(
                "witness_gate",
                "new-gate",
                {
                    "quorum": "single_valid_b",
                    "mode": "degraded",
                    "valid_witnesses": ["witness_b"],
                    "invalid_witnesses": ["witness_a"],
                    "allowed_base_witnesses": ["b"],
                    "automatic_acceptance_allowed": False,
                },
                "2026-01-02T01:00:03Z",
                [new_av, new_bv],
            )
            records = [
                old_a, old_b, old_av, old_bv, old_gate, old_checks,
                old_prosecutor, old_adjudicator, old_final,
                new_a, new_b, new_av, new_bv, new_gate,
            ]
            audit = ReviewRepository(config)._audit(chunk, records)
            self.assertEqual(audit["stages"]["witness_gate"]["cache_key"], "new-gate")
            self.assertEqual(audit["stages"]["witness_a"]["cache_key"], "new-a")
            self.assertNotIn("finalize", audit["stages"])
            self.assertNotIn("prosecutor_initial", audit["stages"])
            self.assertIsNone(audit["final_draft"])
            self.assertEqual(audit["final_status"], "incomplete")
            self.assertTrue(
                any(item.get("cache_key") == "old-final" for item in audit["stage_history"])
            )

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
                self.assertIn("Interpres Reviewer", html)
                self.assertIn('id="app"', html)
                self.assertIn("[hidden] { display: none !important; }", css)
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


class ProjectAwareReviewRegressionTest(unittest.TestCase):
    """Regression test for project-aware review path.

    Verifies that the jerome-ezekiel project, when loaded through the new
    project-aware CLI path, can access cached pipeline data. The project
    config must point to the same cache directory as the root config
    (.cache/jerome) to preserve compatibility with existing cached artifacts,
    since their semantic identity (pipeline_version, schema_version,
    prompt_version, model specs) has not changed.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.root_config = load_config("pipeline.yaml")
        cls.project_config = load_config("projects/jerome-ezekiel/pipeline.yaml")

    def test_project_config_loads_correctly(self):
        self.assertEqual(self.project_config.pipeline_version, "5.0.0-evidence-first")
        self.assertEqual(self.project_config.schema_version, 1)
        self.assertEqual(self.project_config.prompt_version, "2026-08-25.4")
        expected_cache = Path("C:/Users/FabioRosado/Desktop/translation/.cache/jerome").resolve()
        expected_artifacts = Path("C:/Users/FabioRosado/Desktop/translation/artifacts").resolve()
        self.assertEqual(self.project_config.path_value("cache").resolve(), expected_cache)
        self.assertEqual(self.project_config.path_value("artifacts").resolve(), expected_artifacts)

    def test_both_configs_use_same_cache_directory(self):
        """Both root and project configs must resolve to the same cache
        directory to share existing cached artifacts."""
        root_cache = self.root_config.path_value("cache").resolve()
        project_cache = self.project_config.path_value("cache").resolve()
        self.assertEqual(root_cache, project_cache)

    def test_both_configs_share_same_pipeline_identity(self):
        """Semantic identity (pipeline_version, schema_version, prompt_version, models)
        is identical, so cache keys are compatible."""
        self.assertEqual(
            self.root_config.pipeline_version, self.project_config.pipeline_version
        )
        self.assertEqual(
            self.root_config.schema_version, self.project_config.schema_version
        )
        self.assertEqual(
            self.root_config.prompt_version, self.project_config.prompt_version
        )
        for role in [
            "witness_a",
            "witness_b",
            "structural_parser",
            "prosecutor",
            "adjudicator",
        ]:
            root_model = self.root_config.model(role)
            project_model = self.project_config.model(role)
            self.assertEqual(root_model.provider, project_model.provider)
            self.assertEqual(root_model.model, project_model.model)
            self.assertEqual(root_model.temperature, project_model.temperature)

    def test_project_aware_path_exposes_existing_lineage(self):
        """The project-aware path must expose chunks with active lineage
        from the shared Jerome cache."""
        repo = ReviewRepository(self.project_config, book=1, profile="production")
        overview = repo.list_chunks()
        chunks_with_lineage = [
            c for c in overview["chunks"] if c.get("witness_quorum") is not None
        ]
        self.assertGreater(
            len(chunks_with_lineage),
            0,
            "Project-aware path should expose at least one chunk with lineage",
        )
        for chunk in chunks_with_lineage:
            view = repo.get_chunk(chunk["chunk_id"])
            self.assertTrue(view["witness_quorum"]["recorded"])
            self.assertIn(view["witness_quorum"]["mode"], ("normal", "degraded"))
            self.assertGreater(len(view["run_details"]), 0)


class ReviewerUISelectionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        root = Path(__file__).resolve().parents[1]
        cls.ui_root = root / "interpres" / "reviewer_ui"
        module_paths = [cls.ui_root / "app.js", *sorted((cls.ui_root / "js").glob("*.js"))]
        cls.app_js = "\n".join(path.read_text(encoding="utf-8") for path in module_paths)
        cls.css = (root / "interpres" / "reviewer_ui" / "styles.css").read_text(
            encoding="utf-8"
        )
        cls.html = (root / "interpres" / "reviewer_ui" / "index.html").read_text(
            encoding="utf-8"
        )
        cls.component_source = "\n".join(
            path.read_text(encoding="utf-8")
            for path in sorted((cls.ui_root / "src").rglob("*.ts*"))
        )
        cls.component_css = "\n".join(
            path.read_text(encoding="utf-8")
            for path in sorted((cls.ui_root / "src" / "styles").glob("*.css"))
        )

    def test_source_unit_selection_can_select_mapped_machine_final_span(self):
        self.assertIn("id: `source-map:${unit.source_unit_id}`", self.app_js)
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

    def test_context_inspector_is_non_modal_and_preserves_selection(self):
        self.assertIn('<aside className="evidence-inspector"', self.component_source)
        self.assertIn("document.addEventListener('keydown', handleKeyDown)", self.component_source)
        self.assertNotIn('<wa-drawer ref={drawerRef}', self.component_source)
        self.assertIn("onClose={() => setState", self.component_source)
        self.assertNotIn("selectedReviewTarget: null, evidenceInspectorOpen: false", self.component_source)
        self.assertIn(".evidence-inspector {", self.component_css)

    def test_focus_mode_button_and_css_exist(self):
        self.assertIn("(['review', 'focus', 'clean'] as const)", self.component_source)
        self.assertIn("review-mode-${state.reviewMode}", self.component_source)
        self.assertIn(".review-mode-focus .annotation:not(.selected)", self.component_css)

    def test_clean_reading_preserves_source_selection_highlight(self):
        self.assertIn(".clean-reading .annotation.selected-source", self.css)
        self.assertIn("border-bottom: 3px solid var(--indigo)", self.css)

    def test_keyboard_shortcuts_exist(self):
        self.assertIn("event.key === \"j\" || event.key === \"ArrowDown\"", self.app_js)
        self.assertIn("event.key === \"k\" || event.key === \"ArrowUp\"", self.app_js)
        self.assertIn("event.key === \"Escape\"", self.app_js)
        self.assertIn("event.altKey && event.key === \"ArrowLeft\"", self.app_js)
        self.assertIn("event.altKey && event.key === \"ArrowRight\"", self.app_js)

    def test_editorial_diff_drawer_exists(self):
        self.assertIn("<EditorialDiff", self.component_source)
        self.assertIn("editorial-diff-drawer", self.component_css)
        self.assertIn("textDiff(base, editorial)", self.component_source)

    def test_review_links_endpoint_exposed(self):
        audit = fixture_audit("corrected")
        view = build_review_view(audit)
        self.assertIn("review_links", view)
        self.assertIn("persisted", view["review_links"])
        self.assertIn("unavailable", view["review_links"])

    def test_explicit_evidence_ids_preferred_over_regex(self):
        audit = fixture_audit("corrected")
        finding = {
            "finding_id": "test-finding",
            "source_unit_ids": ["u1"],
            "evidence_ids": ["ev-explicit"],
            "message": "Test",
        }
        from interpres.review import _normalise_finding
        normalised = _normalise_finding(finding, prefix="test", index=1, source_units=audit["source_units"])
        self.assertEqual(normalised["evidence_ids"], ["ev-explicit"])
        self.assertTrue(normalised["evidence_ids_explicit"])

    def test_final_edit_offsets_computed(self):
        audit = fixture_audit("corrected")
        view = build_review_view(audit)
        edits = view["adjudicator"]["edits"]
        self.assertTrue(len(edits) > 0)
        for edit in edits:
            if edit.get("start_before") is not None and edit.get("end_before") is not None:
                self.assertIn("final_start_offset", edit)
                self.assertIn("final_end_offset", edit)

    def test_frontend_modules_parse_and_are_loaded_as_es_modules(self):
        self.assertIn('type="module"', self.html)
        modules = [self.ui_root / "app.js", *sorted((self.ui_root / "js").glob("*.js"))]
        for module in modules:
            result = subprocess.run(
                ["node", "--check", str(module)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_editor_first_tabs_markdown_and_compact_ledger_exist(self):
        self.assertIn('className="reference-sidebar"', self.component_source)
        self.assertIn("<SourcePane", self.component_source)
        self.assertIn("<MachineFinalPane", self.component_source)
        self.assertIn("<MarkdownPreview markdown={text}", self.component_source)
        self.assertIn("<IssueNavigator", self.component_source)
        self.assertIn("state.selectedReviewTarget", self.component_source)
        self.assertIn('className="issue-sidebar"', self.component_source)
        self.assertIn("decision-trail", self.component_source)

    def test_primary_workspace_keeps_reference_sidebar_beside_editor(self):
        self.assertIn('className="workstation-grid"', self.component_source)
        self.assertIn('className="reference-sidebar"', self.component_source)
        self.assertIn('className="editor-column"', self.component_source)
        self.assertIn("grid-template-columns: minmax(340px, 500px)", self.component_css)
        self.assertIn('role="tablist" aria-label="Reference text"', self.component_source)
        self.assertIn("Authoritative source", self.component_source)
        self.assertIn("Machine final · locked", self.component_source)

    def test_full_resolution_ledger_is_permanently_docked(self):
        self.assertIn('id="issue-heading">Resolution Ledger', self.component_source)
        self.assertIn('id="issue-ledger"', self.component_source)
        self.assertIn('className="issue-sidebar"', self.component_source)
        self.assertIn("docked", self.component_source)
        self.assertIn("issueLedgerOpen: true", self.component_source)

    def test_human_annotation_ui_uses_structured_metadata(self):
        self.assertIn('id="add-annotation"', self.component_source)
        self.assertIn('className="annotation-list"', self.component_source)
        self.assertIn("validateAnnotationSpan", self.component_source)
        self.assertIn("content_format: 'markdown'", self.component_source)
        self.assertIn("annotations: state.annotations", self.component_source)

    def test_markdown_preview_escapes_raw_html_and_filters_links(self):
        markdown_module = (self.ui_root / "js" / "markdown.js").read_text(encoding="utf-8")
        self.assertIn('.replaceAll("<", "&lt;")', markdown_module)
        self.assertIn('/^(https?:|mailto:|#)/i', markdown_module)
        self.assertNotIn("eval(", markdown_module)


if __name__ == "__main__":
    unittest.main()
