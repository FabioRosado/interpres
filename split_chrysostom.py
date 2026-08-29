from __future__ import annotations

import argparse
import re
from pathlib import Path

try:
    import fitz  # PyMuPDF
except ImportError:
    fitz = None


HOMILY_HEADING_RE = re.compile(
    r"(?im)^[ \t]*Homily[ \t]+(?P<num>[IVXLCDM]+)\.?(?:\d{1,4})?\s*$"
)
END_MATTER_RE = re.compile(
    r"(?im)^[ \t]*Index of \S"
)

PAGE_HEADER_RE = re.compile(
    r"(?i)^(?:Homily\s+\d+|Matthew\s+[IVXLCDM0-9.,\s:-]+)\s*$"
)
DIGITS_ONLY_RE = re.compile(r"^\d+\s*$")

# Very loose Scripture/reference detector for footnote lines.
SCRIPTURE_REF_RE = re.compile(
    r"""(?ix)
    ^
    (?:
        \[?                                  # optional opening bracket
        (?:[1-3]\s+)?                        # optional epistle number
        (?:
            John|Matthew|Matt\.|Mark|Luke|Jerem\.|Is\.|Isa\.|Isaiah|Heb\.|
            Cor\.|Rom\.|Gen\.|Exod\.|Lev\.|Num\.|Deut\.|Wisd\.|
            Josh\.|Judg\.|Ruth|Sam\.|Kings|Chron\.|Ezra|Neh\.|
            Job|Ps\.|Prov\.|Eccles\.|Cant\.|Wisdom|Ecclus\.|
            Dan\.|Hos\.|Joel|Amos|Obad\.|Jonah|Mic\.|Nah\.|
            Hab\.|Zeph\.|Hag\.|Zech\.|Mal\.|Acts|Gal\.|Eph\.|
            Phil\.|Col\.|Thess\.|Tim\.|Tit\.|Philem\.|James|
            Pet\.|Jude|Rev\.|Apoc\.
        )
        \s+
        [ivxlcdm0-9]
    )
    """,
)
NOTEISH_START_RE = re.compile(
    r"""(?ix)
    ^
    (?:
        \[|See\b|Comp\.\b|Or\b|So\b|Our\b|Literally\b|
        i\.e\.|[A-Z][a-z]+\.\s|[\u0370-\u03ff\u1f00-\u1fff]
    )
    """
)

# Embedded footnote marker glued into prose, e.g.:
# require15the  -> require the
# manifest,16both -> manifest, both
INLINE_NOTE_MARKER_RE = re.compile(r"(?<=[A-Za-z,;:])\d{1,4}(?=[A-Za-z])")
TRAILING_NOTE_MARKER_RE = re.compile(
    r"(?<=[A-Za-z”\"’)\],.;:!?])\d{2,4}(?=(?:—|-|\\|\s|[.,;:!?)]|$))"
)
PRINTED_SECTION_CANDIDATE_RE = re.compile(
    r"(?<!^)(?<!\n\n)(?<!\d)(\b\d{1,2}\.\s+(?=[A-Z“]))"
)
SCRIPTURE_CITATION_PREFIX_RE = re.compile(
    r"""(?ix)
    (?:
        (?:Matt|Matthew|John|Mark|Luke|Rom|Cor|Heb|Gal|Eph|Phil|Col|Thess|
        Tim|Pet|Isa|Is|Ps|Gen|Exod|Deut|Wisd)\.\s+
        [ivxlcdm]+\.\s+
    )$
    """
)

SOFT_HYPHEN_RE = re.compile("\u00ad")
NBSP_RE = re.compile("\u00a0")


def roman_to_int(roman: str) -> int:
    values = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
    total = 0
    prev = 0
    for ch in reversed(roman.upper()):
        val = values[ch]
        if val < prev:
            total -= val
        else:
            total += val
            prev = val
    return total


def extract_pdf_text(pdf_path: Path) -> str:
    if fitz is None:
        raise RuntimeError(
            "PyMuPDF is not installed. Run: pip install pymupdf"
        )

    doc = fitz.open(pdf_path)
    pages = []

    for i, page in enumerate(doc, start=1):
        text = page.get_text("text")
        text = SOFT_HYPHEN_RE.sub("", text)
        text = NBSP_RE.sub(" ", text)
        pages.append(text)

        print(f"Extracted page {i}/{len(doc)}")

    return "\n\n".join(pages)


def load_input_text(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        return extract_pdf_text(path)
    return path.read_text(encoding="utf-8")


def normalize_raw_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = SOFT_HYPHEN_RE.sub("", text)
    text = NBSP_RE.sub(" ", text)

    # Join line-break hyphenation:
    # ex-\nhibit -> exhibit
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)

    # Remove trailing spaces
    text = "\n".join(line.rstrip() for line in text.splitlines())

    # Reduce absurd blank-line runs
    text = re.sub(r"\n{4,}", "\n\n\n", text)

    return text.strip()


def split_homilies(full_text: str) -> list[tuple[int, str, str]]:
    matches = list(HOMILY_HEADING_RE.finditer(full_text))
    if not matches:
        raise RuntimeError(
            "No homily headings found. Inspect the raw extraction and adjust HOMILY_HEADING_RE."
        )

    homilies: list[tuple[int, str, str]] = []

    for idx, match in enumerate(matches):
        start = match.start()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(full_text)

        roman = match.group("num").upper()
        number = roman_to_int(roman)
        chunk = full_text[start:end].strip()
        end_matter = END_MATTER_RE.search(chunk)
        if end_matter:
            chunk = chunk[: end_matter.start()].strip()

        homilies.append((number, roman, chunk))

    return homilies


def _next_nonempty(lines: list[str], i: int) -> int | None:
    j = i + 1
    while j < len(lines) and not lines[j].strip():
        j += 1
    return j if j < len(lines) else None


def is_page_boundary(lines: list[str], i: int) -> bool:
    stripped = lines[i].strip()
    if not DIGITS_ONLY_RE.match(stripped):
        return False
    next_index = _next_nonempty(lines, i)
    return next_index is not None and bool(PAGE_HEADER_RE.match(lines[next_index].strip()))


def _has_nearby_page_boundary(lines: list[str], i: int, *, max_nonempty: int = 12) -> bool:
    nonempty = 0
    j = i + 1
    while j < len(lines):
        if is_page_boundary(lines, j):
            return True
        if lines[j].strip():
            nonempty += 1
            if nonempty > max_nonempty:
                return False
        j += 1
    return False


def is_footnote_start(lines: list[str], i: int) -> bool:
    """
    Detects a likely footnote block start, e.g.
    15
    [Greek note...]
    or
    17
    John xiv. 26.
    """
    line = lines[i].strip()
    if not DIGITS_ONLY_RE.match(line):
        return False
    if is_page_boundary(lines, i):
        return False
    if int(line) < 10:
        return False

    # Look ahead to next non-empty line
    j = _next_nonempty(lines, i)
    if j is None:
        return False

    nxt = lines[j].strip()

    if nxt.startswith("["):
        return True
    if SCRIPTURE_REF_RE.match(nxt):
        return True
    if NOTEISH_START_RE.match(nxt):
        return True
    if re.match(r"^[A-Z][A-Za-z]", nxt) and _has_nearby_page_boundary(lines, i):
        return True

    return False


def remove_headers_and_extract_notes(raw_text: str) -> tuple[str, str, list[str]]:
    lines = raw_text.splitlines()
    body_lines: list[str] = []
    note_lines: list[str] = []
    note_markers: list[str] = []

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Drop page number lines and running headers from body.
        if is_page_boundary(lines, i):
            i += 1
            while i < len(lines) and not lines[i].strip():
                i += 1
            if i < len(lines) and PAGE_HEADER_RE.match(lines[i].strip()):
                i += 1
            while i < len(lines) and not lines[i].strip():
                i += 1
            continue

        if DIGITS_ONLY_RE.match(stripped):
            if is_footnote_start(lines, i):
                # Capture the page-bottom note block. Some extracted Greek
                # apparatus notes have unbalanced brackets, so page boundary
                # structure is safer than bracket-depth balancing.
                while i < len(lines):
                    if is_page_boundary(lines, i):
                        break
                    current = lines[i]
                    s = current.strip()
                    if DIGITS_ONLY_RE.match(s):
                        note_markers.append(s)
                    note_lines.append(current)
                    i += 1

                continue
            else:
                # Page number / apparatus number not confidently footnote-start:
                # omit from body.
                i += 1
                continue

        previous_marker = None
        if body_lines:
            previous_marker_match = re.search(
                r"(?<=[A-Za-z”\"’)])(\d{2,4})$", body_lines[-1].strip()
            )
            if previous_marker_match:
                previous_marker = previous_marker_match.group(1)
        if (
            previous_marker
            and (NOTEISH_START_RE.match(stripped) or SCRIPTURE_REF_RE.match(stripped))
            and _has_nearby_page_boundary(lines, i)
        ):
            note_markers.append(previous_marker)
            note_lines.append(previous_marker)
            while i < len(lines):
                if is_page_boundary(lines, i):
                    break
                current = lines[i]
                s = current.strip()
                if DIGITS_ONLY_RE.match(s):
                    note_markers.append(s)
                note_lines.append(current)
                i += 1
            continue

        if PAGE_HEADER_RE.match(stripped):
            i += 1
            continue

        if (
            body_lines
            and re.search(r"[A-Za-z]\d{1,4}$", body_lines[-1].strip())
            and re.match(r"^[a-z]", stripped)
        ):
            body_lines[-1] = re.sub(
                r"(?<=[A-Za-z])\d{1,4}$", "", body_lines[-1].rstrip()
            ) + line.lstrip()
        else:
            body_lines.append(line)
        i += 1

    body = "\n".join(body_lines).strip()
    notes = "\n".join(note_lines).strip()

    return body, notes, note_markers


def normalize_body_text(body: str, note_markers: list[str] | None = None) -> str:
    markers = sorted(set(note_markers or []), key=lambda value: (-len(value), value))
    for marker in markers:
        pattern = re.compile(
            rf"(?<=[A-Za-z”\"’)\],.;:!?]){re.escape(marker)}(?=(?:[A-Za-z“\"'([]|\s|[.,;:!?)]|$))"
        )
        body = pattern.sub(" ", body)

    # Fallback for embedded markers stuck inside words.
    body = INLINE_NOTE_MARKER_RE.sub(" ", body)
    body = TRAILING_NOTE_MARKER_RE.sub(" ", body)

    # Collapse internal excessive spaces
    body = re.sub(r"[ \t]+", " ", body)

    lines = [ln.strip() for ln in body.splitlines()]

    paragraphs: list[str] = []
    current: list[str] = []

    for line in lines:
        if not line:
            if current:
                paragraphs.append(" ".join(current).strip())
                current = []
            continue

        current.append(line)

    if current:
        paragraphs.append(" ".join(current).strip())

    clean = "\n\n".join(paragraphs)

    # Tidy spacing before punctuation
    clean = re.sub(r"\s+([,.;:!?])", r"\1", clean)

    def section_break(match: re.Match[str]) -> str:
        prefix = clean[max(0, match.start() - 48) : match.start()]
        if SCRIPTURE_CITATION_PREFIX_RE.search(prefix):
            return match.group(1)
        return "\n\n" + match.group(1)

    clean = PRINTED_SECTION_CANDIDATE_RE.sub(section_break, clean)

    # Reduce weird blank runs
    clean = re.sub(r"\n{3,}", "\n\n", clean)

    return clean.strip()


def write_outputs(homilies: list[tuple[int, str, str]], out_dir: Path, full_text: str) -> None:
    raw_dir = out_dir / "raw"
    clean_dir = out_dir / "clean"
    notes_dir = out_dir / "notes"

    raw_dir.mkdir(parents=True, exist_ok=True)
    clean_dir.mkdir(parents=True, exist_ok=True)
    notes_dir.mkdir(parents=True, exist_ok=True)

    (raw_dir / "_full_extracted.txt").write_text(full_text, encoding="utf-8")

    for number, roman, raw_chunk in homilies:
        raw_body, notes, note_markers = remove_headers_and_extract_notes(raw_chunk)
        clean_body = normalize_body_text(raw_body, note_markers)

        raw_path = raw_dir / f"homily-{number:03d}.raw.txt"
        clean_path = clean_dir / f"homily-{number:03d}.txt"
        notes_path = notes_dir / f"homily-{number:03d}.notes.txt"

        raw_path.write_text(raw_chunk.strip() + "\n", encoding="utf-8")
        clean_path.write_text(clean_body + "\n", encoding="utf-8")
        notes_path.write_text((notes.strip() + "\n") if notes.strip() else "", encoding="utf-8")

        print(
            f"Homily {number:03d} ({roman}): "
            f"raw={len(raw_chunk):,} chars | "
            f"clean={len(clean_body):,} chars | "
            f"notes={len(notes):,} chars"
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract and split Chrysostom NPNF homilies into clean text files."
    )
    parser.add_argument(
        "input_path",
        type=Path,
        help="Path to the PDF or already-extracted .txt file",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("chrysostom_output"),
        help="Output directory",
    )
    args = parser.parse_args()

    text = load_input_text(args.input_path)
    text = normalize_raw_text(text)

    homilies = split_homilies(text)
    write_outputs(homilies, args.output, text)

    print(f"\nDone. Wrote {len(homilies)} homilies into: {args.output}")


if __name__ == "__main__":
    main()
