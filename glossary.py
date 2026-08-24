"""
glossary.py — deterministic lexical evidence layer for the Jerome pipeline.

Design goals (see project handoff, sections 37 and addendum):
  - NOT an LLM. Purely rule-based lookups against a Latin lexicon.
  - Produces a COMPACT evidence layer per chunk, not a full interlinear
    gloss for every token (avoids flooding the review sidebar).
  - Flags:
      * lexical ambiguity (multiple senses that diverge in meaning)
      * unresolved tokens (not found in lexicon)
  - Explicitly does NOT do:
      * corpus-frequency-based "rarity" (WORDS/L&S data is not a frequency
        database; do not fake this)
      * automatic gloss-vs-witness contradiction detection (too fragile
        generally — see the curated KNOWN_TRAPS list instead)

Backend is swappable via LexiconBackend. Fill in `analyze_word()` once you
have installed and inspected the actual API of whichever package you pick:
  - https://github.com/blagae/whitakers_words   (JSON output, git-installable)
  - https://github.com/HenryHeffan/PyWhitakersWords (bundles Lewis & Short)

I have not been able to verify either package's exact call signature in this
environment, so `WhitakersWordsBackend.analyze_word` below is a stub with the
shape it needs to return — wire in the real call once you've inspected the
library locally.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


# ============================================================================
# DATA SHAPES
# ============================================================================


@dataclass
class Sense:
    lemma: str
    pos: str  # part of speech, e.g. "noun", "verb"
    gloss: str  # short English gloss, e.g. "region, quarter"


@dataclass
class WordAnalysis:
    token: str
    senses: list[Sense] = field(default_factory=list)
    found: bool = True


@dataclass
class LexicalFlag:
    token: str
    offset: int  # character offset within the chunk's Latin text
    flag_type: str  # "ambiguous_senses" | "not_found" | "known_trap"
    senses: list[str]  # short human-readable gloss strings
    note: str = ""


# ============================================================================
# BACKEND ADAPTER — swap this for whichever library you actually install
# ============================================================================


class LexiconBackend(Protocol):
    def analyze_word(self, word: str) -> WordAnalysis:
        ...


class WhitakersWordsBackend:
    """
    Stub adapter. Fill in the real call once you've installed a backend and
    confirmed its API locally — do not trust this implementation as-is.
    """

    def __init__(self):
        # e.g. from whitakers_words.parser import Parser
        # self._parser = Parser()
        raise NotImplementedError(
            "Install a backend (blagae/whitakers_words or "
            "HenryHeffan/PyWhitakersWords), inspect its actual API, "
            "and implement analyze_word() below before using this class."
        )

    def analyze_word(self, word: str) -> WordAnalysis:
        # Expected shape once wired in:
        #   result = self._parser.parse(word)
        #   senses = [Sense(lemma=..., pos=..., gloss=...) for ... in result]
        #   return WordAnalysis(token=word, senses=senses, found=bool(senses))
        raise NotImplementedError


# ============================================================================
# STOPLISTS — build these up empirically from your first batch of chunks.
# Ship a small starting set; expect to grow this after reviewing false
# positives in the first few chunks.
# ============================================================================

# Function words that are morphologically ambiguous (e.g. preposition vs.
# conjunction) but trivially disambiguated by any competent reader from
# context. Without this list, ordinary sentences will flood the sidebar.
COMMON_STRUCTURAL_STOPLIST: set[str] = {
    "et", "in", "ut", "ne", "cum", "quod", "qui", "quae", "quod",
    "est", "sunt", "sed", "non", "si", "de", "ad", "ex", "a", "ab",
    "que", "atque", "vel", "aut", "enim", "autem", "nam", "igitur",
    # extend after reviewing real chunk output
}

# Proper nouns and names known in advance. Anything capitalized and not
# found in the lexicon should be checked against this list before being
# flagged as "not_found" — a classical-era lexicon will not contain most
# biblical/patristic proper names at all, and that is not itself meaningful.
KNOWN_PROPER_NOUNS: set[str] = {
    "Hieronymus", "Ezechiel", "Ezechielem", "Isaiam", "Paula",
    "Judae", "Joachin", "Jechoniae",
    # extend from source annotations / footnote definitions as you go
}

# Curated known translation traps — hand-built, grows every time a new one
# is caught. Deliberately NOT a general contradiction detector (see module
# docstring) — only exact, previously-verified cases.
KNOWN_TRAPS: dict[str, dict] = {
    "concalesco": {
        "expected_senses": ["grow warm", "become hot", "grow fervent"],
        "known_wrong_renderings": ["grow cold", "grew cold"],
        "note": (
            "concaluit cor meum = 'my heart grew hot/burned', not 'grew "
            "cold'. Multiple models have produced the wrong-polarity "
            "reading here."
        ),
    },
    "electrum": {
        "expected_senses": ["amber", "a pale gold-silver alloy"],
        "known_wrong_renderings": ["lightning", "electricity"],
        "note": "Ancient material term; do not modernize without evidence.",
    },
    # extend as new traps are found in review
}


# ============================================================================
# TOKENIZATION
# ============================================================================

_WORD_RE = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ]+")


def tokenize_with_offsets(text: str) -> list[tuple[str, int]]:
    """Return (token, char_offset) pairs for a Latin chunk."""
    return [(m.group(0), m.start()) for m in _WORD_RE.finditer(text)]


# ============================================================================
# CORE ANALYSIS
# ============================================================================


def senses_diverge(senses: list[Sense]) -> bool:
    """
    True if the senses represent genuinely different meanings, not just
    inflectional variants of the same lemma (e.g. plaga = blow/wound vs.
    region/quarter vs. plague IS divergent; noun case variants of the same
    lemma/gloss are NOT).
    """
    distinct_glosses = {s.gloss.strip().lower() for s in senses}
    distinct_lemmas = {s.lemma.strip().lower() for s in senses}
    # Multiple distinct lemmas is the strong signal. Multiple glosses under
    # a single lemma is weaker evidence and worth a lighter-weight flag —
    # tune this threshold once you see real output.
    return len(distinct_lemmas) > 1


def analyze_chunk(
    latin_text: str,
    backend: LexiconBackend,
    *,
    structural_stoplist: set[str] = COMMON_STRUCTURAL_STOPLIST,
    proper_nouns: set[str] = KNOWN_PROPER_NOUNS,
    known_traps: dict[str, dict] = KNOWN_TRAPS,
) -> list[LexicalFlag]:
    """
    Analyze one chunk of Latin text and return only the flags worth
    surfacing — this is the compact evidence layer, not a full gloss.
    """
    flags: list[LexicalFlag] = []
    seen_tokens: set[str] = set()  # avoid duplicate flags for repeated words

    for token, offset in tokenize_with_offsets(latin_text):
        lower = token.lower()

        if lower in structural_stoplist:
            continue

        if token in proper_nouns:
            continue

        if token in seen_tokens:
            continue

        analysis = backend.analyze_word(lower)

        # Known trap override — always flag regardless of lexicon result.
        for lemma, trap in known_traps.items():
            if lower.startswith(lemma[:6]):  # crude; refine once tested
                flags.append(
                    LexicalFlag(
                        token=token,
                        offset=offset,
                        flag_type="known_trap",
                        senses=trap["expected_senses"],
                        note=trap["note"],
                    )
                )
                seen_tokens.add(token)
                break
        else:
            if not analysis.found:
                # Capitalized-and-not-found already filtered by proper_nouns
                # check above where known in advance; anything else here is
                # either a genuinely rare/technical term or a parser issue —
                # worth a light flag, not a loud one.
                flags.append(
                    LexicalFlag(
                        token=token,
                        offset=offset,
                        flag_type="not_found",
                        senses=[],
                        note="Not resolved by lexicon backend — may be "
                        "ecclesiastical/patristic vocabulary outside a "
                        "classical-era dictionary, a proper name not yet "
                        "in KNOWN_PROPER_NOUNS, or a parser artifact.",
                    )
                )
            elif senses_diverge(analysis.senses):
                flags.append(
                    LexicalFlag(
                        token=token,
                        offset=offset,
                        flag_type="ambiguous_senses",
                        senses=[f"{s.lemma}: {s.gloss}" for s in analysis.senses],
                        note="Multiple lexically distinct senses — do not "
                        "let a fluent English rendering silently collapse "
                        "this without checking the Latin context.",
                    )
                )

            seen_tokens.add(token)

    return flags


def flags_to_json(flags: list[LexicalFlag]) -> list[dict]:
    """Serializable form for storage in the chunk cache / JSONL output."""
    return [
        {
            "token": f.token,
            "offset": f.offset,
            "flag_type": f.flag_type,
            "senses": f.senses,
            "note": f.note,
        }
        for f in flags
    ]


# ============================================================================
# CACHE INTEGRATION
#
# Call this once when building book1-chunks.pkl (see handoff section 20/37).
# Store results directly on each chunk dict under "lexical_evidence" so
# translation runs pay zero additional glossary cost afterward.
# ============================================================================


def add_glossary_data(
    chunks: list[dict],
    backend: LexiconBackend,
) -> list[dict]:
    for chunk in chunks:
        latin_text = chunk["latin"]["text"]
        flags = analyze_chunk(latin_text, backend)
        chunk["lexical_evidence"] = flags_to_json(flags)
    return chunks


# ============================================================================
# QUICK MANUAL TEST (no backend required — exercises tokenizer/stoplist only)
# ============================================================================

if __name__ == "__main__":
    sample = "concaluit cor meum et quatuor plagas mundi vidi"
    for token, offset in tokenize_with_offsets(sample):
        marker = "SKIP" if token.lower() in COMMON_STRUCTURAL_STOPLIST else "CHECK"
        print(f"{offset:>3}  {marker:<6} {token}")
