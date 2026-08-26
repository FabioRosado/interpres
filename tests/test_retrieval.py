from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from jerome_pipeline.config import PipelineConfig
from jerome_pipeline.evidence import EvidenceService
from jerome_pipeline.retrieval import (
    INDEX_METHOD,
    LocalRetrievalIndex,
    build_local_retrieval_index,
)


class LocalRetrievalIndexTest(unittest.TestCase):
    def test_persisted_lsa_index_is_reproducible_and_returns_source_text(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            concordance = root / "concordance.jsonl"
            rows = [
                {
                    "source_unit_id": "u1",
                    "book": 1,
                    "page": "1A",
                    "text": "concaluit cor meum ignis in meditatione",
                    "source_fingerprint": "f1",
                    "provenance": {"source_unit_id": "u1", "page": "1A"},
                },
                {
                    "source_unit_id": "u2",
                    "book": 1,
                    "page": "1B",
                    "text": "ignis et flamma ardet in corde",
                    "source_fingerprint": "f2",
                    "provenance": {"source_unit_id": "u2", "page": "1B"},
                },
                {
                    "source_unit_id": "u3",
                    "book": 1,
                    "page": "2A",
                    "text": "aqua frigida fluit de fonte",
                    "source_fingerprint": "f3",
                    "provenance": {"source_unit_id": "u3", "page": "2A"},
                },
                {
                    "source_unit_id": "u4",
                    "book": 1,
                    "page": "2B",
                    "text": "Ezechiel propheta visionem narrat",
                    "source_fingerprint": "f4",
                    "provenance": {"source_unit_id": "u4", "page": "2B"},
                },
            ]
            concordance.write_text(
                "".join(json.dumps(row) + "\n" for row in rows),
                encoding="utf-8",
            )
            output = root / "retrieval.json"
            first = build_local_retrieval_index(
                concordance, output, dimensions=3
            )
            second = build_local_retrieval_index(
                concordance, output, dimensions=3
            )
            self.assertEqual(first["index_digest"], second["index_digest"])
            self.assertEqual(first["method"], INDEX_METHOD)
            index = LocalRetrievalIndex(output)
            results = index.search("ignis in corde", limit=3)
            self.assertEqual(results[0]["source_unit_id"], "u2")
            self.assertEqual(results[0]["text"], rows[1]["text"])
            self.assertEqual(results[0]["provenance"]["page"], "1B")
            self.assertEqual(results[0]["index_digest"], first["index_digest"])
            self.assertEqual(index.search("xyzzy", limit=3), [])

            config = PipelineConfig(
                path=root / "pipeline.yaml",
                root=root,
                data={
                    "evidence": {
                        "semantic_search_enabled": True,
                        "max_results_per_request": 3,
                        "snippet_chars": 120,
                    }
                },
            )
            service = EvidenceService(
                config,
                lexicon=None,  # type: ignore[arg-type]
                concordance=None,
                scripture=None,
                retrieval=index,
            )
            found = service.execute(
                {"kind": "semantic_rag", "query": "ignis in corde"},
                requested_by="test",
            )
            no_hit = service.execute(
                {"kind": "semantic_rag", "query": "xyzzy"},
                requested_by="test",
            )
            unavailable = EvidenceService(
                config,
                lexicon=None,  # type: ignore[arg-type]
                concordance=None,
                scripture=None,
            ).execute(
                {"kind": "semantic_rag", "query": "ignis in corde"},
                requested_by="test",
            )
            self.assertEqual(found["status"], "found")
            self.assertEqual(
                found["retrieval_method"]["index_digest"],
                first["index_digest"],
            )
            self.assertEqual(no_hit["status"], "no_evidence_found")
            self.assertEqual(unavailable["status"], "unavailable")


if __name__ == "__main__":
    unittest.main()
