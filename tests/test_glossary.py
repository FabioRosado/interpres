from __future__ import annotations

import unittest

from glossary import (
    KNOWN_PROPER_NOUNS,
    LexicalFlag,
    MorphologicalCandidate,
    Sense,
    WhitakersWordsBackend,
    WordAnalysis,
    analyze_chunk,
    flags_to_json,
)


class FakeBackend:
    backend_name = "fake"
    contract_version = "fake/v1"

    def analyze_word(self, word: str) -> WordAnalysis:
        if word == "concaluit":
            return WordAnalysis(
                token=word,
                senses=[Sense("concalesco", "v", "become warm")],
                candidates=[MorphologicalCandidate("concalesco", "v")],
            )
        if word == "plagas":
            return WordAnalysis(
                token=word,
                senses=[Sense("plaga", "n", "region"), Sense("plago", "v", "strike")],
                candidates=[MorphologicalCandidate("plaga", "n"), MorphologicalCandidate("plago", "v")],
            )
        return WordAnalysis(token=word, found=False)


class GlossaryUnitTest(unittest.TestCase):
    def test_known_trap_uses_observed_lemma(self):
        flags = analyze_chunk("concaluit cor", FakeBackend())
        trap = next(flag for flag in flags if flag.flag_type == "known_trap")
        self.assertEqual(trap.token, "concaluit")
        self.assertIn("grow warm", trap.senses)

    def test_ambiguity_and_not_found_and_proper_name(self):
        flags = analyze_chunk("plagas xyzzynomen Ezechielem", FakeBackend())
        by_token = {flag.token: flag.flag_type for flag in flags}
        self.assertEqual(by_token["plagas"], "ambiguous_senses")
        self.assertEqual(by_token["xyzzynomen"], "not_found")
        self.assertNotIn("Ezechielem", by_token)
        self.assertIn("Ezechielem", KNOWN_PROPER_NOUNS)

    def test_flag_serialization(self):
        value = flags_to_json([LexicalFlag("x", 2, "not_found", [], "note")])
        self.assertEqual(value, [{"token": "x", "offset": 2, "flag_type": "not_found", "senses": [], "note": "note"}])


class InstalledWhitakersContractTest(unittest.TestCase):
    """Contract tests derived from the installed Parser API, not guessed calls."""

    @classmethod
    def setUpClass(cls):
        cls.backend = WhitakersWordsBackend()

    def test_memoriae(self):
        result = self.backend.analyze_word("memoriae")
        self.assertTrue(result.found)
        self.assertIn("memoria", {sense.lemma for sense in result.senses})
        cases = {candidate.features.get("Case") for candidate in result.candidates}
        self.assertTrue({"Genitive", "Dative"} <= cases)

    def test_concaluit_and_plagas(self):
        concaluit = self.backend.analyze_word("concaluit")
        self.assertIn("concalesco", {sense.lemma for sense in concaluit.senses})
        plagas = self.backend.analyze_word("plagas")
        self.assertTrue({"plaga", "plago"} <= {sense.lemma for sense in plagas.senses})

    def test_tribus_context_contract_and_backend_gap(self):
        # The deterministic word parser receives the same surface candidate in
        # both phrases; syntax/context belongs to the blind structural stage.
        tribus = self.backend.analyze_word("tribus")
        tribusque = self.backend.analyze_word("tribusque")
        self.assertTrue(tribus.found)
        self.assertTrue(any(candidate.enclitic == "que" for candidate in tribusque.candidates))
        self.assertIn("Dative", {candidate.features.get("Case") for candidate in tribus.candidates})
        # Observed package limitation: `tribus Judae` does not surface the noun
        # "tribe". The LLM must record any such proposal as unverified.
        self.assertNotIn("tribus", {sense.lemma for sense in tribus.senses})

    def test_proper_and_unknown_forms_are_not_fabricated(self):
        self.assertFalse(self.backend.analyze_word("ezechielem").found)
        self.assertFalse(self.backend.analyze_word("xyzzynomen").found)


if __name__ == "__main__":
    unittest.main()

