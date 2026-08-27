from __future__ import annotations

import unittest

from interpres.source import make_chunks, parse_source

FIXTURE = """Download header
LIBER PRIMUS.
----[page 0001A]----
1-2 Prima sententia manet integra. Altera sententia[1] quoque manet.
____________
1: (Psal. I, 1)

----[page 0001B]----
3 Tertia sententia finitur. Quarta 6 quoque finitur (Naum I, 3). Continuatio 2).
----[page 0001C]----
4 Quinta sententia finitur.
----[page 0001D]----
5 Sexta sententia finitur.
----[page 0002A]----
6 Septima sententia finitur.
"""


class SourceParserTest(unittest.TestCase):
    def setUp(self):
        self.parsed = parse_source(FIXTURE, book=1, metadata={"corpus": "fixture"})

    def test_preserves_page_units_and_raw_markers(self):
        self.assertEqual(len(self.parsed["source_units"]), 5)
        self.assertEqual(self.parsed["source_units"][0]["source_unit_id"], "book01-pl-0001A")
        self.assertEqual(self.parsed["page_markers"][0]["raw"], "----[page 0001A]----")
        self.assertNotIn("[page", self.parsed["text"])
        self.assertNotIn("1-2 Prima", self.parsed["text"])
        self.assertIn("Prima sententia", self.parsed["text"])

    def test_links_footnote_without_translating_marker(self):
        notes = [item for item in self.parsed["annotations"] if item["type"] == "editorial_reference"]
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0]["reference"], "(Psal. I, 1)")
        self.assertEqual(notes[0]["raw_definition"], "1: (Psal. I, 1)")
        self.assertNotIn("[1]", self.parsed["text"])
        self.assertEqual(self.parsed["unmatched_footnote_definitions"], {})

    def test_removes_inline_single_edition_pagination_but_preserves_citations(self):
        self.assertNotIn("Quarta 6 quoque", self.parsed["text"])
        self.assertIn("Quarta quoque", self.parsed["text"])
        self.assertIn("(Naum I, 3)", self.parsed["text"])
        self.assertIn("Continuatio 2).", self.parsed["text"])
        pagination = [
            item
            for item in self.parsed["annotations"]
            if item["type"] == "edition_pagination"
        ]
        self.assertIn("6", {item["value"] for item in pagination})

    def test_groups_units_and_separates_context_spans(self):
        chunks = make_chunks(
            self.parsed,
            {
                "target_source_units": 3,
                "min_source_units": 2,
                "max_source_units": 3,
                "max_chars": 1000,
                "context_units": 1,
                "context_max_chars": 200,
            },
        )
        self.assertEqual(len(chunks), 2)
        self.assertEqual(chunks[0]["source"]["pages"], ["0001A", "0001B", "0001C"])
        self.assertEqual(chunks[0]["context_before"], "")
        self.assertEqual(chunks[0]["context_after"], self.parsed["source_units"][3]["text"])
        self.assertNotIn(chunks[0]["context_after"], chunks[0]["target_latin"])
        roles = {span["role"] for span in chunks[0]["source_spans"]}
        self.assertEqual(roles, {"target", "context_after"})
        self.assertEqual(
            [marker["page"] for marker in chunks[0]["page_markers"]],
            chunks[0]["source"]["pages"],
        )

    def test_chunk_ids_are_deterministic(self):
        settings = {
            "target_source_units": 3,
            "min_source_units": 2,
            "max_source_units": 3,
            "max_chars": 1000,
            "context_units": 1,
            "context_max_chars": 200,
        }
        first = make_chunks(self.parsed, settings)
        second = make_chunks(self.parsed, settings)
        self.assertEqual([item["chunk_id"] for item in first], [item["chunk_id"] for item in second])

    def test_abnormally_large_unit_splits_only_at_sentence_boundaries(self):
        parsed = parse_source(
            "LIBER PRIMUS.\n[page 0001A]\nPrima sententia satis longa est. Secunda sententia satis longa est. Tertia sententia finitur.\n",
            book=1,
        )
        chunks = make_chunks(
            parsed,
            {
                "target_source_units": 1,
                "min_source_units": 1,
                "max_source_units": 1,
                "max_chars": 45,
                "context_units": 1,
                "context_max_chars": 100,
            },
        )
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(chunk["target_latin"].endswith(".") for chunk in chunks))
        self.assertTrue(all(".p" in chunk["source"]["source_unit_ids"][0] for chunk in chunks))


if __name__ == "__main__":
    unittest.main()
