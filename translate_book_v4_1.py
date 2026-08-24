from __future__ import annotations

import argparse
import json
import os
import re
import time
import urllib.error
import urllib.request
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

# ============================================================================
# CONFIG
# ============================================================================

INPUT_FILE = Path(r"C:\Users\FabioRosado\book1.txt")

# Deliberately new filenames so the old benchmark JSONL is not mixed with this
# new pipeline.
PIPELINE_VERSION = "v4.1"
QWEN_DRAFT_FILE = Path(r"C:\Users\FabioRosado\book1-qwen35-v4.1.jsonl")
MISTRAL_DRAFT_FILE = Path(r"C:\Users\FabioRosado\book1-mistral-v4.1.jsonl")
REVIEW_FILE = Path(r"C:\Users\FabioRosado\book1-reviewed-v4.1.jsonl")
PROSECUTOR_FILE = Path(r"C:\Users\FabioRosado\book1-prosecutor-v4.1.jsonl")

QWEN_DRAFT_MODEL = "qwen3.5:9b"
MISTRAL_DRAFT_MODEL = "mistral-small3.2:24b"
QWEN_REVIEW_MODEL = "qwen38-27b-q4ks"
PROSECUTOR_MODEL = "nvidia/nemotron-3-ultra-550b-a55b:free"
LOCAL_PROSECUTOR_FALLBACK_MODEL = "gemma3:27b"

OLLAMA_URL = "http://127.0.0.1:11434/api/chat"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

BOOK_NUMBER = 1

# Source-aware chunks. Leading Corpus/edition unit markers are preserved as
# stable source units and grouped into processing chunks. Character limits are
# only safety caps, not the primary segmentation rule.
TARGET_SOURCE_UNITS = 4
MIN_SOURCE_UNITS = 3
MAX_CHARS = 6500
CONTEXT_MAX_CHARS = 1800

QWEN_DRAFT_CONTEXT = 8192
MISTRAL_DRAFT_CONTEXT = 16384
QWEN_REVIEW_CONTEXT = 16384
PROSECUTOR_CONTEXT = 32768

QWEN_DRAFT_MAX_OUTPUT = 1500
MISTRAL_DRAFT_MAX_OUTPUT = 1800
QWEN_REVIEW_MAX_OUTPUT = 3600
PROSECUTOR_MAX_OUTPUT = 3200

SOURCE_METADATA = {
    "author": "Hieronymus Stridonensis",
    "work": "Commentaria in Ezechielem",
    "corpus": "Patrologia Latina (Corpus 2)",
    "cc_idno": 21347,
    "cc_id": "cps_2.HieStr.CoInEz",
    "permalink": "https://mlat.uzh.ch/browser/cps_2.HieStr.CoInEz",
}


# ============================================================================
# PROMPTS
# ============================================================================

WITNESS_PROMPT = """\
Translate the following Latin passage from St Jerome into accurate English.

Priorities:
- Preserve every clause and meaningful distinction.
- Stay relatively close to the Latin syntax where readable.
- Do not add historical or theological explanations.
- Do not silently omit difficult wording.
- Preserve technical, biblical, Hebrew, Greek, and textual-critical terminology.
- Do not modernize an unfamiliar ancient term simply because it resembles a
  modern English word.
- Preserve names carefully.
- Preserve meaningful distinctions in Jerome's wording.
- If a word, phrase, name, textual variant, chronology, or construction is
  genuinely uncertain, mark it:
  [UNCERTAIN: brief explanation]
- Do not reconstruct quotations from memory if the supplied Latin differs.
- Do not smooth away a difficult phrase merely to make the English elegant.
- Return only the translation and uncertainty markers.

LATIN:

{latin}
"""


QWEN_REVIEW_PROMPT = """\
You are the adjudicating reviewer for a machine-assisted English edition of
St Jerome's Commentary on Ezekiel.

The LATIN is the authoritative source.

You are given:
1. The original Latin.
2. An independent Qwen 3.5 translation witness.
3. An independent Mistral Small 3.2 translation witness.
4. Editorial/source annotations extracted from the source edition.
5. An adversarial prosecutor report.

The prosecutor is NOT an authority. Its claims are allegations to test.
Any claim that depends on Scripture, Jerome usage elsewhere, lexicons,
chronology, names, or external history remains unverified unless the supplied
evidence actually establishes it. In v4.1, prosecutor evidence_requests have
not yet been resolved by the future research service, so unresolved external
requests should normally become targeted human_check items rather than facts.

Your task is NOT to vote between the witnesses. Agreement is supporting
evidence, not proof. Disagreement is a signal to inspect the Latin carefully.

Check the Latin CLAUSE BY CLAUSE and produce the best accurate, readable
English draft. Assume both witnesses may be wrong.

CRITICAL REVIEW RULES

- Preserve every meaningful Latin clause in final_draft.
- Perform an explicit coverage check independently of both witnesses.
- Do not add information not present in the Latin.
- Do not silently omit difficult material.
- Translate idioms naturally while preserving their meaning.
- Preserve Jerome's distinctions between words and concepts.
- Be particularly cautious with Hebrew, Greek, Latin, etymology, translation
  choices, textual variants, Scripture wording, theological terminology,
  proper names, numbers, chronology, and rare or technical terms.
- Do not modernize an unfamiliar ancient technical term merely because a
  modern English word looks similar.
- Treat polished English as potentially wrong.
- If one witness omits a Latin clause, restore it from the Latin and record the
  omission under coverage.omissions_corrected.
- If a witness appears to add material unsupported by the Latin, do not retain
  it merely because it sounds plausible.
- When witnesses disagree, resolve the reading from the Latin. If the Latin
  remains genuinely risky or requires an external authority, create a
  human_check finding.
- Do not identify Scripture quotations, historical facts, chronology, names,
  or external references from memory when SOURCE ANNOTATIONS provide relevant
  metadata.
- When a source annotation gives a reference, use that supplied reference as
  metadata; do not replace it with a remembered reference.
- If external verification is genuinely required and source annotations do not
  settle it, flag a human_check rather than inventing an answer.

DISTINGUISH TWO KINDS OF FINDINGS

1. "corrected"
   A witness contains a substantive error but the Latin makes the correction
   sufficiently clear. Correct it in final_draft and record it for the audit
   trail.

2. "human_check"
   A competent human editor would genuinely benefit from checking a lexicon,
   Scripture, Hebrew/Greek, source edition, chronology, proper name, or another
   external source before publication.

Do not manufacture human_check findings merely to appear cautious.

Allowed finding types:
- lexical
- syntax
- textual
- scripture
- hebrew_greek
- theological
- proper_name
- chronology
- model_disagreement
- possible_omission
- possible_addition
- source_text

Severity:
- low: worth recording, but unlikely to alter the basic meaning
- medium: meaningful issue; human checking is useful if status=human_check
- high: meaning may materially change or the translation is unsafe to approve

IMPORTANT:
- "english" must contain wording actually used in final_draft.
- "draft_problem" should quote or briefly describe the problematic witness
  wording when status=corrected.
- "latin" must be an exact short substring copied from LATIN whenever possible.
- Do not invent character offsets. Software calculates offsets.
- A high-severity corrected error does not by itself require needs_review.
- review_status="needs_review" only when at least one human_check finding has
  medium or high severity, or when final coverage remains unresolved.
- risk_score measures REMAINING HUMAN REVIEW RISK after your corrections.
- coverage.all_clauses_accounted_for refers to FINAL_DRAFT, not the witnesses.

Return VALID JSON ONLY with exactly this structure:

{{
  "final_draft": "complete reviewed English translation",
  "review_status": "low_risk | needs_review",
  "risk_score": 0,
  "summary": "one short sentence describing remaining review risk",
  "coverage": {{
    "all_clauses_accounted_for": true,
    "omissions_corrected": [
      {{
        "latin": "exact Latin clause omitted by a witness",
        "missing_from": ["qwen35", "mistral"],
        "final_wording": "wording restored in final_draft"
      }}
    ]
  }},
  "findings": [
    {{
      "latin": "exact Latin word or short phrase",
      "english": "wording actually used in final_draft",
      "type": "lexical",
      "severity": "medium",
      "status": "corrected | human_check",
      "draft_problem": "bad witness wording or null",
      "reason": "why this was corrected or why a human should check it",
      "suggested_check": "what to consult, or null if no human check is needed"
    }}
  ]
}}

risk_score must be an integer from 0 to 10.
If there are no meaningful findings, return an empty findings array.
If neither witness omitted a clause, return an empty omissions_corrected array.
Do not include commentary outside the JSON.

LATIN:
<<<
{latin}

SOURCE ANNOTATIONS:
<<<
{annotations}

QWEN 3.5 WITNESS:
<<<
{qwen35}

MISTRAL SMALL 3.2 WITNESS:
<<<
{mistral}

PROSECUTOR REPORT:
<<<
{prosecutor}
"""


PROSECUTOR_PROMPT = """\
You are the adversarial prosecutor for a machine-assisted English edition of
St Jerome's Commentary on Ezekiel.

Your job is NOT to translate the passage again and NOT to manufacture
disagreement. Your job is to try to find grounded reasons why the proposed
translations may be wrong, incomplete, overconfident, or dependent on evidence
that has not yet been verified.

The LATIN is authoritative. Both witnesses may agree and both may still be
wrong.

IMPORTANT EVIDENCE RULE:
- Do not make claims such as "Jerome normally uses X this way", "this quotation
  is Psalm Y", "the Vulgate says Z", or "the historical event was Q" from model
  memory and present them as established facts.
- If such a claim would matter, request evidence instead.
- Unsupported external-memory claims are allegations, not evidence.
- Prefer a precise evidence request over a confident guess.
- Do not reward yourself for finding problems. "no_issue_found" is a valid
  result.
- "insufficient_basis_to_challenge" is also valid and is not equivalent to
  proving the translation correct.

Inspect especially:
- omitted or added meaning
- subject/object or clause-attachment mistakes
- negation, number, chronology, and proper-name mistakes
- wrong lexical sense
- morphology-sensitive ambiguities
- idioms translated literally
- Scripture quotation/allusion claims
- Hebrew/Greek claims
- textual-apparatus handling
- places where polished English hides an unresolved ambiguity
- internal contradictions between a proposed translation and the visible Latin

For every challenge, quote a short exact Latin substring whenever possible.

Return VALID JSON ONLY with exactly this structure:

{{
  "status": "no_issue_found | insufficient_basis_to_challenge | requires_evidence | grounded_challenge | unresolved",
  "summary": "one short sentence",
  "challenges": [
    {{
      "latin": "exact short Latin substring",
      "type": "lexical | syntax | omission | addition | idiom | scripture | hebrew_greek | textual | proper_name | chronology | morphology | source_text | other",
      "severity": "low | medium | high",
      "witness_target": "qwen35 | mistral | both | final_question",
      "claim": "precise description of what may be wrong",
      "basis_visible_in_prompt": "what in the supplied Latin/witnesses/annotations supports raising the concern",
      "requires_external_evidence": true
    }}
  ],
  "evidence_requests": [
    {{
      "kind": "jerome_phrase | jerome_lemma | scripture | glossary | morphology | source_edition | chronology | proper_name | web_research",
      "query": "specific thing to retrieve",
      "reason": "why this evidence would resolve or test the challenge"
    }}
  ]
}}

Rules:
- If a challenge requires external evidence, include a matching evidence_request.
- Do not fabricate evidence results.
- Do not invent character offsets.
- Empty challenges/evidence_requests arrays are valid.
- Do not include commentary outside the JSON.

LATIN:
<<<
{latin}

READ-ONLY CONTEXT BEFORE:
<<<
{context_before}

READ-ONLY CONTEXT AFTER:
<<<
{context_after}

SOURCE ANNOTATIONS:
<<<
{annotations}

QWEN 3.5 WITNESS:
<<<
{qwen35}

MISTRAL SMALL 3.2 WITNESS:
<<<
{mistral}

PROSECUTOR REPORT:
<<<
{prosecutor}
"""


# ============================================================================
# SOURCE PARSING
# ============================================================================

PAGE_RE = re.compile(
    r"-*\[page\s+([0-9]+[A-D])\]-*",
    flags=re.IGNORECASE,
)

INLINE_NOTE_RE = re.compile(r"\[(\d+)\]")

FOOTNOTE_SEPARATOR_RE = re.compile(r"^\s*_{10,}\s*$")

FOOTNOTE_DEFINITION_RE = re.compile(r"^\s*(\d+)\s*:\s*(.+?)\s*$")

# IMPORTANT:
# These are edition pagination numbers only when they occur at the BEGINNING
# of a source line, e.g.
#
#     1-2 Finitis in Isaiam...
#     3-4 Postquam vero...
#
# or on a line by themselves.
#
# We DO NOT remove arbitrary Arabic numbers from within prose. That was the
# previous bug which damaged references such as "(Naum I, 3)".
LEADING_EDITION_PAGINATION_RE = re.compile(
    r"^\s*(\d+(?:-\d+)?)" r"(?=\s+(?:[A-ZÀ-ÖØ-Þ]|[\(\[]|\Z))" r"\s*"
)

STANDALONE_EDITION_PAGINATION_RE = re.compile(r"^\s*(\d+(?:-\d+)?)\s*$")

# Corpus Corporum also sometimes inserts edition pagination ranges such as
# "3-4" in the middle of a wrapped prose line:
#
#     aliorumque 3-4 malis me crucio
#
# A range token outside parentheses/brackets is treated as edition pagination.
# We deliberately do NOT remove single Arabic numbers inline because those may
# be real verse/chapter numbers such as "(Naum I, 3)".
INLINE_EDITION_RANGE_RE = re.compile(r"(?<![\w])(\d+-\d+)(?![\w])")


def strip_download_header(source_text: str) -> str:
    match = re.search(
        r"^\s*LIBER\s+PRIMUS\.?\s*$",
        source_text,
        flags=re.IGNORECASE | re.MULTILINE,
    )

    if not match:
        raise ValueError("Could not find 'LIBER PRIMUS' in the source file.")

    # Keep everything after the heading itself.
    return source_text[match.end() :]


def collect_footnote_definitions(
    source_text: str,
) -> dict[str, deque[str]]:
    """
    Collect editorial note definitions such as:

        ______________________
        1: (Psal. XXXVIII, 4)
        2: (Eccli. XXII, 6)

    Markers are reused throughout PL, so each marker has a queue.
    """
    definitions: dict[str, deque[str]] = defaultdict(deque)

    lines = source_text.splitlines()
    in_footnotes = False

    for line in lines:
        if FOOTNOTE_SEPARATOR_RE.match(line):
            in_footnotes = True
            continue

        if not in_footnotes:
            continue

        match = FOOTNOTE_DEFINITION_RE.match(line)

        if match:
            marker, reference = match.groups()
            definitions[marker].append(reference.strip())
            continue

        if not line.strip():
            continue

        # First non-definition prose line after a note block.
        in_footnotes = False

    return definitions


def remove_footnote_blocks(source_text: str) -> list[str]:
    """
    Return source prose lines while removing the editorial note-definition
    blocks themselves.
    """
    output: list[str] = []

    in_footnotes = False

    for line in source_text.splitlines():
        if FOOTNOTE_SEPARATOR_RE.match(line):
            in_footnotes = True
            continue

        if in_footnotes:
            if FOOTNOTE_DEFINITION_RE.match(line):
                continue

            if not line.strip():
                continue

            in_footnotes = False

        output.append(line)

    return output


def add_text(
    pieces: list[str],
    text: str,
    current_length: int,
) -> tuple[int, int]:
    """
    Append prose with a safe space boundary.

    Returns:
        (start_offset, new_total_length)
    """
    text = text.strip()

    if not text:
        return current_length, current_length

    if pieces:
        previous = pieces[-1]

        if (
            previous
            and not previous.endswith((" ", "\n"))
            and not text.startswith((".", ",", ";", ":", "!", "?", ")", "]"))
        ):
            pieces.append(" ")
            current_length += 1

    start = current_length
    pieces.append(text)
    current_length += len(text)

    return start, current_length


def strip_inline_edition_ranges(
    line: str,
    *,
    current_length: int,
) -> tuple[str, list[dict[str, Any]]]:
    """
    Remove Corpus/edition pagination ranges such as "3-4" when they occur
    outside parentheses or square brackets.

    This avoids the earlier bug where generic number stripping damaged real
    references like "(Naum I, 3)".
    """
    annotations: list[dict[str, Any]] = []
    output: list[str] = []

    paren_depth = 0
    bracket_depth = 0
    cursor = 0

    for match in INLINE_EDITION_RANGE_RE.finditer(line):
        prefix = line[cursor : match.start()]

        # Update nesting state from text before this numeric range.
        for char in prefix:
            if char == "(":
                paren_depth += 1
            elif char == ")" and paren_depth:
                paren_depth -= 1
            elif char == "[":
                bracket_depth += 1
            elif char == "]" and bracket_depth:
                bracket_depth -= 1

        output.append(prefix)

        if paren_depth == 0 and bracket_depth == 0:
            # Approximate clean-text offset before add_text() normalizes spaces.
            cleaned_prefix = "".join(output)
            annotations.append(
                {
                    "type": "edition_pagination",
                    "value": match.group(1),
                    "offset": current_length + len(cleaned_prefix.rstrip()),
                }
            )

            # Replace marker with one space so adjacent prose words remain
            # separated. Final whitespace is normalized below.
            output.append(" ")
        else:
            output.append(match.group(0))

        cursor = match.end()

    output.append(line[cursor:])
    cleaned = re.sub(r"\s+", " ", "".join(output)).strip()

    return cleaned, annotations


def parse_source(source_text: str) -> dict[str, Any]:
    source_text = strip_download_header(source_text)

    footnotes = collect_footnote_definitions(source_text)
    lines = remove_footnote_blocks(source_text)

    pieces: list[str] = []
    annotations: list[dict[str, Any]] = []
    page_markers: list[dict[str, Any]] = []
    source_unit_starts: list[dict[str, Any]] = []

    current_length = 0
    pending_source_unit_id: str | None = None

    def mark_source_unit(unit_id: str):
        # Multiple pagination markers can occur before prose at the same clean
        # offset. Keep the latest marker as the unit label but avoid duplicate
        # empty boundaries.
        nonlocal pending_source_unit_id
        pending_source_unit_id = unit_id

    def materialize_pending_unit():
        nonlocal pending_source_unit_id
        if pending_source_unit_id is None:
            return
        if source_unit_starts and source_unit_starts[-1]["start_offset"] == current_length:
            source_unit_starts[-1]["source_unit_id"] = pending_source_unit_id
        else:
            source_unit_starts.append(
                {
                    "source_unit_id": pending_source_unit_id,
                    "start_offset": current_length,
                }
            )
        pending_source_unit_id = None

    for raw_line in lines:
        line = raw_line.strip()

        if not line:
            continue

        # ------------------------------------------------------------
        # PL page markers
        # ------------------------------------------------------------
        page_matches = list(PAGE_RE.finditer(line))

        if page_matches:
            for match in page_matches:
                page_markers.append(
                    {
                        "offset": current_length,
                        "page": match.group(1).upper(),
                    }
                )

            line = PAGE_RE.sub(" ", line).strip()

            if not line:
                continue

        # ------------------------------------------------------------
        # Edition-pagination marker at LINE START ONLY
        # ------------------------------------------------------------
        standalone = STANDALONE_EDITION_PAGINATION_RE.match(line)

        if standalone:
            annotations.append(
                {
                    "type": "edition_pagination",
                    "value": standalone.group(1),
                    "offset": current_length,
                }
            )
            mark_source_unit(standalone.group(1))
            continue

        leading = LEADING_EDITION_PAGINATION_RE.match(line)

        if leading:
            annotations.append(
                {
                    "type": "edition_pagination",
                    "value": leading.group(1),
                    "offset": current_length,
                }
            )
            mark_source_unit(leading.group(1))
            line = line[leading.end() :].strip()

        if not line:
            continue

        # ------------------------------------------------------------
        # Inline edition-pagination ranges, e.g. "aliorumque 3-4 malis"
        # ------------------------------------------------------------
        line, inline_pagination = strip_inline_edition_ranges(
            line,
            current_length=current_length,
        )
        annotations.extend(inline_pagination)

        if not line:
            continue

        # A leading/standalone edition marker becomes a stable source-unit
        # boundary at the first following prose character.
        materialize_pending_unit()

        # ------------------------------------------------------------
        # Inline editorial footnote markers
        # ------------------------------------------------------------
        cursor = 0

        for match in INLINE_NOTE_RE.finditer(line):
            before = line[cursor : match.start()]

            _, current_length = add_text(
                pieces,
                before,
                current_length,
            )

            marker = match.group(1)

            reference = None
            if footnotes.get(marker):
                reference = footnotes[marker].popleft()

            context_before = "".join(pieces)[-80:]

            annotations.append(
                {
                    "type": "editorial_reference",
                    "marker": marker,
                    "reference": reference,
                    "offset": current_length,
                    "context_before": context_before,
                }
            )

            cursor = match.end()

        remainder = line[cursor:]

        _, current_length = add_text(
            pieces,
            remainder,
            current_length,
        )

    clean_text = "".join(pieces).strip()

    # Add convenient context after parsing.
    for annotation in annotations:
        offset = annotation["offset"]

        annotation["context"] = clean_text[
            max(0, offset - 70) : min(len(clean_text), offset + 90)
        ]

        annotation.pop("context_before", None)

    # Ensure there is at least one canonical source unit even if the source
    # begins with unnumbered prose.
    if not source_unit_starts or source_unit_starts[0]["start_offset"] > 0:
        source_unit_starts.insert(
            0,
            {
                "source_unit_id": "preface",
                "start_offset": 0,
            },
        )

    source_units: list[dict[str, Any]] = []
    for index, item in enumerate(source_unit_starts):
        start_offset = item["start_offset"]
        end_offset = (
            source_unit_starts[index + 1]["start_offset"]
            if index + 1 < len(source_unit_starts)
            else len(clean_text)
        )
        if end_offset <= start_offset:
            continue
        unit_text = clean_text[start_offset:end_offset].strip()
        if not unit_text:
            continue
        actual_start = clean_text.find(unit_text, start_offset, end_offset + 1)
        source_units.append(
            {
                "source_unit_id": item["source_unit_id"],
                "start_offset": actual_start,
                "end_offset": actual_start + len(unit_text),
                "text": unit_text,
            }
        )

    return {
        "text": clean_text,
        "annotations": annotations,
        "page_markers": page_markers,
        "source_units": source_units,
    }


# ============================================================================
# CHUNKING
# ============================================================================


def split_sentences(text: str) -> list[tuple[int, int, str]]:
    """
    Sentence-ish splitting.

    We intentionally prefer slightly larger clauses over chopping Latin at
    arbitrary character positions.
    """
    results = []

    start = 0

    for match in re.finditer(r"(?<=[.!?])\s+", text):
        end = match.start()

        sentence = text[start:end].strip()

        if sentence:
            actual_start = text.find(sentence, start, end + 1)
            results.append(
                (
                    actual_start,
                    actual_start + len(sentence),
                    sentence,
                )
            )

        start = match.end()

    tail = text[start:].strip()

    if tail:
        actual_start = text.find(tail, start)
        results.append(
            (
                actual_start,
                actual_start + len(tail),
                tail,
            )
        )

    return results


def page_at_offset(
    markers: list[dict[str, Any]],
    offset: int,
) -> str | None:
    current = None

    for marker in markers:
        if marker["offset"] <= offset:
            current = marker["page"]
        else:
            break

    return current


def make_chunks(parsed: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Build processing chunks from stable source units rather than from a target
    character count.

    Canonical identity lives at the source-unit level. Chunks are processing
    batches and may be regrouped later without losing provenance.
    """
    text = parsed["text"]
    annotations = parsed["annotations"]
    page_markers = parsed["page_markers"]
    source_units = parsed.get("source_units", [])

    if not source_units:
        raise RuntimeError("No source units were produced by the parser.")

    # If a single source unit is abnormally large, split it at sentence
    # boundaries while preserving the canonical parent source_unit_id.
    expanded_units: list[dict[str, Any]] = []
    for unit in source_units:
        if len(unit["text"]) <= MAX_CHARS:
            expanded_units.append({**unit, "part": None})
            continue

        local_sentences = split_sentences(unit["text"])
        current: list[tuple[int, int, str]] = []
        current_chars = 0
        part_number = 1

        def flush_large_unit_part():
            nonlocal current, current_chars, part_number
            if not current:
                return
            local_start = current[0][0]
            local_end = current[-1][1]
            absolute_start = unit["start_offset"] + local_start
            absolute_end = unit["start_offset"] + local_end
            part_text = text[absolute_start:absolute_end].strip()
            expanded_units.append(
                {
                    "source_unit_id": unit["source_unit_id"],
                    "start_offset": absolute_start,
                    "end_offset": absolute_end,
                    "text": part_text,
                    "part": part_number,
                }
            )
            part_number += 1
            current = []
            current_chars = 0

        for sentence in local_sentences:
            sentence_len = len(sentence[2])
            prospective = current_chars + (1 if current else 0) + sentence_len
            if current and prospective > MAX_CHARS:
                flush_large_unit_part()
            current.append(sentence)
            current_chars += (1 if current_chars else 0) + sentence_len
        flush_large_unit_part()

    chunks: list[dict[str, Any]] = []
    current_units: list[dict[str, Any]] = []

    def context_text(unit: dict[str, Any] | None) -> str:
        if unit is None:
            return ""
        value = unit["text"].strip()
        if len(value) <= CONTEXT_MAX_CHARS:
            return value

        # Context is read-only. Truncate at a nearby sentence boundary rather
        # than expanding the target chunk.
        sentences = split_sentences(value)
        if not sentences:
            return value[:CONTEXT_MAX_CHARS]

        collected = []
        chars = 0
        for _, _, sentence in sentences:
            if collected and chars + 1 + len(sentence) > CONTEXT_MAX_CHARS:
                break
            collected.append(sentence)
            chars += (1 if chars else 0) + len(sentence)
        return " ".join(collected)

    def flush():
        nonlocal current_units
        if not current_units:
            return

        start_offset = current_units[0]["start_offset"]
        end_offset = current_units[-1]["end_offset"]
        chunk_text = text[start_offset:end_offset].strip()

        chunk_annotations = []
        for item in annotations:
            if start_offset <= item["offset"] <= end_offset:
                copied = dict(item)
                copied["offset"] = item["offset"] - start_offset
                chunk_annotations.append(copied)

        first_index = expanded_units.index(current_units[0])
        last_index = expanded_units.index(current_units[-1])
        previous_unit = expanded_units[first_index - 1] if first_index > 0 else None
        next_unit = (
            expanded_units[last_index + 1]
            if last_index + 1 < len(expanded_units)
            else None
        )

        source_unit_ids = []
        seen = set()
        for unit in current_units:
            unit_id = unit["source_unit_id"]
            if unit_id not in seen:
                seen.add(unit_id)
                source_unit_ids.append(unit_id)

        chunks.append(
            {
                "id": f"book{BOOK_NUMBER:02d}-{len(chunks)+1:04d}",
                "book": BOOK_NUMBER,
                "source": {
                    **SOURCE_METADATA,
                    "pl_start": page_at_offset(page_markers, start_offset),
                    "pl_end": page_at_offset(
                        page_markers,
                        max(start_offset, end_offset - 1),
                    ),
                    "source_unit_ids": source_unit_ids,
                },
                "latin": {
                    "text": chunk_text,
                    "start_offset": start_offset,
                    "end_offset": end_offset,
                    "context_before": context_text(previous_unit),
                    "context_after": context_text(next_unit),
                },
                "source_units": [
                    {
                        "source_unit_id": unit["source_unit_id"],
                        "part": unit.get("part"),
                        "start_offset": unit["start_offset"],
                        "end_offset": unit["end_offset"],
                    }
                    for unit in current_units
                ],
                "annotations": chunk_annotations,
            }
        )
        current_units = []

    for unit in expanded_units:
        if not current_units:
            current_units.append(unit)
            continue

        prospective_start = current_units[0]["start_offset"]
        prospective_end = unit["end_offset"]
        prospective_chars = prospective_end - prospective_start

        # Character limit is a safety cap only.
        if prospective_chars > MAX_CHARS and len(current_units) >= MIN_SOURCE_UNITS:
            flush()
            current_units.append(unit)
            continue

        current_units.append(unit)

        if len(current_units) >= TARGET_SOURCE_UNITS:
            flush()

    flush()
    return chunks


# ============================================================================
# JSONL HELPERS
# ============================================================================


def load_jsonl_by_id(path: Path) -> dict[str, dict[str, Any]]:
    records = {}

    if not path.exists():
        return records

    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.strip()

            if not line:
                continue

            try:
                record = json.loads(line)
                records[record["id"]] = record
            except Exception as exc:
                print(
                    f"WARNING: Could not parse {path.name} "
                    f"line {line_number}: {exc}"
                )

    return records


def append_jsonl(path: Path, record: dict[str, Any]):
    with path.open("a", encoding="utf-8") as handle:
        json.dump(
            record,
            handle,
            ensure_ascii=False,
        )
        handle.write("\n")
        handle.flush()


# ============================================================================
# OLLAMA
# ============================================================================


def ollama_chat(
    model: str,
    prompt: str,
    *,
    context: int,
    json_mode: bool = False,
    num_predict: int = 1600,
) -> tuple[str, float]:
    payload: dict[str, Any] = {
        "model": model,
        "stream": False,
        "think": False,
        "messages": [
            {
                "role": "user",
                "content": prompt,
            }
        ],
        "options": {
            "temperature": 0.1,
            "num_ctx": context,
            "num_predict": num_predict,
        },
    }

    if json_mode:
        payload["format"] = "json"

    request = urllib.request.Request(
        OLLAMA_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    started = time.perf_counter()

    try:
        with urllib.request.urlopen(
            request,
            timeout=1800,
        ) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Could not contact Ollama: {exc}") from exc

    elapsed = time.perf_counter() - started

    content = result["message"]["content"].strip()

    return content, elapsed


def openrouter_chat(
    model: str,
    prompt: str,
    *,
    json_mode: bool = False,
    max_tokens: int = 3200,
) -> tuple[str, float]:
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError(
            "OPENROUTER_API_KEY is not set. "
            "Set it before running the Nemotron prosecutor."
        )

    payload: dict[str, Any] = {
        "model": model,
        "stream": False,
        "temperature": 0.01,
        "max_tokens": max_tokens,
        "messages": [
            {
                "role": "user",
                "content": prompt,
            }
        ],
    }

    request = urllib.request.Request(
        OPENROUTER_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )

    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=1800) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"OpenRouter HTTP {exc.code}: {body[:1000]}"
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Could not contact OpenRouter: {exc}") from exc

    elapsed = time.perf_counter() - started

    if "choices" not in result:
        raise RuntimeError(
            "OpenRouter response did not contain choices: "
            + json.dumps(result, ensure_ascii=False)[:1200]
        )

    content = result["choices"][0]["message"]["content"].strip()
    return content, elapsed


def parse_json_response(text: str) -> dict[str, Any]:
    text = text.strip()

    # Be defensive even though Ollama JSON mode should normally handle this.
    if text.startswith("```"):
        text = re.sub(
            r"^```(?:json)?\s*",
            "",
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(r"\s*```$", "", text)

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")

        if start >= 0 and end > start:
            return json.loads(text[start : end + 1])

        raise


# ============================================================================
# PASS 1 — INDEPENDENT TRANSLATION WITNESSES
# ============================================================================


def source_fingerprint(chunk: dict[str, Any]) -> str:
    import hashlib

    return hashlib.sha256(chunk["latin"]["text"].encode("utf-8")).hexdigest()


def run_witness_pass(
    chunks: list[dict[str, Any]],
    *,
    model: str,
    output_file: Path,
    label: str,
    context: int,
    num_predict: int,
    limit: int | None = None,
):
    completed = load_jsonl_by_id(output_file)
    selected = chunks[:limit] if limit else chunks
    pending = [c for c in selected if c["id"] not in completed]

    print("\n" + "=" * 72)
    print(f"WITNESS PASS — {label}")
    print("=" * 72)
    print(f"Model:            {model}")
    print(f"Context:          {context}")
    print(f"Already complete: {len(selected) - len(pending)}")
    print(f"Remaining:        {len(pending)}")

    if not pending:
        print(f"{label} witness pass already complete.")
        return

    for index, chunk in enumerate(selected, start=1):
        if chunk["id"] in completed:
            continue

        latin = chunk["latin"]["text"]

        print("\n" + "=" * 72)
        print(f"[{index}/{len(selected)}] {chunk['id']}")
        print("PL: " f"{chunk['source']['pl_start']} → " f"{chunk['source']['pl_end']}")
        print(f"Latin chars: {len(latin):,}")
        print(f"Annotations: {len(chunk['annotations'])}")
        print(f"  {label}...", end="", flush=True)

        try:
            prompt = WITNESS_PROMPT.format(latin=latin)

            translation, seconds = ollama_chat(
                model,
                prompt,
                context=context,
                num_predict=num_predict,
            )

            result = {
                "pipeline_version": PIPELINE_VERSION,
                "id": chunk["id"],
                "book": chunk["book"],
                "source": chunk["source"],
                "latin": chunk["latin"],
                "annotations": chunk["annotations"],
                "source_fingerprint": source_fingerprint(chunk),
                "witness": {
                    "model": model,
                    "translation": translation,
                    "seconds": round(seconds, 2),
                    "context": context,
                    "error": None,
                },
            }

            print(f" {seconds:.2f}s")
            append_jsonl(output_file, result)
            print("  SAVED")

        except Exception as exc:
            print(f" ERROR: {exc}")
            print("  NOT SAVED — rerunning the script " "will retry this chunk.")


def run_qwen_draft_pass(chunks, *, limit=None):
    run_witness_pass(
        chunks,
        model=QWEN_DRAFT_MODEL,
        output_file=QWEN_DRAFT_FILE,
        label="Qwen 3.5 9B",
        context=QWEN_DRAFT_CONTEXT,
        num_predict=QWEN_DRAFT_MAX_OUTPUT,
        limit=limit,
    )


def run_mistral_draft_pass(chunks, *, limit=None):
    run_witness_pass(
        chunks,
        model=MISTRAL_DRAFT_MODEL,
        output_file=MISTRAL_DRAFT_FILE,
        label="Mistral Small 3.2 24B",
        context=MISTRAL_DRAFT_CONTEXT,
        num_predict=MISTRAL_DRAFT_MAX_OUTPUT,
        limit=limit,
    )


def format_source_annotations(annotations):
    useful = []

    for annotation in annotations:
        if annotation.get("type") != "editorial_reference":
            continue

        useful.append(
            {
                "marker": annotation.get("marker"),
                "reference": annotation.get("reference"),
                "offset": annotation.get("offset"),
                "context": annotation.get("context"),
            }
        )

    if not useful:
        return "[No editorial/source annotations for this chunk.]"

    return json.dumps(useful, ensure_ascii=False, indent=2)


# ============================================================================
# PASS 2 — ADVERSARIAL PROSECUTOR (NEMOTRON ULTRA BY DEFAULT)
# ============================================================================


def validate_prosecutor(result: dict[str, Any]):
    required = {"status", "summary", "challenges", "evidence_requests"}
    missing = required - set(result)
    if missing:
        raise ValueError(f"Prosecutor JSON missing keys: {sorted(missing)}")

    allowed_statuses = {
        "no_issue_found",
        "insufficient_basis_to_challenge",
        "requires_evidence",
        "grounded_challenge",
        "unresolved",
    }
    if result["status"] not in allowed_statuses:
        raise ValueError(f"Invalid prosecutor status: {result['status']!r}")

    if not isinstance(result["challenges"], list):
        raise ValueError("prosecutor.challenges must be a list")
    if not isinstance(result["evidence_requests"], list):
        raise ValueError("prosecutor.evidence_requests must be a list")


def run_prosecutor_pass(
    chunks: list[dict[str, Any]],
    *,
    limit: int | None = None,
    provider: str = "openrouter",
):
    qwen_records = load_jsonl_by_id(QWEN_DRAFT_FILE)
    mistral_records = load_jsonl_by_id(MISTRAL_DRAFT_FILE)
    completed = load_jsonl_by_id(PROSECUTOR_FILE)
    selected = chunks[:limit] if limit else chunks

    if not qwen_records or not mistral_records:
        raise RuntimeError(
            "The prosecutor requires both witness passes. "
            "Run --phase draft first."
        )

    print("\n" + "=" * 72)
    print("PASS 2 — ADVERSARIAL PROSECUTOR")
    print("=" * 72)
    print(f"Provider:          {provider}")
    print(
        "Model:             "
        + (PROSECUTOR_MODEL if provider == "openrouter" else LOCAL_PROSECUTOR_FALLBACK_MODEL)
    )
    print(f"Already complete: {sum(1 for c in selected if c['id'] in completed)}")

    for index, chunk in enumerate(selected, start=1):
        chunk_id = chunk["id"]
        if chunk_id in completed:
            continue

        qwen_record = qwen_records.get(chunk_id)
        mistral_record = mistral_records.get(chunk_id)
        if qwen_record is None or mistral_record is None:
            raise RuntimeError(f"Missing witness data for {chunk_id}")

        expected_fp = source_fingerprint(chunk)
        if (
            qwen_record.get("source_fingerprint") != expected_fp
            or mistral_record.get("source_fingerprint") != expected_fp
        ):
            raise RuntimeError(f"Stale witness data for {chunk_id}")

        latin = chunk["latin"]["text"]
        prompt = PROSECUTOR_PROMPT.format(
            latin=latin,
            context_before=chunk["latin"].get("context_before") or "[None]",
            context_after=chunk["latin"].get("context_after") or "[None]",
            annotations=format_source_annotations(chunk["annotations"]),
            qwen35=qwen_record["witness"]["translation"],
            mistral=mistral_record["witness"]["translation"],
        )

        print(f"\n[{index}/{len(selected)}] {chunk_id}")
        print("  Prosecutor...", end="", flush=True)

        try:
            if provider == "openrouter":
                raw, seconds = openrouter_chat(
                    PROSECUTOR_MODEL,
                    prompt,
                    json_mode=True,
                    max_tokens=PROSECUTOR_MAX_OUTPUT,
                )
                model = PROSECUTOR_MODEL
            else:
                raw, seconds = ollama_chat(
                    LOCAL_PROSECUTOR_FALLBACK_MODEL,
                    prompt,
                    context=PROSECUTOR_CONTEXT,
                    json_mode=True,
                    num_predict=PROSECUTOR_MAX_OUTPUT,
                )
                model = LOCAL_PROSECUTOR_FALLBACK_MODEL

            parsed_result = parse_json_response(raw)
            validate_prosecutor(parsed_result)

            record = {
                "pipeline_version": PIPELINE_VERSION,
                "id": chunk_id,
                "book": chunk["book"],
                "source": chunk["source"],
                "source_fingerprint": expected_fp,
                "prosecutor": {
                    **parsed_result,
                    "model": model,
                    "provider": provider,
                    "seconds": round(seconds, 2),
                    "error": None,
                },
            }
            append_jsonl(PROSECUTOR_FILE, record)
            print(
                f" {seconds:.2f}s | {parsed_result['status']} | "
                f"challenges={len(parsed_result['challenges'])} | "
                f"evidence_requests={len(parsed_result['evidence_requests'])}"
            )
            print("  SAVED")

        except Exception as exc:
            print(f" ERROR: {exc}")
            print("  NOT SAVED — rerunning will retry this chunk.")


# ============================================================================
# PASS 3 — QWEN 3.8 ADJUDICATION
# ============================================================================


def locate_exact_substring(
    haystack: str,
    needle: str | None,
) -> dict[str, Any]:
    """
    Deterministically locate a model-supplied exact phrase.

    We do this in Python rather than asking the LLM to invent character
    offsets. If the same phrase appears multiple times we expose that fact for
    the future UI instead of pretending the locator is unique.
    """
    if not needle:
        return {
            "start": None,
            "end": None,
            "matches": 0,
            "ambiguous": False,
        }

    starts = [match.start() for match in re.finditer(re.escape(needle), haystack)]

    if not starts:
        return {
            "start": None,
            "end": None,
            "matches": 0,
            "ambiguous": False,
        }

    start = starts[0]

    return {
        "start": start,
        "end": start + len(needle),
        "matches": len(starts),
        "ambiguous": len(starts) > 1,
    }


def enrich_review_offsets(
    review: dict[str, Any],
    *,
    latin: str,
):
    final_draft = review["final_draft"]

    for finding in review["findings"]:
        latin_locator = locate_exact_substring(latin, finding.get("latin"))
        english_locator = locate_exact_substring(
            final_draft,
            finding.get("english"),
        )

        finding["latin_start"] = latin_locator["start"]
        finding["latin_end"] = latin_locator["end"]
        finding["latin_matches"] = latin_locator["matches"]
        finding["latin_locator_ambiguous"] = latin_locator["ambiguous"]

        finding["english_start"] = english_locator["start"]
        finding["english_end"] = english_locator["end"]
        finding["english_matches"] = english_locator["matches"]
        finding["english_locator_ambiguous"] = english_locator["ambiguous"]

    for omission in review["coverage"]["omissions_corrected"]:
        latin_locator = locate_exact_substring(latin, omission.get("latin"))
        english_locator = locate_exact_substring(
            final_draft,
            omission.get("final_wording"),
        )

        omission["latin_start"] = latin_locator["start"]
        omission["latin_end"] = latin_locator["end"]
        omission["latin_matches"] = latin_locator["matches"]
        omission["latin_locator_ambiguous"] = latin_locator["ambiguous"]

        omission["english_start"] = english_locator["start"]
        omission["english_end"] = english_locator["end"]
        omission["english_matches"] = english_locator["matches"]
        omission["english_locator_ambiguous"] = english_locator["ambiguous"]


def validate_review(review: dict[str, Any]):
    required = {
        "final_draft",
        "review_status",
        "risk_score",
        "summary",
        "coverage",
        "findings",
    }

    missing = required - set(review)
    if missing:
        raise ValueError(f"Review JSON missing keys: {sorted(missing)}")

    if review["review_status"] not in {"low_risk", "needs_review"}:
        raise ValueError("review_status must be low_risk or needs_review")

    if not isinstance(review["risk_score"], int):
        raise ValueError("risk_score must be an integer")

    if not 0 <= review["risk_score"] <= 10:
        raise ValueError("risk_score must be between 0 and 10")

    if not isinstance(review["findings"], list):
        raise ValueError("findings must be a list")

    coverage = review["coverage"]

    if not isinstance(coverage, dict):
        raise ValueError("coverage must be an object")

    if not isinstance(coverage.get("all_clauses_accounted_for"), bool):
        raise ValueError("coverage.all_clauses_accounted_for must be boolean")

    omissions = coverage.get("omissions_corrected")
    if not isinstance(omissions, list):
        raise ValueError("coverage.omissions_corrected must be a list")

    allowed_statuses = {"corrected", "human_check"}
    allowed_severities = {"low", "medium", "high"}

    for index, finding in enumerate(review["findings"]):
        if finding.get("status") not in allowed_statuses:
            raise ValueError(
                f"finding {index} has invalid status: " f"{finding.get('status')!r}"
            )
        if finding.get("severity") not in allowed_severities:
            raise ValueError(
                f"finding {index} has invalid severity: " f"{finding.get('severity')!r}"
            )

    human_review_required = any(
        f.get("status") == "human_check" and f.get("severity") in {"medium", "high"}
        for f in review["findings"]
    )

    coverage_unresolved = not coverage["all_clauses_accounted_for"]

    review["review_status"] = (
        "needs_review" if human_review_required or coverage_unresolved else "low_risk"
    )


def run_review_pass(
    chunks: list[dict[str, Any]],
    *,
    limit: int | None = None,
):
    qwen_records = load_jsonl_by_id(QWEN_DRAFT_FILE)
    mistral_records = load_jsonl_by_id(MISTRAL_DRAFT_FILE)
    prosecutor_records = load_jsonl_by_id(PROSECUTOR_FILE)
    reviewed = load_jsonl_by_id(REVIEW_FILE)

    selected = chunks[:limit] if limit else chunks

    if not qwen_records:
        raise RuntimeError(
            "No Qwen 3.5 witness records found. "
            "Run --phase qwen or --phase draft first."
        )

    if not mistral_records:
        raise RuntimeError(
            "No Mistral witness records found. "
            "Run --phase mistral or --phase draft first."
        )

    if not prosecutor_records:
        raise RuntimeError(
            "No prosecutor records found. "
            "Run --phase prosecutor first."
        )

    stale = []
    missing = []

    for chunk in selected:
        chunk_id = chunk["id"]
        expected_fp = source_fingerprint(chunk)
        qwen = qwen_records.get(chunk_id)
        mistral = mistral_records.get(chunk_id)
        prosecutor = prosecutor_records.get(chunk_id)

        if qwen is None or mistral is None or prosecutor is None:
            missing.append(chunk_id)
            continue

        if (
            qwen.get("source_fingerprint") != expected_fp
            or mistral.get("source_fingerprint") != expected_fp
            or prosecutor.get("source_fingerprint") != expected_fp
        ):
            stale.append(chunk_id)

    if stale:
        raise RuntimeError(
            "Witness files are stale relative to the current parser/source. "
            f"First mismatches: {stale[:5]}."
        )

    if missing:
        raise RuntimeError(
            "Some chunks do not yet have both witnesses plus prosecutor output. "
            f"First missing IDs: {missing[:5]}."
        )

    print("\n" + "=" * 72)
    print("PASS 3 — QWEN 3.8 ADJUDICATION")
    print("=" * 72)
    print(f"Chunks available:  {len(selected)}")
    print(f"Already reviewed: " f"{sum(1 for c in selected if c['id'] in reviewed)}")
    print(
        f"Remaining:        " f"{sum(1 for c in selected if c['id'] not in reviewed)}"
    )

    for index, chunk in enumerate(selected, start=1):
        chunk_id = chunk["id"]

        if chunk_id in reviewed:
            continue

        qwen_record = qwen_records[chunk_id]
        mistral_record = mistral_records[chunk_id]
        prosecutor_record = prosecutor_records[chunk_id]

        qwen35 = qwen_record["witness"]["translation"]
        mistral = mistral_record["witness"]["translation"]

        latin = chunk["latin"]["text"]
        annotations = format_source_annotations(chunk["annotations"])

        prompt = QWEN_REVIEW_PROMPT.format(
            latin=latin,
            annotations=annotations,
            qwen35=qwen35,
            mistral=mistral,
            prosecutor=json.dumps(
                prosecutor_record["prosecutor"],
                ensure_ascii=False,
                indent=2,
            ),
        )

        print("\n" + "=" * 72)
        print(f"[{index}/{len(selected)}] {chunk_id}")
        print("PL: " f"{chunk['source']['pl_start']} → " f"{chunk['source']['pl_end']}")
        print(f"Latin chars: {len(latin):,}")
        print("  Qwen 3.8 reviewer...", end="", flush=True)

        started = time.perf_counter()

        try:
            raw, model_seconds = ollama_chat(
                QWEN_REVIEW_MODEL,
                prompt,
                context=QWEN_REVIEW_CONTEXT,
                json_mode=True,
                num_predict=QWEN_REVIEW_MAX_OUTPUT,
            )

            try:
                review = parse_json_response(raw)
                validate_review(review)
                enrich_review_offsets(review, latin=latin)
            except Exception:
                debug_file = Path(
                    rf"C:\Users\FabioRosado\review-debug-v4.1-{chunk_id}.txt"
                )
                debug_file.write_text(raw, encoding="utf-8")
                print("\n  Raw reviewer output saved to: " f"{debug_file}")
                raise

            total_seconds = time.perf_counter() - started

            human_checks = sum(
                1 for f in review["findings"] if f.get("status") == "human_check"
            )
            omissions = review["coverage"]["omissions_corrected"]

            print(f" {model_seconds:.2f}s")
            print(
                "  STATUS: "
                f"{review['review_status']} | "
                f"risk={review['risk_score']}/10 | "
                f"findings={len(review['findings'])} | "
                f"human_checks={human_checks} | "
                f"omissions_fixed={len(omissions)}"
            )

            for omission in omissions:
                missing_from = ",".join(omission.get("missing_from", []))
                print(
                    "    ↺ COVERAGE corrected "
                    f"[{missing_from}]: "
                    f"{omission.get('latin', '')[:60]}"
                )

            for finding in review["findings"]:
                symbol = "⚠" if finding.get("status") == "human_check" else "✓"
                print(
                    f"    {symbol} "
                    f"{finding.get('severity', '?').upper()} "
                    f"{finding.get('status', '?')} "
                    f"{finding.get('type', '?')}: "
                    f"{finding.get('latin', '')[:60]}"
                )

            output = {
                "pipeline_version": PIPELINE_VERSION,
                **chunk,
                "witnesses": {
                    "qwen35": qwen_record["witness"],
                    "mistral": mistral_record["witness"],
                },
                "prosecutor": prosecutor_record["prosecutor"],
                "adjudication": {
                    **review,
                    "model": QWEN_REVIEW_MODEL,
                    "seconds": round(model_seconds, 2),
                    "total_seconds": round(total_seconds, 2),
                    "context": QWEN_REVIEW_CONTEXT,
                    "error": None,
                },
            }

            append_jsonl(REVIEW_FILE, output)
            print("  SAVED")

        except Exception as exc:
            print(f" ERROR: {exc}")
            print("  NOT SAVED — rerunning the script " "will retry this chunk.")


# ============================================================================
# DIAGNOSTICS
# ============================================================================


def show_diagnostics(
    source_text: str,
    parsed: dict[str, Any],
    chunks: list[dict[str, Any]],
):
    print("\n" + "=" * 72)
    print("SOURCE PARSER DIAGNOSTICS")
    print("=" * 72)

    print(f"Source lines:       " f"{len(source_text.splitlines()):,}")
    print(f"Source characters:  " f"{len(source_text):,}")
    print(f"Clean Latin chars:  " f"{len(parsed['text']):,}")
    print(f"Annotations:        " f"{len(parsed['annotations']):,}")
    print(f"PL page markers:    " f"{len(parsed['page_markers']):,}")
    print(f"Source units:       " f"{len(parsed.get('source_units', [])):,}")
    print(f"Translation chunks: " f"{len(chunks):,}")

    print("\nFIRST 300 CLEAN CHARACTERS:")
    print("-" * 72)
    print(parsed["text"][:300])

    print("\nLAST 300 CLEAN CHARACTERS:")
    print("-" * 72)
    print(parsed["text"][-300:])

    print("\nFIRST 5 PAGE MARKERS:")
    print("-" * 72)

    for item in parsed["page_markers"][:5]:
        print(item)

    print("\nFIRST 10 ANNOTATIONS:")
    print("-" * 72)

    for item in parsed["annotations"][:10]:
        print(item)

    print("\nFIRST 5 CHUNKS:")
    print("-" * 72)

    for chunk in chunks[:5]:
        print(
            f"{chunk['id']} "
            f"chars={len(chunk['latin']['text'])} "
            f"PL={chunk['source']['pl_start']}"
            f"->{chunk['source']['pl_end']} "
            f"units={chunk['source'].get('source_unit_ids')} "
            f"annotations={len(chunk['annotations'])}"
        )

    # Specific regression test for the bug we just found.
    suspicious_missing_ref = re.findall(
        r"\([A-Za-z]+\.\s+[IVXLCDM]+,\s*\)",
        parsed["text"],
    )

    print("\nPAGINATION REGRESSION CHECK:")
    print("-" * 72)

    leftover_ranges = re.findall(
        r"(?<![\w(\[,])\b\d+-\d+\b(?![^()]*\))",
        parsed["text"],
    )

    if leftover_ranges:
        print("WARNING: possible edition-pagination ranges remain in clean Latin:")
        for item in leftover_ranges[:10]:
            print(f"  {item}")
    else:
        print("PASS: no obvious inline edition-pagination ranges remain.")

    print("\nREFERENCE REGRESSION CHECK:")
    print("-" * 72)

    if suspicious_missing_ref:
        print(
            "WARNING: Found references with apparently missing " "Arabic verse numbers:"
        )

        for item in suspicious_missing_ref[:10]:
            print(f"  {item}")
    else:
        print("PASS: no obvious '(Book RomanNumeral, )' " "damage detected.")

    print("=" * 72)

    if len(chunks) < 5:
        raise RuntimeError(
            "SAFETY STOP: fewer than five chunks produced. " "Parser is probably wrong."
        )

    if not parsed["text"].startswith("Finitis in Isaiam"):
        raise RuntimeError(
            "SAFETY STOP: clean text does not begin with " "'Finitis in Isaiam'."
        )


# ============================================================================
# MAIN
# ============================================================================


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Translate and adjudicate St Jerome, "
            "Commentary on Ezekiel Book I — pipeline v4.1."
        )
    )

    parser.add_argument(
        "--phase",
        choices=[
            "diagnose",
            "qwen",
            "mistral",
            "draft",
            "prosecutor",
            "review",
            "all",
        ],
        default="all",
        help=(
            "diagnose = parser only; "
            "qwen = Qwen 3.5 witness only; "
            "mistral = Mistral witness only; "
            "draft = both independent witnesses; "
            "prosecutor = Nemotron Ultra adversarial pass; "
            "review = Qwen 3.8 adjudication using prosecutor output; "
            "all = witnesses, prosecutor, then adjudication"
        ),
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help=("Optional smoke-test limit, e.g. --limit 1."),
    )
    parser.add_argument(
        "--prosecutor-provider",
        choices=["openrouter", "ollama"],
        default="openrouter",
        help=(
            "openrouter = Nemotron Ultra (default); "
            "ollama = local Gemma 3 27B fallback"
        ),
    )

    args = parser.parse_args()

    print(f"Reading: {INPUT_FILE}")
    print(f"Pipeline: {PIPELINE_VERSION}")

    source_text = INPUT_FILE.read_text(encoding="utf-8")
    parsed = parse_source(source_text)
    chunks = make_chunks(parsed)

    show_diagnostics(source_text, parsed, chunks)

    if args.phase == "diagnose":
        print("\nDiagnostics only. No models were run.")
        return

    if args.phase in {"qwen", "draft", "all"}:
        run_qwen_draft_pass(chunks, limit=args.limit)

    if args.phase in {"mistral", "draft", "all"}:
        run_mistral_draft_pass(chunks, limit=args.limit)

    if args.phase in {"prosecutor", "all"}:
        run_prosecutor_pass(
            chunks,
            limit=args.limit,
            provider=args.prosecutor_provider,
        )

    if args.phase in {"review", "all"}:
        run_review_pass(chunks, limit=args.limit)

    print("\n" + "=" * 72)
    print("DONE")
    print("=" * 72)

    if QWEN_DRAFT_FILE.exists():
        print(f"Qwen witness:    {QWEN_DRAFT_FILE}")
    if MISTRAL_DRAFT_FILE.exists():
        print(f"Mistral witness: {MISTRAL_DRAFT_FILE}")
    if PROSECUTOR_FILE.exists():
        print(f"Prosecutor:      {PROSECUTOR_FILE}")
    if REVIEW_FILE.exists():
        print(f"Reviewed:        {REVIEW_FILE}")


if __name__ == "__main__":
    main()
