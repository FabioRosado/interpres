from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from jerome_pipeline.cache import canonical_digest
from jerome_pipeline.evidence import (
    AuthorityIndex,
    EvidenceService,
    JeromeConcordance,
    ScriptureCorpus,
    bound_evidence_results,
    build_concordance,
    build_retrieval_index,
    canonical_source_manifest,
    normalize_latin,
)
from jerome_pipeline.config import PipelineConfig, load_config


class FreshnessLexicon:
    backend_name = "freshness-fixture"
    contract_version = "fixture/v1"

    def analyze_word(self, word):
        raise AssertionError("lemma analysis is not used by this fixture")


class FakeWebBackend:
    backend_name = "fixture-search"

    def __init__(self):
        self.queries: list[str] = []

    def search(self, query: str, *, limit: int):
        self.queries.append(query)
        return [
            {
                "title": "Unverified research lead",
                "url": "https://example.invalid/lead",
                "text": "A lead requiring primary-source verification.",
            }
        ][:limit]


class EvidenceTest(unittest.TestCase):
    def test_normalization(self):
        self.assertEqual(normalize_latin("Jūxta Vulgatam, cæli!"), "iuxta uulgatam caeli")

    def test_concordance_exact_lemma_and_semantic(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "index.jsonl"
            rows = [
                {"source_unit_id": "u1", "book": 1, "page": "1A", "text": "concaluit cor meum", "normalized": normalize_latin("concaluit cor meum"), "lemmas": ["concalesco"], "provenance": {"source_unit_id": "u1"}},
                {"source_unit_id": "u2", "book": 1, "page": "1B", "text": "ignis in corde", "normalized": normalize_latin("ignis in corde"), "lemmas": ["ignis"], "provenance": {"source_unit_id": "u2"}},
                {"source_unit_id": "u3", "book": 2, "page": "2A", "text": "incipit liber alter", "normalized": normalize_latin("incipit liber alter"), "lemmas": ["incipio"], "provenance": {"source_unit_id": "u3"}},
            ]
            path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
            concordance = JeromeConcordance(path)
            exact = concordance.exact("concaluit cor")[0]
            self.assertEqual(exact["provenance"]["source_unit_id"], "u1")
            self.assertIsNone(exact["context_before"])
            self.assertEqual(exact["context_after"], "ignis in corde")
            lemma = concordance.lemma("concalesco")[0]
            self.assertEqual(lemma["provenance"]["source_unit_id"], "u1")
            self.assertEqual(
                lemma["context_provenance"]["context_after"]["source_unit_id"],
                "u2",
            )
            book_boundary = concordance.exact("ignis in corde")[0]
            self.assertIsNone(book_boundary["context_after"])
            self.assertEqual(concordance.semantic("ignis corde")[0]["provenance"]["source_unit_id"], "u2")

    def test_content_freshness_rejects_stale_concordance_and_retrieval(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "book1.txt"
            source.write_text(
                "Header\nLIBER PRIMUS.\n----[page 0001A]----\nPrima sententia manet.\n",
                encoding="utf-8",
            )
            base = load_config()
            data = copy.deepcopy(base.data)
            data["source"]["books"] = {"1": str(source)}
            data["paths"]["artifacts"] = str(root / "artifacts")
            data["paths"]["concordance"] = str(root / "concordance.jsonl")
            data["paths"]["retrieval_index"] = str(root / "retrieval.json")
            config = PipelineConfig(path=base.path, root=root, data=data)

            concordance_build = build_concordance(
                config, books=[1], include_lemmas=False
            )
            retrieval_build = build_retrieval_index(config)
            manifest = canonical_source_manifest(config, [1])
            self.assertEqual(
                concordance_build["canonical_source_digest"],
                manifest["canonical_source_digest"],
            )
            self.assertEqual(
                retrieval_build["canonical_source_digest"],
                manifest["canonical_source_digest"],
            )
            service = EvidenceService.from_config(config, FreshnessLexicon())
            self.assertTrue(service.concordance.freshness["fresh"])
            self.assertTrue(service.retrieval_freshness["fresh"])
            self.assertEqual(
                service.execute(
                    {"kind": "jerome_phrase", "query": "Prima sententia"},
                    requested_by="test",
                )["status"],
                "found",
            )

            # A single forged per-unit fingerprint is independently detected
            # even when the metadata records digest is recomputed to match the
            # tampered JSONL and the canonical-source digest is left intact.
            concordance_path = config.path_value("concordance")
            rows = [
                json.loads(line)
                for line in concordance_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            rows[0]["source_fingerprint"] = "forged-unit-fingerprint"
            concordance_path.write_text(
                "".join(
                    json.dumps(row, ensure_ascii=False, separators=(",", ":"))
                    + "\n"
                    for row in rows
                ),
                encoding="utf-8",
            )
            metadata_path = concordance_path.with_suffix(
                concordance_path.suffix + ".meta.json"
            )
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            metadata["records_digest"] = canonical_digest(rows)
            metadata_path.write_text(
                json.dumps(metadata, ensure_ascii=False, separators=(",", ":"))
                + "\n",
                encoding="utf-8",
            )
            unit_tampered = EvidenceService.from_config(
                config, FreshnessLexicon()
            )
            self.assertFalse(unit_tampered.concordance.freshness["fresh"])
            self.assertIn(
                "concordance unit fingerprints differ from canonical source",
                unit_tampered.concordance.freshness["reasons"],
            )
            self.assertEqual(
                unit_tampered.execute(
                    {"kind": "jerome_phrase", "query": "Prima"},
                    requested_by="test",
                )["status"],
                "stale_evidence",
            )
            build_concordance(config, books=[1], include_lemmas=False)

            # Same filename, changed source content: both persisted artifacts
            # must be refused by content identity rather than timestamps.
            source.write_text(
                "Header\nLIBER PRIMUS.\n----[page 0001A]----\nAltera sententia manet.\n",
                encoding="utf-8",
            )
            stale = EvidenceService.from_config(config, FreshnessLexicon())
            self.assertFalse(stale.concordance.freshness["fresh"])
            self.assertEqual(
                stale.execute(
                    {"kind": "jerome_phrase", "query": "Prima"},
                    requested_by="test",
                )["status"],
                "stale_evidence",
            )
            self.assertEqual(
                stale.execute(
                    {"kind": "semantic_rag", "query": "sententia"},
                    requested_by="test",
                )["status"],
                "stale_evidence",
            )

            # Rebuilding only the concordance restores exact retrieval but the
            # old semantic index remains stale until independently rebuilt.
            build_concordance(config, books=[1], include_lemmas=False)
            half_rebuilt = EvidenceService.from_config(config, FreshnessLexicon())
            self.assertTrue(half_rebuilt.concordance.freshness["fresh"])
            self.assertFalse(half_rebuilt.retrieval_freshness["fresh"])
            self.assertEqual(
                half_rebuilt.execute(
                    {"kind": "semantic_rag", "query": "sententia"},
                    requested_by="test",
                )["status"],
                "stale_evidence",
            )
            build_retrieval_index(config)
            rebuilt = EvidenceService.from_config(config, FreshnessLexicon())
            self.assertTrue(rebuilt.concordance.freshness["fresh"])
            self.assertTrue(rebuilt.retrieval_freshness["fresh"])

    def test_scripture_reference_and_no_evidence_distinction(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            vulgate = root / "vul.tsv"
            # Deliberate duplicate verifies corpus de-duplication.
            row = "Psalmi\tPs\t21\t38\t4\tConcaluit cor meum.\n"
            vulgate.write_text(row + row, encoding="utf-8")
            metadata = root / "books.csv"
            metadata.write_text("Ps,Psalmi\n", encoding="utf-8")
            cpdv = root / "cpdv"
            cpdv.mkdir()
            (cpdv / "psalms.json").write_text(
                json.dumps({"book": {"order": 21}, "chapters": [{"chapter": 38, "verses": [{"verse": 4, "text": "My heart grew hot."}]}]}),
                encoding="utf-8",
            )
            corpus = ScriptureCorpus(vulgate, metadata, cpdv)
            found = corpus.lookup_reference("(Psal. XXXVIII, 4)")
            self.assertTrue(found["source_annotation_verified"])
            self.assertFalse(found["textual_match_verified"])
            self.assertEqual(len(found["verses"]), 1)
            self.assertEqual(found["verses"][0]["cpdv"], "My heart grew hot.")
            missing = corpus.lookup_reference("(Psal. XXXVIII, 99)")
            self.assertFalse(missing["reference_exists"])
            near = corpus.search_phrase("Concaluit cor tuum")
            self.assertEqual(near[0]["match_kind"], "normalized_near_candidate")
            self.assertFalse(near[0]["textual_match_verified"])
            self.assertEqual(near[0]["book"], "Psalmi")
            self.assertIn("concaluit cor meum", near[0]["matched_latin"])

    def test_scripture_optional_odr_comparison_is_loaded_from_jsonl(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            vulgate = root / "vul.tsv"
            vulgate.write_text(
                "Psalmi\tPs\t21\t38\t4\tConcaluit cor meum.\n",
                encoding="utf-8",
            )
            metadata = root / "books.csv"
            metadata.write_text("Ps,Psalmi\n", encoding="utf-8")
            odr = root / "odr.jsonl"
            odr.write_text(
                json.dumps(
                    {
                        "book_order": 21,
                        "chapter": 38,
                        "verse": 4,
                        "text": "My heart became hot within me.",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            corpus = ScriptureCorpus(vulgate, metadata, odr_path=odr)
            found = corpus.lookup_reference("(Psal. XXXVIII, 4)")
            self.assertEqual(
                found["verses"][0]["odr"],
                "My heart became hot within me.",
            )
            self.assertEqual(
                found["verses"][0]["provenance"]["odr_comparison"],
                "Configured ODR verse-comparison JSONL",
            )

    def test_authority_index_and_missing_authority_are_distinct(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            authority_path = root / "chronology.jsonl"
            authority_path.write_text(
                json.dumps(
                    {
                        "entry_id": "chron-001",
                        "label": "Nebuchadnezzar chronology",
                        "aliases": ["Nabuchodonosor"],
                        "text": "Regnal chronology authority fixture for 597 BCE.",
                        "citation": "Fixture Authority 1",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            authority = AuthorityIndex(
                authority_path, authority_kind="chronology"
            )
            self.assertEqual(
                authority.search("Nabuchodonosor")[0]["entry_id"],
                "chron-001",
            )
            self.assertEqual(
                authority.search("597")[0]["entry_id"], "chron-001"
            )

            config = PipelineConfig(
                path=root / "pipeline.yaml",
                root=root,
                data={
                    "evidence": {
                        "max_results_per_request": 8,
                        "max_requests_per_round": 1,
                    }
                },
            )
            unavailable = EvidenceService(
                config,
                lexicon=None,  # type: ignore[arg-type]
                concordance=None,
                scripture=None,
            ).execute(
                {"kind": "chronology", "query": "Nabuchodonosor"},
                requested_by="test",
            )
            self.assertEqual(unavailable["status"], "unavailable")

            service = EvidenceService(
                config,
                lexicon=None,  # type: ignore[arg-type]
                concordance=None,
                scripture=None,
                authorities={"chronology": authority},
            )
            found = service.execute(
                {"kind": "chronology", "query": "Nabuchodonosor"},
                requested_by="test",
            )
            no_hit = service.execute(
                {"kind": "chronology", "query": "unrelated"},
                requested_by="test",
            )
            self.assertEqual(found["status"], "found")
            self.assertEqual(no_hit["status"], "no_evidence_found")
            bounded_round = service.execute_round(
                [
                    {"kind": "chronology", "query": "Nabuchodonosor"},
                    {"kind": "chronology", "query": "597"},
                ],
                requested_by="test",
            )
            self.assertEqual(bounded_round["request_limit"], 1)
            self.assertEqual(bounded_round["omitted_requests_count"], 1)
            self.assertEqual(len(bounded_round["evidence"]), 1)

    def test_external_web_backend_is_opt_in_and_never_verified_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            backend = FakeWebBackend()
            config = PipelineConfig(
                path=root / "pipeline.yaml",
                root=root,
                data={
                    "evidence": {
                        "external_web_enabled": False,
                        "max_results_per_request": 8,
                    }
                },
            )
            service = EvidenceService(
                config,
                lexicon=None,  # type: ignore[arg-type]
                concordance=None,
                scripture=None,
                web_backend=backend,
            )
            request = {"kind": "web_research", "query": "Jerome chronology"}
            disabled = service.execute(request, requested_by="test")
            self.assertEqual(disabled["status"], "unavailable")
            self.assertEqual(backend.queries, [])

            config.data["evidence"]["external_web_enabled"] = True
            enabled = service.execute(request, requested_by="test")
            self.assertEqual(enabled["status"], "found")
            self.assertEqual(enabled["evidence_class"], "research_lead")
            self.assertFalse(enabled["results"][0]["verified_evidence"])
            self.assertEqual(backend.queries, ["Jerome chronology"])

    def test_evidence_snippet_limit_preserves_query_and_exact_offsets(self):
        text = "alpha " * 120 + "CONCALUIT COR MEUM " + "omega " * 120
        result = bound_evidence_results(
            [{"text": text, "context_after": text, "provenance": {"source_unit_id": "u1"}}],
            query="concaluit cor meum",
            snippet_chars=180,
        )[0]
        self.assertLessEqual(len(result["text"]), 180)
        self.assertIn("CONCALUIT COR MEUM", result["text"])
        offsets = result["truncation"]["text"]
        self.assertEqual(
            result["text"], text[offsets["snippet_start"] : offsets["snippet_end"]]
        )
        self.assertEqual(offsets["original_chars"], len(text))
        self.assertLessEqual(len(result["context_after"]), 180)
        self.assertTrue(
            result["truncation"]["context_after"]["truncated"]
        )

    def test_snippet_limit_also_bounds_odr_comparisons(self):
        value = "comparison " * 100
        result = bound_evidence_results(
            [{"odr": value}], query="comparison", snippet_chars=100
        )[0]
        self.assertLessEqual(len(result["odr"]), 100)
        self.assertTrue(result["truncation"]["odr"]["truncated"])


if __name__ == "__main__":
    unittest.main()
