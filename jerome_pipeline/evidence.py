from __future__ import annotations

import csv
import difflib
import json
import math
import re
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Protocol

from glossary import WhitakersWordsBackend, analysis_to_json, tokenize_with_offsets

from .cache import canonical_digest, utc_now
from .config import PipelineConfig
from .retrieval import LocalRetrievalIndex, build_local_retrieval_index
from .source import parse_source, preprocess_book


EVIDENCE_SERVICE_VERSION = 3
CONCORDANCE_VERSION = 2


def _source_manifest(parsed_books: list[dict[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {
        "schema": "canonical-source-manifest/v1",
        "books": [
            {
                "book": parsed["book"],
                "source_fingerprint": parsed["source_fingerprint"],
                "clean_fingerprint": parsed["clean_fingerprint"],
                "units": [
                    {
                        "source_unit_id": unit["source_unit_id"],
                        "fingerprint": unit["fingerprint"],
                    }
                    for unit in parsed["source_units"]
                ],
            }
            for parsed in sorted(parsed_books, key=lambda item: int(item["book"]))
        ],
    }
    value["canonical_source_digest"] = canonical_digest(value)
    return value


def canonical_source_manifest(
    config: PipelineConfig, books: list[int] | None = None
) -> dict[str, Any]:
    configured = sorted(int(key) for key in config.section("source").get("books", {}))
    selected = books or configured
    parsed = [
        parse_source(
            config.source_path(book).read_text(encoding="utf-8"),
            book=book,
            metadata=config.section("source").get("metadata", {}),
        )
        for book in selected
    ]
    return _source_manifest(parsed)


def _concordance_metadata_path(path: Path) -> Path:
    return path.with_suffix(path.suffix + ".meta.json")


def normalize_latin(value: str) -> str:
    value = unicodedata.normalize("NFKD", value.casefold())
    value = value.replace("æ", "ae").replace("œ", "oe")
    value = value.replace("j", "i").replace("v", "u")
    value = "".join(char for char in value if not unicodedata.combining(char))
    return " ".join(re.findall(r"[a-z]+", value))


def bound_evidence_results(
    results: list[dict[str, Any]],
    *,
    query: str,
    snippet_chars: int,
) -> list[dict[str, Any]]:
    """Bound prompt-facing text while preserving exact source offsets.

    The retrieved corpus remains unchanged. Receipts carry the exact substring
    plus original character counts/offsets, rather than an LLM summary.
    """
    limit = max(80, int(snippet_chars))
    bounded: list[dict[str, Any]] = []
    for result in results:
        copied = dict(result)
        truncation: dict[str, Any] = {}
        for field in (
            "text",
            "latin",
            "cpdv",
            "odr",
            "context_before",
            "context_after",
        ):
            value = copied.get(field)
            if not isinstance(value, str) or len(value) <= limit:
                continue
            folded = value.casefold()
            position = folded.find(query.casefold().strip()) if query.strip() else -1
            start = 0 if position < 0 else max(0, position - limit // 3)
            end = min(len(value), start + limit)
            start = max(0, end - limit)
            if start > 0:
                boundary = value.find(" ", start, min(end, start + 60))
                if boundary >= 0:
                    start = boundary + 1
            if end < len(value):
                boundary = value.rfind(" ", max(start, end - 60), end)
                if boundary > start:
                    end = boundary
            copied[field] = value[start:end]
            truncation[field] = {
                "original_chars": len(value),
                "snippet_start": start,
                "snippet_end": end,
                "truncated": True,
            }
        if truncation:
            copied["truncation"] = truncation
        bounded.append(copied)
    return bounded


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    results = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"Expected JSON object at {path}:{line_number}")
            results.append(value)
    return results


def _write_jsonl(path: Path, values: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        for value in values:
            handle.write(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n")
    temporary.replace(path)


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def build_concordance(
    config: PipelineConfig,
    *,
    books: list[int] | None = None,
    include_lemmas: bool = True,
    backend: WhitakersWordsBackend | None = None,
) -> dict[str, Any]:
    configured_books = sorted(int(key) for key in config.section("source").get("books", {}))
    selected_books = books or configured_books
    lexicon = backend or (WhitakersWordsBackend() if include_lemmas else None)
    token_cache: dict[str, set[str]] = {}
    records: list[dict[str, Any]] = []
    parsed_books: list[dict[str, Any]] = []
    for book in selected_books:
        parsed, _ = preprocess_book(config, book)
        parsed_books.append(parsed)
        for unit in parsed["source_units"]:
            lemmas: set[str] = set()
            if lexicon is not None:
                for token, _ in tokenize_with_offsets(unit["text"]):
                    folded = token.casefold()
                    if folded not in token_cache:
                        analysis = lexicon.analyze_word(folded)
                        token_cache[folded] = {
                            sense.lemma.casefold() for sense in analysis.senses if sense.lemma
                        }
                    lemmas.update(token_cache[folded])
            records.append(
                {
                    "source_unit_id": unit["source_unit_id"],
                    "book": book,
                    "page": unit.get("page"),
                    "text": unit["text"],
                    "normalized": normalize_latin(unit["text"]),
                    "lemmas": sorted(lemmas),
                    "source_fingerprint": unit["fingerprint"],
                    "provenance": {
                        "corpus": parsed.get("metadata", {}).get("corpus"),
                        "work": parsed.get("metadata", {}).get("work"),
                        "source_unit_id": unit["source_unit_id"],
                        "page": unit.get("page"),
                    },
                }
            )
    path = config.path_value("concordance")
    _write_jsonl(path, records)
    manifest = _source_manifest(parsed_books)
    metadata = {
        "schema": "jerome-concordance-metadata/v2",
        "concordance_version": CONCORDANCE_VERSION,
        "built_at": utc_now(),
        "books": selected_books,
        "records": len(records),
        "records_digest": canonical_digest(records),
        "canonical_source": manifest,
        "canonical_source_digest": manifest["canonical_source_digest"],
        "lemma_index": include_lemmas,
    }
    _write_json(_concordance_metadata_path(path), metadata)
    return {
        "path": str(path),
        "metadata_path": str(_concordance_metadata_path(path)),
        "records": len(records),
        "books": selected_books,
        "lemma_index": include_lemmas,
        "unique_analyzed_forms": len(token_cache),
        "records_digest": metadata["records_digest"],
        "canonical_source_digest": metadata["canonical_source_digest"],
    }


def build_retrieval_index(config: PipelineConfig) -> dict[str, Any]:
    settings = config.section("retrieval")
    expected = canonical_source_manifest(config)
    concordance = JeromeConcordance(
        config.path_value("concordance"), expected_manifest=expected
    )
    if not concordance.freshness["fresh"]:
        raise ValueError(
            "Cannot build retrieval index from stale concordance: "
            + "; ".join(concordance.freshness["reasons"])
        )
    return build_local_retrieval_index(
        config.path_value("concordance"),
        config.path_value("retrieval_index"),
        dimensions=int(settings.get("dimensions", 48)),
        min_document_frequency=int(
            settings.get("min_document_frequency", 1)
        ),
        source_identity=expected,
        concordance_identity=concordance.identity,
    )


class JeromeConcordance:
    def __init__(
        self, path: Path, *, expected_manifest: dict[str, Any] | None = None
    ):
        self.path = path
        self.records = _read_jsonl(path)
        metadata_path = _concordance_metadata_path(path)
        try:
            self.metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            self.metadata = {}
        reasons: list[str] = []
        records_digest = canonical_digest(self.records)
        if self.metadata.get("records_digest") != records_digest:
            reasons.append("concordance records do not match persisted records_digest")
        if expected_manifest is not None:
            if (
                self.metadata.get("canonical_source_digest")
                != expected_manifest.get("canonical_source_digest")
            ):
                reasons.append("concordance canonical source digest is stale")
            expected_units = {
                item["source_unit_id"]: item["fingerprint"]
                for book in expected_manifest.get("books", [])
                for item in book.get("units", [])
            }
            actual_units = {
                str(item.get("source_unit_id")): str(item.get("source_fingerprint"))
                for item in self.records
            }
            if actual_units != expected_units:
                reasons.append("concordance unit fingerprints differ from canonical source")
        self.freshness = {
            "fresh": not reasons,
            "status": "fresh" if not reasons else "stale_evidence",
            "reasons": reasons,
            "expected_canonical_source_digest": (
                expected_manifest or {}
            ).get("canonical_source_digest"),
            "actual_canonical_source_digest": self.metadata.get(
                "canonical_source_digest"
            ),
            "records_digest": records_digest,
        }

    @property
    def identity(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "concordance_version": self.metadata.get("concordance_version"),
            "records_digest": self.freshness["records_digest"],
            "canonical_source_digest": self.metadata.get("canonical_source_digest"),
            "freshness": self.freshness,
        }

    def _contextual_result(
        self,
        index: int,
        result: dict[str, Any],
    ) -> dict[str, Any]:
        record = self.records[index]
        context_provenance: dict[str, Any] = {}
        for field, neighbor_index in (
            ("context_before", index - 1),
            ("context_after", index + 1),
        ):
            neighbor = (
                self.records[neighbor_index]
                if 0 <= neighbor_index < len(self.records)
                else None
            )
            # Never leak context across configured books when their records
            # are adjacent in the combined concordance.
            if neighbor is None or neighbor.get("book") != record.get("book"):
                result[field] = None
                context_provenance[field] = None
                continue
            result[field] = neighbor.get("text", "")
            context_provenance[field] = neighbor.get("provenance", {})
        result["context_provenance"] = context_provenance
        return result

    def exact(self, query: str, *, normalized: bool = False, limit: int = 8) -> list[dict[str, Any]]:
        needle = normalize_latin(query) if normalized else query.casefold()
        results = []
        for index, record in enumerate(self.records):
            haystack = record["normalized"] if normalized else record["text"].casefold()
            offset = haystack.find(needle)
            if offset >= 0:
                results.append(
                    self._contextual_result(
                        index,
                        {
                            "match": query,
                            "match_offset": offset,
                            "text": record["text"],
                            "provenance": record["provenance"],
                        },
                    )
                )
                if len(results) >= limit:
                    break
        return results

    def lemma(self, lemma: str, *, limit: int = 8) -> list[dict[str, Any]]:
        folded = lemma.casefold()
        results = []
        for index, record in enumerate(self.records):
            if folded not in record.get("lemmas", []):
                continue
            results.append(
                self._contextual_result(
                    index,
                    {
                        "lemma": lemma,
                        "text": record["text"],
                        "provenance": record["provenance"],
                    },
                )
            )
            if len(results) >= limit:
                break
        return results

    def semantic(self, query: str, *, limit: int = 8) -> list[dict[str, Any]]:
        """Compatibility-only TF-IDF diagnostic.

        Production `semantic_rag` requests use `LocalRetrievalIndex`, whose
        persisted vectors and digest are independently inspectable.
        """
        query_tokens = normalize_latin(query).split()
        if not query_tokens or not self.records:
            return []
        documents = [record["normalized"].split() for record in self.records]
        document_frequency = Counter(
            token for document in documents for token in set(document)
        )
        count = len(documents)

        def vector(tokens: list[str]) -> dict[str, float]:
            frequencies = Counter(tokens)
            return {
                token: frequency * (math.log((count + 1) / (document_frequency[token] + 1)) + 1)
                for token, frequency in frequencies.items()
            }

        query_vector = vector(query_tokens)
        query_norm = math.sqrt(sum(value * value for value in query_vector.values())) or 1.0
        scored = []
        for record, tokens in zip(self.records, documents):
            candidate = vector(tokens)
            candidate_norm = math.sqrt(sum(value * value for value in candidate.values())) or 1.0
            dot = sum(query_vector.get(token, 0.0) * value for token, value in candidate.items())
            score = dot / (query_norm * candidate_norm)
            if score > 0:
                scored.append((score, record))
        scored.sort(key=lambda item: (-item[0], item[1]["source_unit_id"]))
        return [
            {
                "score": round(score, 6),
                "text": record["text"],
                "provenance": record["provenance"],
            }
            for score, record in scored[:limit]
        ]


def roman_to_int(value: str) -> int:
    value = value.upper()
    if value.isdigit():
        return int(value)
    numerals = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
    total = 0
    previous = 0
    for char in reversed(value):
        current = numerals.get(char)
        if current is None:
            raise ValueError(f"Invalid Roman numeral: {value}")
        total += -current if current < previous else current
        previous = max(previous, current)
    return total


MANUAL_BOOK_ALIASES = {
    "psal": "Psalmi",
    "psalm": "Psalmi",
    "eccli": "Ecclesiasticus",
    "luc": "Lucas",
    "matth": "Matthaeus",
    "marc": "Marcus",
    "joan": "Joannes",
    "ioan": "Joannes",
    "genes": "Genesis",
    "num": "Numeri",
    "osee": "Osee",
    "isai": "Isaias",
    "jer": "Jeremias",
    "ez": "Ezechiel",
    "ezech": "Ezechiel",
    "dan": "Daniel",
    "iv reg": "Regum IV",
    "iii reg": "Regum III",
    "ii reg": "Regum II",
    "i reg": "Regum I",
    "ii par": "Paralipomenon II",
    "i par": "Paralipomenon I",
}


def _book_key(value: str) -> str:
    return " ".join(re.findall(r"[a-zivx]+", value.casefold().replace("j", "i")))


class ScriptureCorpus:
    def __init__(
        self,
        vulgate_path: Path,
        book_metadata_path: Path,
        cpdv_path: Path | None = None,
        odr_path: Path | None = None,
    ):
        self.rows: list[dict[str, Any]] = []
        self.by_reference: dict[tuple[str, int, int], dict[str, Any]] = {}
        self.aliases: dict[str, str] = {}
        with vulgate_path.open("r", encoding="utf-8") as handle:
            reader = csv.reader(handle, delimiter="\t")
            for row in reader:
                if len(row) < 6:
                    continue
                title, abbreviation, order, chapter, verse = row[:5]
                item = {
                    "book": title,
                    "abbreviation": abbreviation,
                    "order": int(order),
                    "chapter": int(chapter),
                    "verse": int(verse),
                    "latin": "\t".join(row[5:]),
                }
                reference_key = (title, int(chapter), int(verse))
                # The bundled TSV currently concatenates the canon more than
                # once. Treat identical reference rows as one verse while
                # retaining the local file itself as provenance.
                if reference_key in self.by_reference:
                    continue
                self.rows.append(item)
                self.by_reference[reference_key] = item
                self.aliases[_book_key(title)] = title
                self.aliases[_book_key(abbreviation)] = title
        if book_metadata_path.exists():
            with book_metadata_path.open("r", encoding="utf-8") as handle:
                for abbreviation, title, *_ in csv.reader(handle):
                    self.aliases[_book_key(abbreviation)] = title
                    self.aliases[_book_key(title)] = title
        for alias, title in MANUAL_BOOK_ALIASES.items():
            self.aliases[_book_key(alias)] = title
        self.cpdv: dict[tuple[int, int, int], str] = {}
        if cpdv_path and cpdv_path.exists():
            for path in cpdv_path.glob("*.json"):
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    order = int(data["book"]["order"])
                    for chapter in data.get("chapters", []):
                        for verse in chapter.get("verses", []):
                            self.cpdv[(order, int(chapter["chapter"]), int(verse["verse"]))] = verse["text"]
                except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                    continue
        self.odr: dict[tuple[int, int, int], str] = {}
        if odr_path and odr_path.exists():
            paths = (
                sorted(odr_path.glob("*.jsonl"))
                if odr_path.is_dir()
                else [odr_path]
            )
            for path in paths:
                try:
                    rows = _read_jsonl(path)
                except (OSError, ValueError, json.JSONDecodeError):
                    continue
                for row in rows:
                    try:
                        order = int(row.get("book_order", row.get("order")))
                        chapter = int(row["chapter"])
                        verse = int(row["verse"])
                        text = str(row["text"]).strip()
                    except (KeyError, TypeError, ValueError):
                        continue
                    if text:
                        self.odr[(order, chapter, verse)] = text

    def _parse_reference(self, reference: str) -> list[dict[str, Any]]:
        cleaned = reference.strip().strip("()[] ")
        results = []
        for segment in re.split(r"\s*;\s*", cleaned):
            match = re.match(
                r"^(?P<book>.+?)\s+(?P<chapter>[IVXLCDM]+|\d+)(?:\s*,\s*(?P<verse>[IVXLCDM]+|\d+))?\.?$",
                segment,
                flags=re.IGNORECASE,
            )
            if not match:
                results.append({"raw": segment, "status": "invalid_syntax"})
                continue
            book_key = _book_key(match.group("book").rstrip("."))
            title = self.aliases.get(book_key)
            if not title:
                results.append({"raw": segment, "status": "unknown_book", "book_key": book_key})
                continue
            try:
                chapter = roman_to_int(match.group("chapter"))
                verse = roman_to_int(match.group("verse")) if match.group("verse") else None
            except ValueError as exc:
                results.append({"raw": segment, "status": "invalid_numeral", "error": str(exc)})
                continue
            results.append({"raw": segment, "status": "parsed", "book": title, "chapter": chapter, "verse": verse})
        return results

    def lookup_reference(self, reference: str, *, limit: int = 8) -> dict[str, Any]:
        parsed = self._parse_reference(reference)
        verses: list[dict[str, Any]] = []
        for item in parsed:
            if item["status"] != "parsed":
                continue
            matches = [
                row
                for row in self.rows
                if row["book"] == item["book"]
                and row["chapter"] == item["chapter"]
                and (item["verse"] is None or row["verse"] == item["verse"])
            ]
            item["reference_exists"] = bool(matches)
            for row in matches[: max(0, limit - len(verses))]:
                copied = dict(row)
                copied["cpdv"] = self.cpdv.get((row["order"], row["chapter"], row["verse"]))
                copied["odr"] = self.odr.get(
                    (row["order"], row["chapter"], row["verse"])
                )
                copied["provenance"] = {
                    "latin_source": "Clementine Vulgate local TSV",
                    "english_comparison": "CPDV local public-domain corpus" if copied["cpdv"] else None,
                    "odr_comparison": (
                        "Configured ODR verse-comparison JSONL"
                        if copied["odr"]
                        else None
                    ),
                }
                verses.append(copied)
        parsed_references = [item for item in parsed if item.get("status") == "parsed"]
        all_references_exist = bool(parsed_references) and all(
            item.get("reference_exists") for item in parsed_references
        )
        return {
            "query": reference,
            "parsed": parsed,
            "reference_exists": any(item.get("reference_exists") for item in parsed_references),
            "source_annotation_verified": all_references_exist,
            "textual_match_verified": False,
            "verses": verses,
        }

    def search_phrase(self, phrase: str, *, limit: int = 8) -> list[dict[str, Any]]:
        needle = normalize_latin(phrase)
        if not needle:
            return []
        exact = []
        for row in self.rows:
            normalized = normalize_latin(row["latin"])
            if needle in normalized:
                copied = dict(row)
                copied["match_kind"] = "normalized_exact"
                copied["textual_match_verified"] = True
                copied["cpdv"] = self.cpdv.get((row["order"], row["chapter"], row["verse"]))
                copied["odr"] = self.odr.get(
                    (row["order"], row["chapter"], row["verse"])
                )
                exact.append(copied)
                if len(exact) >= limit:
                    break
        if exact:
            return exact
        # Near matches are candidates requiring interpretation, never silently
        # upgraded to verified quotation identity.
        query_tokens = needle.split()
        scored = []
        for row in self.rows:
            normalized = normalize_latin(row["latin"])
            verse_tokens = normalized.split()
            candidates = [normalized]
            if len(query_tokens) >= 2:
                for width in {
                    max(1, len(query_tokens) - 1),
                    len(query_tokens),
                    len(query_tokens) + 1,
                }:
                    candidates.extend(
                        " ".join(verse_tokens[start : start + width])
                        for start in range(
                            0, max(0, len(verse_tokens) - width + 1)
                        )
                    )
            matched, score = max(
                (
                    (
                        candidate,
                        difflib.SequenceMatcher(
                            None, needle, candidate
                        ).ratio(),
                    )
                    for candidate in candidates
                    if candidate
                ),
                key=lambda item: item[1],
                default=("", 0.0),
            )
            threshold = 0.72 if len(query_tokens) >= 2 else 0.82
            if score >= threshold:
                scored.append((score, matched, row))
        scored.sort(key=lambda item: (-item[0], item[2]["order"], item[2]["chapter"], item[2]["verse"]))
        results = []
        for score, matched, row in scored[:limit]:
            copied = dict(row)
            copied["match_kind"] = "normalized_near_candidate"
            copied["match_score"] = round(score, 4)
            copied["matched_latin"] = matched
            copied["textual_match_verified"] = False
            copied["cpdv"] = self.cpdv.get((row["order"], row["chapter"], row["verse"]))
            copied["odr"] = self.odr.get(
                (row["order"], row["chapter"], row["verse"])
            )
            results.append(copied)
        return results


class AuthorityIndex:
    """Inspectable project-local authority records; no model interpretation."""

    def __init__(self, path: Path, *, authority_kind: str):
        self.path = path
        self.authority_kind = authority_kind
        self.records = _read_jsonl(path)

    def search(self, query: str, *, limit: int = 8) -> list[dict[str, Any]]:
        def tokens(value: str) -> set[str]:
            return set(normalize_latin(value).split()) | set(
                re.findall(r"\d+", value)
            )

        query_tokens = tokens(query)
        if not query_tokens:
            return []
        scored: list[tuple[float, str, dict[str, Any]]] = []
        for index, record in enumerate(self.records):
            aliases = record.get("aliases", [])
            if isinstance(aliases, str):
                aliases = [aliases]
            searchable = " ".join(
                [
                    str(record.get("label", "")),
                    str(record.get("text", "")),
                    " ".join(str(item) for item in aliases),
                ]
            )
            record_tokens = tokens(searchable)
            overlap = len(query_tokens & record_tokens)
            if overlap:
                score = overlap / max(1, len(query_tokens | record_tokens))
                copied = dict(record)
                copied["authority_kind"] = self.authority_kind
                copied["authority_path"] = str(self.path)
                copied["match_score"] = round(score, 8)
                scored.append(
                    (
                        score,
                        str(record.get("entry_id", index)),
                        copied,
                    )
                )
        scored.sort(key=lambda item: (-item[0], item[1]))
        return [item[2] for item in scored[:limit]]


class ExternalResearchBackend(Protocol):
    backend_name: str

    def search(self, query: str, *, limit: int) -> list[dict[str, Any]]:
        ...


class EvidenceService:
    def __init__(
        self,
        config: PipelineConfig,
        *,
        lexicon: WhitakersWordsBackend,
        concordance: JeromeConcordance | None,
        scripture: ScriptureCorpus | None,
        retrieval: LocalRetrievalIndex | None = None,
        authorities: dict[str, AuthorityIndex] | None = None,
        web_backend: ExternalResearchBackend | None = None,
        canonical_manifest: dict[str, Any] | None = None,
        retrieval_freshness: dict[str, Any] | None = None,
    ):
        self.config = config
        self.lexicon = lexicon
        self.concordance = concordance
        self.scripture = scripture
        self.retrieval = retrieval
        self.authorities = authorities or {}
        self.web_backend = web_backend
        self.canonical_manifest = canonical_manifest or {}
        self.retrieval_freshness = retrieval_freshness or {
            "fresh": retrieval is not None,
            "status": "fresh" if retrieval is not None else "unavailable",
            "reasons": [],
        }

    def cache_identity(self) -> dict[str, Any]:
        def file_identity(path: Path) -> dict[str, Any]:
            if not path.exists():
                return {"path": str(path), "available": False}
            stat = path.stat()
            return {
                "path": str(path),
                "available": True,
                "bytes": stat.st_size,
                "modified_ns": stat.st_mtime_ns,
            }

        return {
            "service_version": EVIDENCE_SERVICE_VERSION,
            "lexicon": {
                "backend": self.lexicon.backend_name,
                "contract": self.lexicon.contract_version,
            },
            "canonical_source_digest": self.canonical_manifest.get(
                "canonical_source_digest"
            ),
            "concordance": (
                getattr(
                    self.concordance,
                    "identity",
                    file_identity(self.config.path_value("concordance")),
                )
                if self.concordance is not None
                else file_identity(self.config.path_value("concordance"))
            ),
            "retrieval_index": (
                {**self.retrieval.identity, "freshness": self.retrieval_freshness}
                if self.retrieval is not None
                else file_identity(self.config.path_value("retrieval_index"))
            ),
            "vulgate": file_identity(self.config.path_value("vulgate")),
            "cpdv_path": str(self.config.path_value("cpdv")),
            "odr": file_identity(self.config.path_value("odr")),
            "authorities": {
                kind: file_identity(authority.path)
                for kind, authority in sorted(self.authorities.items())
            },
            "web_backend": getattr(self.web_backend, "backend_name", None),
            "semantic_search_enabled": self.config.section("evidence").get(
                "semantic_search_enabled", True
            ),
            "external_web_enabled": self.config.section("evidence").get(
                "external_web_enabled", False
            ),
            "limits": {
                key: self.config.section("evidence").get(key)
                for key in (
                    "max_requests_per_round",
                    "max_results_per_request",
                    "snippet_chars",
                )
            },
            "adapter_contracts": self.config.section("research_adapters"),
        }

    @classmethod
    def from_config(cls, config: PipelineConfig, lexicon: WhitakersWordsBackend):
        expected_manifest = canonical_source_manifest(config)
        concordance_path = config.path_value("concordance")
        concordance = (
            JeromeConcordance(
                concordance_path, expected_manifest=expected_manifest
            )
            if concordance_path.exists()
            else None
        )
        retrieval_path = config.path_value("retrieval_index")
        try:
            retrieval = (
                LocalRetrievalIndex(retrieval_path)
                if retrieval_path.exists()
                else None
            )
        except (OSError, ValueError, KeyError, json.JSONDecodeError):
            retrieval = None
        retrieval_reasons: list[str] = []
        if retrieval is not None:
            if (
                retrieval.identity.get("canonical_source_digest")
                != expected_manifest.get("canonical_source_digest")
            ):
                retrieval_reasons.append("retrieval index canonical source digest is stale")
            if concordance is None or not concordance.freshness["fresh"]:
                retrieval_reasons.append("retrieval index depends on unavailable or stale concordance")
            elif (
                retrieval.identity.get("records_digest")
                != concordance.identity.get("records_digest")
            ):
                retrieval_reasons.append("retrieval index records digest differs from concordance")
        retrieval_freshness = {
            "fresh": retrieval is not None and not retrieval_reasons,
            "status": (
                "fresh"
                if retrieval is not None and not retrieval_reasons
                else "stale_evidence" if retrieval is not None else "unavailable"
            ),
            "reasons": retrieval_reasons,
        }
        try:
            scripture = ScriptureCorpus(
                config.path_value("vulgate"),
                config.path_value("vulgate_books"),
                config.path_value("cpdv"),
                config.path_value("odr"),
            )
        except (OSError, ValueError):
            scripture = None
        authorities: dict[str, AuthorityIndex] = {}
        for kind, path_key in (
            ("chronology", "chronology_authority"),
            ("proper_name", "proper_name_authority"),
            ("source_edition", "source_edition_authority"),
        ):
            path = config.path_value(path_key)
            if path.exists():
                try:
                    authorities[kind] = AuthorityIndex(
                        path, authority_kind=kind
                    )
                except (OSError, ValueError, json.JSONDecodeError):
                    pass
        return cls(
            config,
            lexicon=lexicon,
            concordance=concordance,
            scripture=scripture,
            retrieval=retrieval,
            authorities=authorities,
            canonical_manifest=expected_manifest,
            retrieval_freshness=retrieval_freshness,
        )

    def execute(
        self,
        request: dict[str, Any],
        *,
        requested_by: str,
        chunk: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        kind = str(request.get("kind", ""))
        query = str(request.get("query", ""))
        evidence_id = "ev-" + canonical_digest({"kind": kind, "query": query, "chunk": chunk and chunk.get("chunk_id")})[:14]
        base = {
            "evidence_id": evidence_id,
            "request": dict(request),
            "requested_by": requested_by,
            "retrieved_at": utc_now(),
            "source_annotation_verified": False,
            "textual_match_verified": False,
        }
        limit = max(
            0,
            int(
                self.config.section("evidence").get(
                    "max_results_per_request", 8
                )
            ),
        )
        snippet_chars = int(
            self.config.section("evidence").get("snippet_chars", 900)
        )

        def bounded(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
            return bound_evidence_results(
                results,
                query=query,
                snippet_chars=snippet_chars,
            )

        try:
            if kind in {"jerome_phrase", "jerome_lemma"}:
                if self.concordance is None:
                    return {**base, "status": "unavailable", "evidence_class": "retrieved_evidence", "results": [], "message": "Jerome concordance has not been built"}
                if not getattr(self.concordance, "freshness", {"fresh": True})["fresh"]:
                    return {
                        **base,
                        "status": "stale_evidence",
                        "evidence_class": "retrieved_evidence",
                        "results": [],
                        "message": "Jerome concordance does not match the configured canonical source; rebuild required",
                        "freshness": self.concordance.freshness,
                    }
                if kind == "jerome_phrase":
                    results = self.concordance.exact(query, normalized=False, limit=limit)
                    if not results:
                        results = self.concordance.exact(query, normalized=True, limit=limit)
                elif kind == "jerome_lemma":
                    results = self.concordance.lemma(query, limit=limit)
                return {**base, "status": "found" if results else "no_evidence_found", "evidence_class": "retrieved_evidence", "results": bounded(results)}
            if kind in {"semantic_rag", "corpus_related"}:
                if not self.config.section("evidence").get(
                    "semantic_search_enabled", True
                ):
                    return {**base, "status": "unavailable", "evidence_class": "retrieved_evidence", "results": [], "message": "Local retrieval is disabled"}
                if self.retrieval is None:
                    return {
                        **base,
                        "status": "unavailable",
                        "evidence_class": "retrieved_evidence",
                        "results": [],
                        "message": (
                            "Persisted local retrieval index is unavailable; "
                            "run build-retrieval-index"
                        ),
                    }
                if not self.retrieval_freshness["fresh"]:
                    return {
                        **base,
                        "status": "stale_evidence",
                        "evidence_class": "retrieved_evidence",
                        "results": [],
                        "message": "Local retrieval index does not match the current concordance/canonical source; rebuild required",
                        "freshness": self.retrieval_freshness,
                    }
                results = self.retrieval.search(query, limit=limit)
                return {
                    **base,
                    "status": "found" if results else "no_evidence_found",
                    "evidence_class": "retrieved_evidence",
                    "retrieval_method": self.retrieval.identity,
                    "results": bounded(results),
                }
            if kind == "scripture":
                if self.scripture is None:
                    return {**base, "status": "unavailable", "evidence_class": "verified_evidence", "results": [], "message": "Local Scripture corpus unavailable"}
                lookup = self.scripture.lookup_reference(query, limit=limit)
                if lookup["reference_exists"]:
                    return {**base, "status": "found", "evidence_class": "verified_evidence", "source_annotation_verified": lookup["source_annotation_verified"], "textual_match_verified": False, "results": bounded(lookup["verses"]), "parsed": lookup["parsed"]}
                phrase = self.scripture.search_phrase(query, limit=limit)
                exact_match = any(
                    item.get("textual_match_verified") is True for item in phrase
                )
                return {**base, "status": "found" if phrase else "no_evidence_found", "evidence_class": "verified_evidence" if exact_match else "retrieved_evidence", "textual_match_verified": exact_match, "results": bounded(phrase), "parsed": lookup["parsed"]}
            if kind in {"glossary", "morphology"}:
                tokens = [token for token, _ in tokenize_with_offsets(query)]
                results = [analysis_to_json(self.lexicon.analyze_word(token.casefold())) for token in tokens[:limit]]
                return {**base, "status": "found" if any(item["found"] for item in results) else "no_evidence_found", "evidence_class": "verified_evidence", "results": bounded(results), "provenance": {"backend": self.lexicon.backend_name, "contract": self.lexicon.contract_version}}
            if kind == "source_edition":
                annotations = chunk.get("annotations", []) if chunk else []
                matches = [item for item in annotations if query.casefold() in json.dumps(item, ensure_ascii=False).casefold()]
                authority = self.authorities.get("source_edition")
                authority_matches = (
                    authority.search(query, limit=limit) if authority else []
                )
                results = [
                    {**item, "result_class": "source_annotation"}
                    for item in matches
                ] + [
                    {**item, "result_class": "configured_source_edition"}
                    for item in authority_matches
                ]
                if not results and authority is None and not annotations:
                    return {**base, "status": "unavailable", "evidence_class": "retrieved_evidence", "results": [], "message": "No source-edition authority or chunk annotations are available"}
                return {**base, "status": "found" if results else "no_evidence_found", "evidence_class": "retrieved_evidence", "results": bounded(results)}
            if kind == "web_research":
                if not self.config.section("evidence").get(
                    "external_web_enabled", False
                ):
                    return {**base, "status": "unavailable", "evidence_class": "research_lead", "results": [], "message": "Optional web research is disabled"}
                if self.web_backend is None:
                    return {**base, "status": "unavailable", "evidence_class": "research_lead", "results": [], "message": "Web research is enabled but no backend is configured"}
                leads = self.web_backend.search(query, limit=limit)
                leads = [
                    {
                        **lead,
                        "result_class": "research_lead",
                        "verified_evidence": False,
                        "backend": self.web_backend.backend_name,
                    }
                    for lead in leads
                ]
                return {**base, "status": "found" if leads else "no_evidence_found", "evidence_class": "research_lead", "results": bounded(leads), "message": "External results are leads only and require primary-source verification"}
            if kind in {"chronology", "proper_name"}:
                authority = self.authorities.get(kind)
                if authority is None:
                    return {**base, "status": "unavailable", "evidence_class": "retrieved_evidence", "results": [], "message": f"No deterministic local {kind} authority is configured"}
                results = authority.search(query, limit=limit)
                return {**base, "status": "found" if results else "no_evidence_found", "evidence_class": "retrieved_evidence", "results": bounded(results)}
            return {**base, "status": "invalid_request", "evidence_class": "none", "results": [], "message": f"Unsupported evidence kind: {kind}"}
        except Exception as exc:
            return {**base, "status": "error", "evidence_class": "none", "results": [], "message": str(exc)}

    def execute_many(
        self,
        requests: list[dict[str, Any]],
        *,
        requested_by: str,
        chunk: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        maximum = max(
            0,
            int(
                self.config.section("evidence").get(
                    "max_requests_per_round", 6
                )
            ),
        )
        return [
            self.execute(request, requested_by=requested_by, chunk=chunk)
            for request in requests[:maximum]
        ]

    def execute_round(
        self,
        requests: list[dict[str, Any]],
        *,
        requested_by: str,
        chunk: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        maximum = max(
            0,
            int(
                self.config.section("evidence").get(
                    "max_requests_per_round", 6
                )
            ),
        )
        executed = requests[:maximum]
        return {
            "requests": requests,
            "request_limit": maximum,
            "executed_requests": executed,
            "omitted_requests_count": max(0, len(requests) - len(executed)),
            "evidence": [
                self.execute(request, requested_by=requested_by, chunk=chunk)
                for request in executed
            ],
        }
