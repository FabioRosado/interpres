from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict, deque
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from .config import PipelineConfig

BOOK_HEADING_RE = re.compile(r"^\s*LIBER\s+([A-Z]+)\.?\s*$", re.IGNORECASE)
PAGE_RE = re.compile(r"-*\[page\s+([0-9]+[A-D])\]-*", re.IGNORECASE)
INLINE_NOTE_RE = re.compile(r"\[(\d+)\]")
FOOTNOTE_SEPARATOR_RE = re.compile(r"^\s*_{10,}\s*$")
FOOTNOTE_DEFINITION_RE = re.compile(r"^\s*(\d+)\s*:\s*(.+?)\s*$")
LEADING_EDITION_PAGINATION_RE = re.compile(r"^\s*(\d+(?:-\d+)?)\s+(?=\S)")
STANDALONE_EDITION_PAGINATION_RE = re.compile(r"^\s*(\d+(?:-\d+)?)\s*$")
# Corpus Corporum interleaves sequential edition pagination with prose. It can
# appear as a range (``aliorumque 3-4 malis``) or a single token
# (``Dominus 6 ad baptisma``). Require whitespace boundaries so citation
# continuations such as ``(Ps. XCVI,`` / page break / ``2).`` remain text.
INLINE_EDITION_PAGINATION_RE = re.compile(r"(?<!\S)([0-9]+(?:-[0-9]+)?)(?=\s)")


class SourceParseError(ValueError):
    pass


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _normalise_space(value: str) -> str:
    return re.sub(r"[ \t]+", " ", value).strip()


def _collect_footnotes(source_text: str) -> dict[str, deque[dict[str, str]]]:
    definitions: dict[str, deque[dict[str, str]]] = defaultdict(deque)
    in_block = False
    for line in source_text.splitlines():
        if FOOTNOTE_SEPARATOR_RE.match(line):
            in_block = True
            continue
        if not in_block:
            continue
        match = FOOTNOTE_DEFINITION_RE.match(line)
        if match:
            definitions[match.group(1)].append(
                {
                    "reference": match.group(2).strip(),
                    "raw_definition": line,
                }
            )
        elif line.strip():
            in_block = False
    return definitions


def _strip_inline_edition_pagination(
    line: str,
) -> tuple[str, list[tuple[str, int]]]:
    """Remove edition pagination tokens only outside parentheses/brackets."""
    output: list[str] = []
    annotations: list[tuple[str, int]] = []
    cursor = 0
    paren_depth = 0
    bracket_depth = 0
    for match in INLINE_EDITION_PAGINATION_RE.finditer(line):
        prefix = line[cursor : match.start()]
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
            annotations.append((match.group(1), len("".join(output).rstrip())))
            output.append(" ")
        else:
            output.append(match.group(0))
        cursor = match.end()
    output.append(line[cursor:])
    return _normalise_space("".join(output)), annotations


def parse_source(
    source_text: str,
    *,
    book: int,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Parse a Corpus Corporum download into stable page-based source units.

    PL page blocks are the stable boundaries that are actually present across
    this download. Edition line pagination and linked footnotes remain
    annotations; they are not mistaken for canonical prose units.
    """
    heading_match = None
    raw_offset = 0
    for line in source_text.splitlines(keepends=True):
        if BOOK_HEADING_RE.match(line.rstrip("\r\n")):
            heading_match = (raw_offset, raw_offset + len(line), line.strip())
            break
        raw_offset += len(line)
    if heading_match is None:
        raise SourceParseError("Could not find a 'LIBER ...' heading")

    body_start = heading_match[1]
    body = source_text[body_start:]
    footnotes = _collect_footnotes(body)
    pieces: list[str] = []
    clean_length = 0
    annotations: list[dict[str, Any]] = []
    page_markers: list[dict[str, Any]] = []
    units: list[dict[str, Any]] = []
    page_counts: dict[str, int] = defaultdict(int)
    current: dict[str, Any] | None = None
    in_footnotes = False
    pending_paragraph = False
    unnumbered_count = 0

    def new_unit(page: str | None, raw_start: int, marker: dict[str, Any] | None):
        nonlocal current, unnumbered_count
        if page:
            page_counts[page] += 1
            suffix = f"-o{page_counts[page]}" if page_counts[page] > 1 else ""
            unit_id = f"book{book:02d}-pl-{page}{suffix}"
        else:
            unnumbered_count += 1
            unit_id = f"book{book:02d}-unnumbered-{unnumbered_count:03d}"
        current = {
            "source_unit_id": unit_id,
            "canonical_parent_id": unit_id,
            "book": book,
            "page": page,
            "page_marker": marker,
            "clean_start": clean_length,
            "clean_end": clean_length,
            "raw_start": raw_start,
            "raw_end": raw_start,
            "annotation_ids": [],
        }

    def finish_unit(raw_end: int):
        nonlocal current
        if current is None:
            return
        current["clean_end"] = clean_length
        current["raw_end"] = raw_end
        full_text = "".join(pieces)
        current["text"] = full_text[current["clean_start"] : clean_length].strip()
        if current["text"]:
            leading = full_text[current["clean_start"] : clean_length].find(current["text"])
            current["clean_start"] += max(0, leading)
            current["clean_end"] = current["clean_start"] + len(current["text"])
            current["fingerprint"] = _sha256_text(current["text"])
            units.append(current)
        current = None

    def ensure_unit(raw_start: int):
        if current is None:
            new_unit(None, raw_start, None)

    def append_text(value: str, *, paragraph: bool = False) -> tuple[int, int]:
        nonlocal clean_length
        value = _normalise_space(value)
        if not value:
            return clean_length, clean_length
        if pieces:
            separator = "\n\n" if paragraph else " "
            if pieces[-1].endswith((" ", "\n")) or value.startswith(
                (".", ",", ";", ":", "!", "?", ")", "]")
            ):
                separator = ""
            pieces.append(separator)
            clean_length += len(separator)
        start = clean_length
        pieces.append(value)
        clean_length += len(value)
        return start, clean_length

    line_raw_start = body_start
    for raw_line in body.splitlines(keepends=True):
        line_raw_end = line_raw_start + len(raw_line)
        line = raw_line.rstrip("\r\n")

        page_matches = list(PAGE_RE.finditer(line))
        if page_matches:
            # Corpus downloads use marker-only lines, but handle residual text
            # defensively and retain every marker verbatim.
            for match in page_matches:
                finish_unit(line_raw_start + match.start())
                page = match.group(1).upper()
                marker = {
                    "page": page,
                    "raw": match.group(0),
                    "raw_start": line_raw_start + match.start(),
                    "raw_end": line_raw_start + match.end(),
                    "clean_offset": clean_length,
                }
                page_markers.append(marker)
                new_unit(page, marker["raw_start"], marker)
            line = PAGE_RE.sub(" ", line)
            if not line.strip():
                pending_paragraph = False
                line_raw_start = line_raw_end
                continue

        if FOOTNOTE_SEPARATOR_RE.match(line):
            in_footnotes = True
            pending_paragraph = True
            line_raw_start = line_raw_end
            continue
        if in_footnotes:
            if FOOTNOTE_DEFINITION_RE.match(line) or not line.strip():
                line_raw_start = line_raw_end
                continue
            in_footnotes = False

        if not line.strip():
            pending_paragraph = True
            line_raw_start = line_raw_end
            continue

        ensure_unit(line_raw_start)

        standalone = STANDALONE_EDITION_PAGINATION_RE.match(line)
        leading = LEADING_EDITION_PAGINATION_RE.match(line)
        if standalone or leading:
            match = standalone or leading
            assert match is not None
            annotation = {
                "annotation_id": f"book{book:02d}-ann-{len(annotations)+1:05d}",
                "type": "edition_pagination",
                "value": match.group(1),
                "clean_offset": clean_length,
                "raw_start": line_raw_start + match.start(1),
                "raw_end": line_raw_start + match.end(1),
                "source_unit_id": current["source_unit_id"],
            }
            annotations.append(annotation)
            current["annotation_ids"].append(annotation["annotation_id"])
            if standalone:
                line_raw_start = line_raw_end
                continue
            line = line[leading.end() :]

        line, inline_pagination = _strip_inline_edition_pagination(line)
        for value, local_offset in inline_pagination:
            annotation = {
                "annotation_id": f"book{book:02d}-ann-{len(annotations)+1:05d}",
                "type": "edition_pagination",
                "value": value,
                "clean_offset": clean_length + local_offset,
                "raw_start": line_raw_start,
                "raw_end": line_raw_end,
                "source_unit_id": current["source_unit_id"],
            }
            annotations.append(annotation)
            current["annotation_ids"].append(annotation["annotation_id"])

        cursor = 0
        first_piece = True
        for note_match in INLINE_NOTE_RE.finditer(line):
            before = line[cursor : note_match.start()]
            _, _ = append_text(
                before,
                paragraph=pending_paragraph and first_piece,
            )
            pending_paragraph = False
            first_piece = False
            marker = note_match.group(1)
            definition = footnotes[marker].popleft() if footnotes.get(marker) else None
            annotation = {
                "annotation_id": f"book{book:02d}-ann-{len(annotations)+1:05d}",
                "type": "editorial_reference",
                "marker": marker,
                "raw_marker": note_match.group(0),
                "reference": definition and definition["reference"],
                "raw_definition": definition and definition["raw_definition"],
                "clean_offset": clean_length,
                "raw_start": line_raw_start + note_match.start(),
                "raw_end": line_raw_start + note_match.end(),
                "source_unit_id": current["source_unit_id"],
            }
            annotations.append(annotation)
            current["annotation_ids"].append(annotation["annotation_id"])
            cursor = note_match.end()
        append_text(line[cursor:], paragraph=pending_paragraph and first_piece)
        pending_paragraph = False
        current["raw_end"] = line_raw_end
        line_raw_start = line_raw_end

    finish_unit(len(source_text))
    clean_text = "".join(pieces).strip()
    # Leading/trailing stripping can only affect an unnumbered empty prefix;
    # real units begin at the first page marker in this corpus.
    for annotation in annotations:
        offset = annotation["clean_offset"]
        annotation["context"] = clean_text[max(0, offset - 70) : offset + 90]

    return {
        "schema_version": 1,
        "book": book,
        "heading": heading_match[2],
        "metadata": dict(metadata or {}),
        "source_fingerprint": _sha256_text(source_text),
        "clean_fingerprint": _sha256_text(clean_text),
        "text": clean_text,
        "source_units": units,
        "page_markers": page_markers,
        "annotations": annotations,
        "unmatched_footnote_definitions": {
            marker: list(values) for marker, values in footnotes.items() if values
        },
    }


def split_sentences(text: str) -> list[tuple[int, int, str]]:
    results: list[tuple[int, int, str]] = []
    start = 0
    for match in re.finditer(r"(?<=[.!?])(?:\s+|\n+)", text):
        candidate = text[start : match.start()].strip()
        if candidate:
            actual = text.find(candidate, start, match.start() + 1)
            results.append((actual, actual + len(candidate), candidate))
        start = match.end()
    tail = text[start:].strip()
    if tail:
        actual = text.find(tail, start)
        results.append((actual, actual + len(tail), tail))
    return results


def _expand_large_units(
    units: list[dict[str, Any]], max_chars: int
) -> list[dict[str, Any]]:
    expanded: list[dict[str, Any]] = []
    for unit in units:
        if len(unit["text"]) <= max_chars:
            expanded.append({**unit, "part": None})
            continue
        sentences = split_sentences(unit["text"])
        if not sentences:
            raise SourceParseError(
                f"Oversized source unit {unit['source_unit_id']} has no natural split"
            )
        current: list[tuple[int, int, str]] = []
        part = 1
        for sentence in sentences:
            prospective = sentence[1] - current[0][0] if current else len(sentence[2])
            if current and prospective > max_chars:
                start, end = current[0][0], current[-1][1]
                text = unit["text"][start:end].strip()
                expanded.append(
                    {
                        **unit,
                        "source_unit_id": f"{unit['canonical_parent_id']}.p{part:03d}",
                        "clean_start": unit["clean_start"] + start,
                        "clean_end": unit["clean_start"] + end,
                        "text": text,
                        "fingerprint": _sha256_text(text),
                        "part": part,
                    }
                )
                part += 1
                current = []
            current.append(sentence)
        if current:
            start, end = current[0][0], current[-1][1]
            text = unit["text"][start:end].strip()
            expanded.append(
                {
                    **unit,
                    "source_unit_id": f"{unit['canonical_parent_id']}.p{part:03d}",
                    "clean_start": unit["clean_start"] + start,
                    "clean_end": unit["clean_start"] + end,
                    "text": text,
                    "fingerprint": _sha256_text(text),
                    "part": part,
                }
            )
    return expanded


def _context_text(value: str, max_chars: int, *, before: bool) -> str:
    value = value.strip()
    if len(value) <= max_chars:
        return value
    sentences = split_sentences(value)
    if not sentences:
        return value[-max_chars:] if before else value[:max_chars]
    selected: list[str] = []
    chars = 0
    iterable: Iterable[tuple[int, int, str]] = reversed(sentences) if before else sentences
    for _, _, sentence in iterable:
        prospective = chars + (1 if selected else 0) + len(sentence)
        if selected and prospective > max_chars:
            break
        selected.append(sentence)
        chars = prospective
    if before:
        selected.reverse()
    return " ".join(selected)


def _ends_naturally(unit: dict[str, Any]) -> bool:
    return bool(re.search(r"[.!?][\"')\]]?\s*$", unit["text"]))


def make_chunks(parsed: dict[str, Any], chunking: dict[str, Any]) -> list[dict[str, Any]]:
    target = int(chunking.get("target_source_units", 4))
    minimum = int(chunking.get("min_source_units", 3))
    maximum = int(chunking.get("max_source_units", target))
    max_chars = int(chunking.get("max_chars", 6500))
    context_units = int(chunking.get("context_units", 1))
    context_max = int(chunking.get("context_max_chars", 1800))
    if not (1 <= minimum <= target <= maximum):
        raise ValueError("chunking must satisfy 1 <= min <= target <= max")

    units = _expand_large_units(parsed["source_units"], max_chars)
    annotations = parsed["annotations"]
    chunks: list[dict[str, Any]] = []
    cursor = 0
    while cursor < len(units):
        remaining = len(units) - cursor
        if remaining <= maximum:
            count = remaining
        else:
            choices = list(range(minimum, maximum + 1))
            # Prefer a natural terminal boundary, then distance to target.
            count = min(
                choices,
                key=lambda n: (
                    0 if _ends_naturally(units[cursor + n - 1]) else 1,
                    abs(target - n),
                ),
            )
            while count > minimum and 0 < remaining - count < minimum:
                count -= 1
        selected = units[cursor : cursor + count]
        # Safety cap can flush fewer normal units, but never split them merely
        # to hit a target. Oversized individual units were already split only
        # at sentence boundaries.
        while len(selected) > minimum:
            span_chars = selected[-1]["clean_end"] - selected[0]["clean_start"]
            if span_chars <= max_chars:
                break
            selected = selected[:-1]
        count = len(selected)
        start = selected[0]["clean_start"]
        end = selected[-1]["clean_end"]
        target_latin = parsed["text"][start:end].strip()
        actual_start = parsed["text"].find(target_latin, start, end + 1)
        start = actual_start
        end = start + len(target_latin)

        before_units = units[max(0, cursor - context_units) : cursor]
        after_units = units[cursor + count : cursor + count + context_units]
        before = "\n\n".join(unit["text"] for unit in before_units)
        after = "\n\n".join(unit["text"] for unit in after_units)
        context_before = _context_text(before, context_max, before=True) if before else ""
        context_after = _context_text(after, context_max, before=False) if after else ""

        chunk_annotations = []
        selected_ids = {unit["source_unit_id"] for unit in selected}
        selected_parents = {unit["canonical_parent_id"] for unit in selected}
        for annotation in annotations:
            annotation_offset = annotation["clean_offset"]
            source_matches = annotation["source_unit_id"] in selected_ids | selected_parents
            offset_matches = start <= annotation_offset <= end
            # Page-opening note markers can precede the materialized inter-page
            # separator by one character while belonging to the first target.
            opening_marker = (
                annotation["source_unit_id"] == selected[0]["canonical_parent_id"]
                and annotation_offset == start - 1
            )
            if source_matches and (offset_matches or opening_marker):
                copied = dict(annotation)
                # A marker can occur at the very beginning of a page before
                # the inter-page separator is materialized. It still belongs
                # at target offset zero, not offset -1.
                effective_offset = min(end, max(start, annotation["clean_offset"]))
                copied["global_clean_offset"] = effective_offset
                copied["offset"] = effective_offset - start
                chunk_annotations.append(copied)

        unit_ids = [unit["source_unit_id"] for unit in selected]
        stable_material = json.dumps(unit_ids, ensure_ascii=False, separators=(",", ":"))
        digest = _sha256_text(stable_material)[:10]
        first_short = unit_ids[0].removeprefix(f"book{parsed['book']:02d}-")
        last_short = unit_ids[-1].removeprefix(f"book{parsed['book']:02d}-")
        chunk_id = f"book{parsed['book']:02d}-{first_short}--{last_short}-{digest}"

        target_spans = [
            {
                "role": "target",
                "source_unit_id": unit["source_unit_id"],
                "canonical_parent_id": unit["canonical_parent_id"],
                "clean_start": unit["clean_start"],
                "clean_end": unit["clean_end"],
                "page": unit.get("page"),
            }
            for unit in selected
        ]
        context_spans = [
            {
                "role": "context_before",
                "source_unit_id": unit["source_unit_id"],
                "clean_start": unit["clean_start"],
                "clean_end": unit["clean_end"],
                "page": unit.get("page"),
            }
            for unit in before_units
        ] + [
            {
                "role": "context_after",
                "source_unit_id": unit["source_unit_id"],
                "clean_start": unit["clean_start"],
                "clean_end": unit["clean_end"],
                "page": unit.get("page"),
            }
            for unit in after_units
        ]
        pages = list(dict.fromkeys(unit["page"] for unit in selected if unit.get("page")))
        unique_page_markers = []
        seen_marker_offsets = set()
        for unit in selected:
            marker = unit.get("page_marker")
            if marker and marker.get("raw_start") not in seen_marker_offsets:
                seen_marker_offsets.add(marker.get("raw_start"))
                unique_page_markers.append(marker)
        chunks.append(
            {
                "schema_version": 1,
                "chunk_id": chunk_id,
                "id": chunk_id,
                "book": parsed["book"],
                "source": {
                    **parsed.get("metadata", {}),
                    "source_fingerprint": parsed["source_fingerprint"],
                    "source_unit_ids": unit_ids,
                    "canonical_source_unit_ids": list(
                        dict.fromkeys(unit["canonical_parent_id"] for unit in selected)
                    ),
                    "pages": pages,
                    "pl_start": pages[0] if pages else None,
                    "pl_end": pages[-1] if pages else None,
                },
                "target_latin": target_latin,
                "context_before": context_before,
                "context_after": context_after,
                "latin": {
                    "text": target_latin,
                    "start_offset": start,
                    "end_offset": end,
                    "context_before": context_before,
                    "context_after": context_after,
                },
                "page_markers": unique_page_markers,
                "source_spans": target_spans + context_spans,
                "source_units": selected,
                "annotations": chunk_annotations,
                "source_fingerprint": _sha256_text(target_latin),
            }
        )
        cursor += count
    return chunks


def preprocess_book(config: PipelineConfig, book: int) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    source_path = config.source_path(book)
    parsed = parse_source(
        source_path.read_text(encoding="utf-8"),
        book=book,
        metadata=config.section("source").get("metadata", {}),
    )
    chunks = make_chunks(parsed, config.section("chunking"))
    artifact_dir = config.path_value("artifacts") / f"book{book:02d}"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    _write_json(artifact_dir / "source.json", parsed)
    _write_jsonl(artifact_dir / "source_units.jsonl", parsed["source_units"])
    _write_jsonl(artifact_dir / "chunks.jsonl", chunks)
    return parsed, chunks


def load_chunks(config: PipelineConfig, book: int) -> list[dict[str, Any]]:
    path = config.path_value("artifacts") / f"book{book:02d}" / "chunks.jsonl"
    if not path.exists():
        _, chunks = preprocess_book(config, book)
        return chunks
    return list(_read_jsonl(path))


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def _write_jsonl(path: Path, values: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        for value in values:
            handle.write(json.dumps(value, ensure_ascii=False, separators=(",", ":")))
            handle.write("\n")
    temporary.replace(path)


def _read_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise SourceParseError(f"Invalid JSONL {path}:{line_number}: {exc}") from exc
            if not isinstance(value, dict):
                raise SourceParseError(f"Expected object at {path}:{line_number}")
            yield value
