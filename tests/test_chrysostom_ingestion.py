from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from interpres.source import make_chunks, parse_homily_directory
from split_chrysostom import (
    normalize_body_text,
    remove_headers_and_extract_notes,
    split_homilies,
)


class ChrysostomCleanupTest(unittest.TestCase):
    def test_homily_heading_with_footnote_marker_and_index_tail(self):
        raw = (
            "Homily XIX.\nBody before the next homily.\n\n"
            "Homily XX.883\nMatt. VI. 16.\nText of recovered homily.\n\n"
            "Index of Subjects\nThis is not homily text.\n"
        )

        homilies = split_homilies(raw)

        self.assertEqual([item[0] for item in homilies], [19, 20])
        self.assertIn("Text of recovered homily", homilies[1][2])
        self.assertNotIn("Index of Subjects", homilies[1][2])

    def test_extracts_page_bottom_notes_and_repairs_interrupted_word(self):
        raw = (
            "Homily XVI.\nThe law is dis661\n"
            "[tn eremnon.]\n"
            "662\nMatt. v. 22.\n"
            "190\nMatthew V. 17.\n\n"
            "turbed for its preservation, and this remains body text.\n"
        )

        body, notes, markers = remove_headers_and_extract_notes(raw)
        clean = normalize_body_text(body, markers)

        self.assertIn("disturbed for its preservation", clean)
        self.assertNotIn("[tn eremnon.]", clean)
        self.assertIn("661", markers)
        self.assertIn("662", markers)
        self.assertIn("Matt. v. 22.", notes)
        self.assertIn("[tn eremnon.]", raw)

    def test_removes_footnote_markers_but_retains_real_numbers(self):
        raw = (
            "Homily I.\nMatt. I. 1. “The book of the generation.” "
            "Keep 99 sheep and the section below. This is remembrance.”17\n"
            "17\nJohn xiv. 26.\n"
            "83\nMatthew I. 1.\n\n"
            "2. Reflect then how great an evil it is.\n"
        )

        body, notes, markers = remove_headers_and_extract_notes(raw)
        clean = normalize_body_text(body, markers)

        self.assertIn("Matt. I. 1.", clean)
        self.assertIn("99 sheep", clean)
        self.assertIn("2. Reflect then", clean)
        self.assertNotIn("remembrance.”17", clean)
        self.assertIn("John xiv. 26.", notes)


class ChrysostomDirectoryParserTest(unittest.TestCase):
    def _fixture(self, root: Path) -> tuple[Path, Path]:
        clean = root / "clean"
        notes = root / "notes"
        clean.mkdir()
        notes.mkdir()
        (clean / "homily-001.txt").write_text(
            (
                "Homily I. Opening prose has no printed section one. "
                "It remains literal source text.\n\n"
                "2. Reflect then how great an evil it is. Another sentence follows.\n\n"
                "3. How then was that law given in time past? It was given later."
            ),
            encoding="utf-8",
        )
        (clean / "homily-002.txt").write_text(
            (
                "Homily II. Matt. I. 1. “The book of the generation.” "
                "The citation number is not an internal section.\n\n"
                "2. But what is this vestibule? It is the beginning."
            ),
            encoding="utf-8",
        )
        (notes / "homily-001.notes.txt").write_text(
            "17\nJohn xiv. 26.\n",
            encoding="utf-8",
        )
        return clean, notes

    def test_parses_implicit_and_explicit_sections_with_stable_ids(self):
        with tempfile.TemporaryDirectory() as directory:
            clean, notes = self._fixture(Path(directory))
            parsed = parse_homily_directory(
                clean,
                book=1,
                metadata={"work": "Homilies on Matthew"},
                notes_path=notes,
            )

        units = parsed["source_units"]
        self.assertEqual(
            [unit["source_unit_id"] for unit in units],
            [
                "book01-homily-001-section-001",
                "book01-homily-001-section-002",
                "book01-homily-001-section-003",
                "book01-homily-002-section-001",
                "book01-homily-002-section-002",
            ],
        )
        self.assertFalse(units[0]["section_number_explicit"])
        self.assertTrue(units[1]["section_number_explicit"])
        self.assertNotIn("1. Opening", units[0]["text"])
        self.assertIn("2. Reflect then", units[1]["text"])
        self.assertEqual(units[1]["anchor"], "homily-1-section-2")
        self.assertEqual(parsed["apparatus"][0]["association"], "homily_level")
        self.assertNotIn("John xiv. 26.", parsed["text"])

    def test_chunking_preserves_section_provenance_and_homily_boundaries(self):
        with tempfile.TemporaryDirectory() as directory:
            clean, notes = self._fixture(Path(directory))
            parsed = parse_homily_directory(clean, book=1, notes_path=notes)
            chunks = make_chunks(
                parsed,
                {
                    "target_source_units": 2,
                    "min_source_units": 1,
                    "max_source_units": 2,
                    "max_chars": 1000,
                    "context_units": 1,
                    "context_max_chars": 200,
                },
            )

        self.assertEqual(len(chunks), 3)
        self.assertEqual(
            chunks[0]["source"]["section_ids"],
            [
                "book01-homily-001-section-001",
                "book01-homily-001-section-002",
            ],
        )
        self.assertNotEqual(
            chunks[1]["source_units"][-1]["homily_number"],
            chunks[2]["source_units"][0]["homily_number"],
        )
        self.assertTrue(
            all(
                len({unit["homily_number"] for unit in chunk["source_units"]}) == 1
                for chunk in chunks
            )
        )

    def test_large_section_split_retains_original_section_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            clean = root / "clean"
            clean.mkdir()
            (clean / "homily-001.txt").write_text(
                (
                    "Homily I. Opening sentence.\n\n"
                    "2. First long sentence has enough words to cross the tiny "
                    "test limit. Second long sentence also has enough words to "
                    "be split cleanly. Third long sentence completes the section."
                ),
                encoding="utf-8",
            )
            parsed = parse_homily_directory(clean, book=1)
            chunks = make_chunks(
                parsed,
                {
                    "target_source_units": 1,
                    "min_source_units": 1,
                    "max_source_units": 1,
                    "max_chars": 75,
                    "context_units": 1,
                    "context_max_chars": 200,
                },
            )

        split_chunks = [
            chunk
            for chunk in chunks
            if chunk["source"]["section_ids"] == ["book01-homily-001-section-002"]
        ]
        self.assertGreater(len(split_chunks), 1)
        self.assertTrue(
            all(
                chunk["source_units"][0]["canonical_parent_id"]
                == "book01-homily-001-section-002"
                for chunk in split_chunks
            )
        )
        self.assertTrue(
            all(".p" in chunk["source_units"][0]["source_unit_id"] for chunk in split_chunks)
        )


if __name__ == "__main__":
    unittest.main()
