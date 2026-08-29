from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

from interpres.challenge import challenge_metrics, run_challenges
from interpres.checks import run_deterministic_checks
from interpres.config import PipelineConfig, load_config
from interpres.evidence import EvidenceService, build_concordance, build_retrieval_index
from interpres.pipeline import EvidenceFirstPipeline
from interpres.prompts import adjudicator_prompt, budgeted_prosecutor_prompt, witness_prompt
from interpres.review import build_review_view
from interpres.source import preprocess_book
from interpres.tasks import TaskProfile


PROJECT_CONFIG = (
    Path(__file__).resolve().parents[1]
    / "projects"
    / "chrysostom-homilies"
    / "pipeline.yaml"
)


class StubLexicon:
    backend_name = "stub"
    contract_version = "stub-v1"


def write_sample_chrysostom_source(root: Path) -> tuple[Path, Path]:
    clean_dir = root / "clean"
    notes_dir = root / "notes"
    clean_dir.mkdir(parents=True, exist_ok=True)
    notes_dir.mkdir(parents=True, exist_ok=True)
    (clean_dir / "homily-001.txt").write_text(
        (
            "Homily I. It were indeed meet for us not at all to require the aid "
            "of the written Word. The opening has no printed section number, "
            "and it speaks of repentance and mercy.\n\n"
            "2. Reflect then how great an evil it is for us, who ought to live "
            "so purely as not even to need written words.\n\n"
            "3. How then was that law given in time past? It was given for our "
            "instruction."
        ),
        encoding="utf-8",
    )
    (clean_dir / "homily-002.txt").write_text(
        (
            "Homily II. Matt. I. 1. “The book of the generation of Jesus "
            "Christ.” The opening citation number is not a homily section.\n\n"
            "2. But what is this vestibule? It is the beginning of the Gospel."
        ),
        encoding="utf-8",
    )
    (notes_dir / "homily-001.notes.txt").write_text(
        "17\nJohn xiv. 26.\n",
        encoding="utf-8",
    )
    return clean_dir, notes_dir


def isolated_chrysostom_config(directory: str) -> PipelineConfig:
    base = load_config(PROJECT_CONFIG)
    data = copy.deepcopy(base.data)
    root = Path(directory)
    clean_dir, notes_dir = write_sample_chrysostom_source(root)
    data["source"]["books"]["1"] = str(clean_dir)
    data["source"]["notes_path"] = str(notes_dir)
    data["paths"]["artifacts"] = str(root / "artifacts")
    data["paths"]["cache"] = str(root / "cache")
    data["paths"]["concordance"] = str(root / "artifacts" / "concordance.jsonl")
    data["paths"]["retrieval_index"] = str(root / "artifacts" / "retrieval-index.json")
    data["paths"]["challenge_results"] = str(root / "artifacts" / "challenge-results.jsonl")
    return PipelineConfig(path=base.path, root=base.root, data=data)


class ModernizationProjectTest(unittest.TestCase):
    def _modernization_chunk(self, source: str) -> dict:
        return {
            "source_text": source,
            "target_latin": source,
            "task_type": "modernization",
            "project": {
                "id": "fixture",
                "task_type": "modernization",
                "morphology_enabled": False,
                "structural_enabled": False,
            },
            "checks": {
                "archaic_residue_terms": [
                    "thou",
                    "thee",
                    "thy",
                    "thine",
                    "hath",
                    "doth",
                    "saith",
                    "mayest",
                    "hast",
                    "wherein",
                    "unto",
                    "shew",
                ],
                "reverse_modernization_pairs": [
                    {"modern": "says", "archaic": "saith"},
                    {"modern": "has", "archaic": "hath"},
                    {"modern": "show", "archaic": "shew"},
                    {"modern": "you", "archaic": "thou"},
                ],
                "unnecessary_modernization_pairs": [
                    {"source": "arisen", "target": "had birth"},
                    {"source": "separated", "target": "parted off"},
                ],
            },
            "source_spans": [],
            "page_markers": [],
            "source": {"pages": []},
            "annotations": [],
        }

    def test_preprocess_adds_project_metadata_without_dropping_legacy_aliases(self):
        with tempfile.TemporaryDirectory() as directory:
            config = isolated_chrysostom_config(directory)
            parsed, chunks = preprocess_book(config, 1)

            self.assertEqual(parsed["project"]["id"], "chrysostom-homilies")
            self.assertEqual(len(chunks), 5)
            self.assertEqual(chunks[0]["source_label"], "Historical English")
            self.assertEqual(chunks[0]["target_label"], "Modern English")
            self.assertEqual(chunks[0]["source_text"], chunks[0]["target_latin"])
            self.assertEqual(chunks[0]["latin"]["text"], chunks[0]["source_text"])
            self.assertFalse(chunks[0]["project"]["morphology_enabled"])
            self.assertFalse(chunks[0]["project"]["structural_enabled"])
            self.assertEqual(
                chunks[0]["source"]["section_ids"],
                ["book01-homily-001-section-001"],
            )
            self.assertEqual(chunks[0]["source"]["anchors"], ["homily-1-section-1"])
            self.assertFalse(chunks[0]["source_units"][0]["section_number_explicit"])

            _, second = preprocess_book(config, 1)
            self.assertEqual(
                [chunk["chunk_id"] for chunk in chunks],
                [chunk["chunk_id"] for chunk in second],
            )

    def test_modernization_checks_separate_deterministic_and_review_signals(self):
        chunk = {
            "source_text": (
                'Augustine saith, "Grace abideth." Luke 15:7 names 99 sheep; '
                "thou preventeth the weary."
            ),
            "target_latin": (
                'Augustine saith, "Grace abideth." Luke 15:7 names 99 sheep; '
                "thou preventeth the weary."
            ),
            "task_type": "modernization",
            "project": {
                "id": "fixture",
                "task_type": "modernization",
                "morphology_enabled": False,
                "structural_enabled": False,
            },
            "checks": {
                "archaic_residue_terms": ["thou", "saith", "abideth"],
                "preserved_terms": ["Grace"],
                "lexical_traps": {
                    "prevent": {"wrong_modern_senses": ["stop"]},
                },
            },
            "source_spans": [],
            "page_markers": [],
            "source": {"pages": []},
            "annotations": [],
        }

        result = run_deterministic_checks(
            chunk,
            'Augustine says, "Grace remains." Luke 15:7 names sheep; you stop the weary.',
            'Augustine says, "Grace abides." Luke names 99 sheep; thou go before the weary.',
        )
        findings = result["findings"]
        by_check = {item["check"]: item for item in findings if item["status"] == "warning"}

        self.assertNotIn("quoted_material", by_check)
        self.assertEqual(by_check["scripture_reference"]["provenance"]["kind"], "deterministic_preservation")
        self.assertEqual(by_check["numbers"]["provenance"]["kind"], "deterministic_preservation")
        self.assertEqual(by_check["archaic_residue"]["provenance"]["kind"], "deterministic_preservation")
        self.assertEqual(by_check["historical_lexical_trap"]["provenance"]["kind"], "heuristic_review_signal")

    def test_modernization_direction_checks_reject_re_archaization(self):
        chunk = self._modernization_chunk(
            "For he says that God has made this manifest and will show mercy."
        )

        result = run_deterministic_checks(
            chunk,
            "For he saith that God hath made this manifest and will shew mercy.",
            "For he says that God has made this manifest and will show mercy.",
        )
        warnings = [
            item
            for item in result["findings"]
            if item["status"] == "warning"
            and item["evidence"].get("witness") == "witness_a"
        ]
        by_check = {item["check"]: item for item in warnings}

        self.assertEqual(
            by_check["archaic_introduction"]["evidence"]["terms"],
            ["hath", "saith", "shew"],
        )
        self.assertEqual(by_check["archaic_introduction"]["severity"], "high")
        self.assertEqual(
            by_check["reverse_modernization_churn"]["evidence"]["pairs"],
            [
                {"source_modern": "has", "target_archaic": "hath"},
                {"source_modern": "says", "target_archaic": "saith"},
                {"source_modern": "show", "target_archaic": "shew"},
            ],
        )
        self.assertNotIn(
            "archaic_introduction",
            {
                item["check"]
                for item in result["findings"]
                if item["status"] == "warning"
                and item["evidence"].get("witness") == "witness_b"
            },
        )

    def test_observed_unnecessary_churn_pairs_are_review_signals(self):
        result = run_deterministic_checks(
            self._modernization_chunk("For many sects have arisen since their time."),
            "For many sects had birth since their time.",
            "For many sects have arisen since their time.",
        )
        churn = next(
            item
            for item in result["findings"]
            if item["check"] == "unnecessary_lexical_churn"
            and item["evidence"].get("witness") == "witness_a"
        )
        self.assertEqual(churn["status"], "warning")
        self.assertEqual(churn["provenance"]["kind"], "heuristic_review_signal")
        self.assertFalse(churn["evidence"]["mechanically_proven"])
        self.assertEqual(
            churn["evidence"]["pairs"],
            [{"source": "arisen", "target": "had birth", "note": ""}],
        )

        separated = run_deterministic_checks(
            self._modernization_chunk("Some have separated a portion."),
            "Some have parted off a portion.",
            "Some have separated a portion.",
        )
        separated_churn = next(
            item
            for item in separated["findings"]
            if item["check"] == "unnecessary_lexical_churn"
            and item["evidence"].get("witness") == "witness_a"
        )
        self.assertEqual(separated_churn["status"], "warning")
        self.assertEqual(
            separated_churn["provenance"]["kind"], "heuristic_review_signal"
        )

    def test_exact_directionality_examples(self):
        cases = [
            ("He says", "saith He", "archaic_introduction"),
            ("he has", "he hath", "archaic_introduction"),
            ("show", "shew", "archaic_introduction"),
        ]
        for source, bad, expected in cases:
            with self.subTest(source=source, bad=bad):
                result = run_deterministic_checks(
                    self._modernization_chunk(source),
                    bad,
                    source,
                )
                warnings = {
                    item["check"]
                    for item in result["findings"]
                    if item["status"] == "warning"
                    and item["evidence"].get("witness") == "witness_a"
                }
                self.assertIn(expected, warnings)

        good = run_deterministic_checks(
            self._modernization_chunk("he saith"),
            "he says",
            "he saith",
        )
        good_warnings = {
            item["check"]
            for item in good["findings"]
            if item["status"] == "warning"
            and item["evidence"].get("witness") == "witness_a"
        }
        self.assertNotIn("archaic_introduction", good_warnings)
        self.assertNotIn("archaic_residue", good_warnings)

        unchanged = run_deterministic_checks(
            self._modernization_chunk("many sects have arisen since their time"),
            "many sects have arisen since their time",
            "many sects have arisen since their time",
        )
        unchanged_warnings = {
            item["check"]
            for item in unchanged["findings"]
            if item["status"] == "warning"
            and item["evidence"].get("witness") == "witness_a"
        }
        self.assertNotIn("unnecessary_lexical_churn", unchanged_warnings)
        self.assertNotIn("archaic_introduction", unchanged_warnings)

    def test_mixed_paragraph_allows_minimal_modernization(self):
        source = (
            "And that thou mayest learn that this was far better, hear what He "
            "saith by the Prophet. For many sects have arisen since their time. "
            "But if there were any hostility in their statements, neither would "
            "the sects have received all."
        )
        target = (
            "And that you may learn that this was far better, hear what He "
            "says by the Prophet. For many sects have arisen since their time. "
            "But if there were any hostility in their statements, neither would "
            "the sects have received all."
        )
        result = run_deterministic_checks(
            self._modernization_chunk(source),
            target,
            target,
        )
        warnings = [
            item
            for item in result["findings"]
            if item["status"] == "warning"
            and item["evidence"].get("witness") == "witness_a"
        ]
        self.assertEqual(warnings, [])

    def test_modernization_direction_checks_respect_source_and_quotes(self):
        chunk = {
            "source_text": 'He saith, "thou art beloved." God hath made manifest.',
            "target_latin": 'He saith, "thou art beloved." God hath made manifest.',
            "task_type": "modernization",
            "project": {"task_type": "modernization"},
            "checks": {
                "archaic_residue_terms": ["thou", "art", "saith", "hath"],
                "reverse_modernization_pairs": {"has": "hath"},
            },
            "source_spans": [],
            "page_markers": [],
            "source": {"pages": []},
            "annotations": [],
        }

        good = run_deterministic_checks(
            chunk,
            'He says, "you are beloved." God has made manifest.',
            'He saith, "thou art beloved." God hath made manifest.',
        )
        good_warnings = {
            item["check"]
            for item in good["findings"]
            if item["status"] == "warning"
            and item["evidence"].get("witness") == "witness_a"
        }
        self.assertNotIn("archaic_introduction", good_warnings)
        self.assertNotIn("archaic_residue", good_warnings)

        residue = run_deterministic_checks(
            chunk,
            'He saith, "thou art beloved." God hath made manifest.',
            'He says, "thou art beloved." God has made manifest.',
        )
        residue_warnings = {
            item["check"]
            for item in residue["findings"]
            if item["status"] == "warning"
            and item["evidence"].get("witness") == "witness_a"
        }
        self.assertIn("archaic_residue", residue_warnings)
        self.assertNotIn("archaic_introduction", residue_warnings)

    def test_ordinary_quoted_archaism_is_modernization_residue(self):
        chunk = self._modernization_chunk('“that thou mayest hold”')

        result = run_deterministic_checks(
            chunk,
            '“that thou mayest hold”',
            '“that you may hold”',
        )
        warnings = {
            item["check"]: item
            for item in result["findings"]
            if item["status"] == "warning"
            and item["evidence"].get("witness") == "witness_a"
        }
        self.assertIn("archaic_residue", warnings)
        self.assertEqual(
            warnings["archaic_residue"]["evidence"]["terms"],
            ["mayest", "thou"],
        )
        self.assertFalse(
            warnings["archaic_residue"]["evidence"]["ordinary_quotation_marks_protected"]
        )

        good = run_deterministic_checks(
            chunk,
            '“that you may hold”',
            '“that thou mayest hold”',
        )
        good_warnings = {
            item["check"]
            for item in good["findings"]
            if item["status"] == "warning"
            and item["evidence"].get("witness") == "witness_a"
        }
        self.assertNotIn("archaic_residue", good_warnings)

    def test_explicit_protected_quotation_is_exempt_from_residue(self):
        source = 'Before “thou mayest” after.'
        protected = "“thou mayest”"
        start = source.index(protected)
        chunk = {
            **self._modernization_chunk(source),
            "protected_spans": [{"start": start, "end": start + len(protected)}],
        }

        result = run_deterministic_checks(
            chunk,
            source,
            source,
        )
        warnings = {
            item["check"]
            for item in result["findings"]
            if item["status"] == "warning"
            and item["evidence"].get("witness") == "witness_a"
        }
        self.assertNotIn("archaic_residue", warnings)

    def test_quotation_with_already_modern_english_can_remain_unchanged(self):
        source = '"For every kingdom divided against itself shall not stand."'
        result = run_deterministic_checks(
            self._modernization_chunk(source),
            source,
            source,
        )
        warnings = {
            item["check"]
            for item in result["findings"]
            if item["status"] == "warning"
            and item["evidence"].get("witness") == "witness_a"
        }
        self.assertNotIn("quoted_material", warnings)
        self.assertNotIn("archaic_residue", warnings)

    def test_disabled_latin_stages_are_cached_as_skipped(self):
        with tempfile.TemporaryDirectory() as directory:
            config = isolated_chrysostom_config(directory)
            _, chunks = preprocess_book(config, 1)
            pipeline = EvidenceFirstPipeline(config, lexicon=StubLexicon())

            result = pipeline.run_chunk(chunks[0], through="structural_parse")

            self.assertEqual(result["status"], "partial")
            self.assertEqual(
                result["completed_stages"], ["morphology", "structural_parse"]
            )
            self.assertEqual(
                result["records"]["morphology"]["output"]["status"], "skipped"
            )
            self.assertEqual(
                result["records"]["structural_parse"]["output"]["status"], "skipped"
            )
            morphology_inputs = result["records"]["morphology"]["cache_material"]["inputs"]
            self.assertIn("source_text", morphology_inputs)
            self.assertNotIn("target_latin", morphology_inputs)

    def test_source_retrieval_and_evidence_kind_gating_are_project_specific(self):
        with tempfile.TemporaryDirectory() as directory:
            config = isolated_chrysostom_config(directory)
            build_concordance(config, include_lemmas=False)
            retrieval = build_retrieval_index(config)
            self.assertEqual(retrieval["method"], "source_tfidf_lsa_v1")

            service = EvidenceService.from_config(config, StubLexicon())
            identity = service.cache_identity()
            self.assertEqual(identity["enabled_kinds"], ["corpus_related", "semantic_rag", "source_edition"])
            disabled = service.execute(
                {"kind": "morphology", "query": "preventeth"},
                requested_by="test",
            )
            self.assertEqual(disabled["status"], "unavailable")
            self.assertIn("disabled by project", disabled["message"])

            semantic = service.execute(
                {"kind": "semantic_rag", "query": "repentance mercy"},
                requested_by="test",
            )
            self.assertEqual(semantic["status"], "found")
            self.assertEqual(semantic["retrieval_method"]["method"], "source_tfidf_lsa_v1")

    def test_prompts_and_review_labels_use_project_source_label(self):
        with tempfile.TemporaryDirectory() as directory:
            config = isolated_chrysostom_config(directory)
            _, chunks = preprocess_book(config, 1)
            task = TaskProfile.from_config(config)
            prompt = witness_prompt(chunks[0], task)
            self.assertIn("Conservatively modernize this historical English passage", prompt)
            self.assertIn("A good modernization may be almost identical", prompt)
            self.assertIn("Never move backward into older English", prompt)
            self.assertIn("For he says that this is manifest", prompt)
            self.assertIn("BAD: For he saith", prompt)
            self.assertIn("For many sects have arisen since their time", prompt)
            self.assertIn("BAD: For many sects had birth", prompt)
            self.assertIn("<SOURCE_TEXT", prompt)
            self.assertNotIn("<TARGET_LATIN", prompt)
            self.assertIn("archaic introduction", task.prosecutor_brief()["focus"])
            self.assertIn("fewer unnecessary changes", task.adjudicator_brief()["task_rules"])

            audit = {
                "chunk_id": "modernization-fixture",
                "project": chunks[0]["project"],
                "source": chunks[0]["source"],
                "source_text": chunks[0]["source_text"],
                "target_latin": chunks[0]["target_latin"],
                "context_before": "",
                "context_after": "",
                "source_units": chunks[0]["source_units"],
                "page_markers": chunks[0]["page_markers"],
                "source_spans": chunks[0]["source_spans"],
                "annotations": chunks[0]["annotations"],
                "stages": {},
            }
            view = build_review_view(audit)
            self.assertEqual(view["source"]["label"], "Historical English")

    def test_actual_modernization_prosecutor_and_adjudicator_prompts_are_conservative(self):
        chunk = self._modernization_chunk(
            "For many sects have arisen since their time. He says that God has made manifest."
        )
        task = TaskProfile.from_config(load_config(PROJECT_CONFIG))
        checks = run_deterministic_checks(
            chunk,
            "For many sects had birth since their time. He saith that God hath made manifest.",
            "For many sects have arisen since their time. He says that God has made manifest.",
        )
        prosecutor = budgeted_prosecutor_prompt(
            chunk,
            {"sentences": [], "intrinsic_ambiguity": [], "context_dependent": [], "unverified_analyses": []},
            {"flags": []},
            checks,
            "For many sects had birth since their time. He saith that God hath made manifest.",
            "For many sects have arisen since their time. He says that God has made manifest.",
            max_evidence_requests=0,
            budget={
                "max_prompt_utf8_bytes": 40000,
                "max_request_utf8_bytes": 42000,
                "max_estimated_prompt_tokens": 15000,
                "estimator_bytes_per_token": 3.0,
            },
            task=task,
        )
        self.assertTrue(prosecutor.fits)
        self.assertIn("MODERNIZATION REVIEW CONTRACT", prosecutor.prompt)
        self.assertIn("source wording have safely remained unchanged", prosecutor.prompt)
        self.assertIn("task-direction error", prosecutor.prompt)
        self.assertIn("paraphrase|preposition", prosecutor.prompt)
        self.assertIn(
            "at most 8 distinct challenges", " ".join(prosecutor.prompt.split())
        )

        adjudicator = adjudicator_prompt(
            chunk,
            "For many sects had birth since their time. He saith that God hath made manifest.",
            "For many sects have arisen since their time. He says that God has made manifest.",
            {"sentences": [], "intrinsic_ambiguity": [], "context_dependent": [], "unverified_analyses": []},
            {"flags": []},
            checks,
            {"status": "grounded_challenge", "summary": "", "challenges": [], "evidence_requests": []},
            [],
            task=task,
        )
        self.assertIn("MODERNIZATION DECISION CONTRACT", adjudicator)
        self.assertIn("Prefer the smallest change necessary", adjudicator)
        self.assertIn("changed-word count", adjudicator)

    def test_modernization_adjudicator_invalid_exact_edits_become_human_review(self):
        task = TaskProfile.from_config(load_config(PROJECT_CONFIG))
        decision = {
            "status": "corrected",
            "base_witness": "a",
            "edits": [
                {
                    "old": "Thou shalt never find this span.",
                    "new": "You will never find this span.",
                    "reason": "Modernize pronoun.",
                    "evidence_ids": [],
                }
            ],
            "summary": "Modernization edit proposed.",
            "coverage": {"all_clauses_accounted_for": True, "omissions_corrected": []},
            "findings": [],
            "unresolved_issues": [],
            "human_review_requests": [],
            "evidence_requests": [],
            "decision_basis": [],
        }
        result = EvidenceFirstPipeline._expand_adjudication_for_task(
            decision,
            "You should preserve this base witness.",
            "Alternate witness.",
            allowed_base_witnesses=["a"],
            task=task,
        )
        self.assertEqual(result["status"], "human_review")
        self.assertEqual(result["final_draft"], "You should preserve this base witness.")
        self.assertEqual(result["coverage"]["applied_edits"], [])
        self.assertEqual(
            result["coverage"]["edit_application_mode"],
            "invalid_exact_edit_human_review_fallback",
        )
        self.assertIn("not be applied mechanically", result["human_review_requests"][0]["issue"])

    def test_deterministic_challenge_suite_catches_planted_modernization_errors(self):
        with tempfile.TemporaryDirectory() as directory:
            config = isolated_chrysostom_config(directory)
            results = run_challenges(
                config,
                lexicon=StubLexicon(),
                deterministic_only=True,
            )
            metrics = challenge_metrics(results)
            self.assertEqual(metrics["cases"], 8)
            self.assertEqual(metrics["planted_errors"], 9)
            self.assertEqual(metrics["planted_errors_missed"], 0)
            self.assertEqual(metrics["false_positive_clean_cases"], 0)


if __name__ == "__main__":
    unittest.main()
