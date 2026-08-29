from __future__ import annotations

import json
import re
import threading
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .cache import canonical_digest, utc_now
from .evidence import normalize_latin

EDITORIAL_REVISION_SCHEMA_VERSION = "jerome-editorial-revision-v1"
EDITORIAL_MEMORY_POLICY_VERSION = 1
SAFE_CHUNK_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$")
REVISION_STATES = {"draft", "approved"}
RESOLUTION_OUTCOMES = {"resolved", "accepted_as_is", "deferred"}
CONTENT_FORMATS = {"plain_text", "markdown"}
ANNOTATION_KINDS = {
    "editorial_note",
    "translation_decision",
    "context_note",
    "scripture_reference",
    "lexical_note",
    "todo",
}
SAFE_ANNOTATION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")


class EditorialRevisionError(ValueError):
    """Raised when an editorial revision does not satisfy the save contract."""


class EditorialRevisionConflict(EditorialRevisionError):
    """Raised when a save is based on stale machine or editorial state."""


def text_digest(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    return canonical_digest({"text": value})


def _safe_chunk_id(chunk_id: str) -> str:
    if not SAFE_CHUNK_ID.fullmatch(chunk_id):
        raise EditorialRevisionError("Chunk ID is not safe for editorial storage")
    return chunk_id


def _read_revision(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict):
        return None
    if value.get("schema_version") != EDITORIAL_REVISION_SCHEMA_VERSION:
        return None
    return value


def _summary(revision: dict[str, Any]) -> dict[str, Any]:
    editorial = revision.get("editorial", {})
    resolutions = editorial.get("issue_resolutions", [])
    if not isinstance(resolutions, list):
        resolutions = []
    reusable = [
        item
        for item in resolutions
        if isinstance(item, dict)
        and item.get("outcome") == "resolved"
        and item.get("reusable") is True
    ]
    return {
        "revision_id": revision.get("revision_id"),
        "revision_number": revision.get("revision_number"),
        "created_at": revision.get("created_at"),
        "state": editorial.get("state"),
        "translation_digest": editorial.get("translation_digest"),
        "content_format": editorial.get("content_format", "plain_text"),
        "annotation_count": len(editorial.get("annotations", []))
        if isinstance(editorial.get("annotations", []), list)
        else 0,
        "resolution_count": len(resolutions) if isinstance(resolutions, list) else 0,
        "reusable_resolution_count": len(reusable),
        "machine_final_digest": revision.get("machine", {}).get(
            "final_draft_digest"
        ),
    }


def _annotation_span_status(annotation: dict[str, Any], translation: str) -> str:
    target = annotation.get("target", {})
    if not isinstance(target, dict):
        return "stale"
    start = target.get("start")
    end = target.get("end")
    selected_text = target.get("selected_text")
    if (
        not isinstance(start, int)
        or isinstance(start, bool)
        or not isinstance(end, int)
        or isinstance(end, bool)
        or not isinstance(selected_text, str)
        or start < 0
        or end <= start
        or end > len(translation)
    ):
        return "stale"
    return "valid" if translation[start:end] == selected_text else "stale"


def _resolved_revision(revision: dict[str, Any] | None) -> dict[str, Any] | None:
    """Return a UI-safe legacy-compatible view without rewriting the record."""

    if revision is None:
        return None
    resolved = {**revision}
    editorial = dict(revision.get("editorial", {}))
    translation = editorial.get("translation")
    if not isinstance(translation, str):
        translation = ""
    editorial["content_format"] = (
        editorial.get("content_format")
        if editorial.get("content_format") in CONTENT_FORMATS
        else "plain_text"
    )
    annotations = editorial.get("annotations", [])
    if not isinstance(annotations, list):
        annotations = []
    editorial["annotations"] = [
        {**item, "span_status": _annotation_span_status(item, translation)}
        for item in annotations
        if isinstance(item, dict)
    ]
    resolved["editorial"] = editorial
    return resolved


def _validate_annotations(
    raw_annotations: Any,
    *,
    translation: str,
    created_at: str,
) -> list[dict[str, Any]]:
    if not isinstance(raw_annotations, list) or len(raw_annotations) > 500:
        raise EditorialRevisionError("annotations must be a bounded list")
    annotations: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in raw_annotations:
        if not isinstance(raw, dict):
            raise EditorialRevisionError("Every annotation must be an object")
        annotation_id = str(raw.get("annotation_id") or "")
        if not SAFE_ANNOTATION_ID.fullmatch(annotation_id):
            raise EditorialRevisionError("Annotation IDs must be stable safe identifiers")
        if annotation_id in seen:
            raise EditorialRevisionError(f"Duplicate annotation_id: {annotation_id}")
        seen.add(annotation_id)
        kind = raw.get("kind")
        if kind not in ANNOTATION_KINDS:
            raise EditorialRevisionError(f"Invalid annotation kind: {kind!r}")
        text = raw.get("text")
        if not isinstance(text, str) or not text.strip() or len(text) > 20_000:
            raise EditorialRevisionError(f"Invalid annotation text: {annotation_id}")
        target = raw.get("target")
        if not isinstance(target, dict) or target.get("surface") != "editorial":
            raise EditorialRevisionError(
                f"Annotation {annotation_id} must target the editorial surface"
            )
        start = target.get("start")
        end = target.get("end")
        selected_text = target.get("selected_text")
        if (
            not isinstance(start, int)
            or isinstance(start, bool)
            or not isinstance(end, int)
            or isinstance(end, bool)
            or start < 0
            or end <= start
            or not isinstance(selected_text, str)
            or not selected_text
            or len(selected_text) > 50_000
        ):
            raise EditorialRevisionError(f"Invalid annotation target: {annotation_id}")
        source_unit_ids = raw.get("source_unit_ids", [])
        if (
            not isinstance(source_unit_ids, list)
            or len(source_unit_ids) > 100
            or not all(isinstance(item, str) for item in source_unit_ids)
        ):
            raise EditorialRevisionError(
                f"Invalid annotation source_unit_ids: {annotation_id}"
            )
        created = raw.get("created_at") or created_at
        updated = raw.get("updated_at") or created_at
        if not isinstance(created, str) or not isinstance(updated, str):
            raise EditorialRevisionError(
                f"Invalid annotation timestamps: {annotation_id}"
            )
        normalized = {
            "annotation_id": annotation_id,
            "kind": kind,
            "text": text.strip(),
            "target": {
                "surface": "editorial",
                "start": start,
                "end": end,
                "selected_text": selected_text,
            },
            "source_unit_ids": list(dict.fromkeys(source_unit_ids)),
            "created_at": created,
            "updated_at": updated,
        }
        normalized["span_status"] = _annotation_span_status(normalized, translation)
        annotations.append(normalized)
    return annotations


@dataclass
class EditorialRevisionStore:
    """Append-only editorial revisions kept outside immutable machine artifacts."""

    root: Path

    def __post_init__(self) -> None:
        self._lock = threading.RLock()

    def chunk_path(self, book: int, chunk_id: str) -> Path:
        return self.root / f"book{int(book):02d}" / _safe_chunk_id(chunk_id)

    def revisions(self, book: int, chunk_id: str) -> list[dict[str, Any]]:
        directory = self.chunk_path(book, chunk_id)
        if not directory.exists():
            return []
        values = [
            value
            for path in sorted(directory.glob("revision-*.json"))
            if (value := _read_revision(path)) is not None
            and value.get("chunk_id") == chunk_id
            and int(value.get("book", -1)) == int(book)
        ]
        return sorted(
            values,
            key=lambda item: (
                int(item.get("revision_number", 0)),
                str(item.get("created_at", "")),
                str(item.get("revision_id", "")),
            ),
        )

    def all_revisions(self, *, book: int | None = None) -> list[dict[str, Any]]:
        if not self.root.exists():
            return []
        values = []
        for path in sorted(self.root.glob("book*/**/revision-*.json")):
            revision = _read_revision(path)
            if not revision:
                continue
            try:
                revision_book = int(revision.get("book"))
            except (TypeError, ValueError):
                continue
            if book is not None and revision_book != int(book):
                continue
            chunk_id = str(revision.get("chunk_id") or "")
            try:
                _safe_chunk_id(chunk_id)
            except EditorialRevisionError:
                continue
            values.append(revision)
        return sorted(
            values,
            key=lambda item: (
                int(item.get("book", 0)),
                str(item.get("chunk_id", "")),
                int(item.get("revision_number", 0)),
                str(item.get("created_at", "")),
                str(item.get("revision_id", "")),
            ),
        )

    def export_package(self, *, book: int | None = None) -> dict[str, Any]:
        revisions = self.all_revisions(book=book)
        return {
            "schema_version": "interpres-editorial-export-v1",
            "revision_schema_version": EDITORIAL_REVISION_SCHEMA_VERSION,
            "generated_at": utc_now(),
            "book": int(book) if book is not None else None,
            "revision_count": len(revisions),
            "revisions": revisions,
        }

    def import_package(
        self,
        package: dict[str, Any],
        *,
        book: int | None = None,
    ) -> dict[str, Any]:
        if not isinstance(package, dict):
            raise EditorialRevisionError("Import body must be an object")
        if package.get("schema_version") != "interpres-editorial-export-v1":
            raise EditorialRevisionError("Unsupported editorial export schema")
        revisions = package.get("revisions")
        if not isinstance(revisions, list) or len(revisions) > 10_000:
            raise EditorialRevisionError("Import revisions must be a bounded list")
        imported = 0
        skipped = 0
        errors: list[dict[str, Any]] = []
        with self._lock:
            existing_ids = {
                str(item.get("revision_id"))
                for item in self.all_revisions(book=book)
                if item.get("revision_id")
            }
            for index, raw in enumerate(revisions):
                if not isinstance(raw, dict):
                    errors.append({"index": index, "message": "revision must be an object"})
                    continue
                if raw.get("schema_version") != EDITORIAL_REVISION_SCHEMA_VERSION:
                    errors.append({"index": index, "message": "unsupported revision schema"})
                    continue
                try:
                    revision_book = int(raw.get("book"))
                    if book is not None and revision_book != int(book):
                        skipped += 1
                        continue
                    chunk_id = _safe_chunk_id(str(raw.get("chunk_id") or ""))
                    revision_id = str(raw.get("revision_id") or "")
                    revision_number = int(raw.get("revision_number", 0))
                    created_at = str(raw.get("created_at") or "")
                    if (
                        not revision_id.startswith("editorial-")
                        or revision_number < 1
                        or not created_at
                        or not isinstance(raw.get("machine"), dict)
                        or not isinstance(raw.get("editorial"), dict)
                    ):
                        raise EditorialRevisionError("invalid revision record")
                except (TypeError, ValueError, EditorialRevisionError) as exc:
                    errors.append({"index": index, "message": str(exc)})
                    continue
                if revision_id in existing_ids:
                    skipped += 1
                    continue
                directory = self.chunk_path(revision_book, chunk_id)
                directory.mkdir(parents=True, exist_ok=True)
                stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
                path = directory / (
                    f"revision-{revision_number:06d}-{stamp}-{revision_id}.json"
                )
                try:
                    with path.open("x", encoding="utf-8", newline="\n") as handle:
                        json.dump(raw, handle, ensure_ascii=False, indent=2)
                        handle.write("\n")
                except FileExistsError:
                    skipped += 1
                    continue
                existing_ids.add(revision_id)
                imported += 1
        return {
            "imported": imported,
            "skipped": skipped,
            "errors": errors,
            "revision_count": len(revisions),
        }

    def latest(self, book: int, chunk_id: str) -> dict[str, Any] | None:
        values = self.revisions(book, chunk_id)
        return values[-1] if values else None

    def state(
        self,
        book: int,
        chunk_id: str,
        *,
        machine_final_digest: str | None,
    ) -> dict[str, Any]:
        values = self.revisions(book, chunk_id)
        latest = _resolved_revision(values[-1]) if values else None
        return {
            "schema_version": EDITORIAL_REVISION_SCHEMA_VERSION,
            "storage_mode": "append_only_files",
            "machine_artifacts_immutable": True,
            "latest": latest,
            "history": [_summary(item) for item in reversed(values)],
            "revision_count": len(values),
            "based_on_current_machine_final": bool(
                latest
                and latest.get("machine", {}).get("final_draft_digest")
                == machine_final_digest
            ),
        }

    def save(
        self,
        *,
        book: int,
        chunk_id: str,
        payload: dict[str, Any],
        machine: dict[str, Any],
        issues: Iterable[dict[str, Any]],
    ) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise EditorialRevisionError("Editorial save body must be an object")
        machine_digest = machine.get("final_draft_digest")
        machine_draft = machine.get("final_draft")
        if not isinstance(machine_digest, str) or not isinstance(machine_draft, str):
            raise EditorialRevisionError(
                "A complete immutable machine final is required before editing"
            )
        supplied_machine_digest = payload.get("machine_final_digest")
        if supplied_machine_digest != machine_digest:
            raise EditorialRevisionConflict(
                "The machine final changed; reload the chunk before saving"
            )

        editorial_state = payload.get("state")
        if editorial_state not in REVISION_STATES:
            raise EditorialRevisionError("state must be draft or approved")
        translation = payload.get("translation")
        if not isinstance(translation, str) or not translation.strip():
            raise EditorialRevisionError("Editorial translation cannot be empty")
        if len(translation) > 250_000:
            raise EditorialRevisionError("Editorial translation is too large")
        content_format = payload.get("content_format", "plain_text")
        if content_format not in CONTENT_FORMATS:
            raise EditorialRevisionError("content_format must be plain_text or markdown")

        issue_by_id = {
            str(item.get("issue_id")): item
            for item in issues
            if isinstance(item, dict) and item.get("issue_id")
        }
        raw_resolutions = payload.get("issue_resolutions", [])
        if not isinstance(raw_resolutions, list) or len(raw_resolutions) > 500:
            raise EditorialRevisionError("issue_resolutions must be a bounded list")
        resolutions: list[dict[str, Any]] = []
        seen: set[str] = set()
        for raw in raw_resolutions:
            if not isinstance(raw, dict):
                raise EditorialRevisionError("Every issue resolution must be an object")
            issue_id = str(raw.get("issue_id") or "")
            if not issue_id or issue_id not in issue_by_id:
                raise EditorialRevisionError(f"Unknown issue_id: {issue_id or '[empty]'}")
            if issue_id in seen:
                raise EditorialRevisionError(f"Duplicate issue_id: {issue_id}")
            seen.add(issue_id)
            outcome = raw.get("outcome")
            if outcome not in RESOLUTION_OUTCOMES:
                raise EditorialRevisionError(
                    f"Invalid outcome for {issue_id}: {outcome!r}"
                )
            note = raw.get("note", "")
            if not isinstance(note, str) or len(note) > 20_000:
                raise EditorialRevisionError(f"Invalid note for {issue_id}")
            reusable = raw.get("reusable") is True
            approved_english = raw.get("approved_english")
            if approved_english is not None and not isinstance(approved_english, str):
                raise EditorialRevisionError(
                    f"approved_english must be text for {issue_id}"
                )
            approved_english = (approved_english or "").strip() or None
            source_issue = issue_by_id[issue_id]
            latin = str(source_issue.get("latin") or "").strip() or None
            if reusable and (
                outcome != "resolved" or not latin or not approved_english
            ):
                raise EditorialRevisionError(
                    "Reusable precedent requires a resolved issue, exact Latin, "
                    f"and approved English ({issue_id})"
                )
            resolutions.append(
                {
                    "issue_id": issue_id,
                    "origin": source_issue.get("origin"),
                    "type": source_issue.get("type"),
                    "source_unit_ids": source_issue.get("source_unit_ids", []),
                    "latin": latin,
                    "outcome": outcome,
                    "note": note.strip(),
                    "reusable": reusable,
                    "approved_english": approved_english,
                }
            )

        with self._lock:
            previous = self.latest(book, chunk_id)
            expected_base = previous.get("revision_id") if previous else None
            supplied_base = payload.get("base_revision_id")
            if supplied_base != expected_base:
                raise EditorialRevisionConflict(
                    "A newer editorial revision exists; reload before saving"
                )
            revision_number = int(previous.get("revision_number", 0)) + 1 if previous else 1
            created_at = utc_now()
            annotations = _validate_annotations(
                payload.get("annotations", []),
                translation=translation,
                created_at=created_at,
            )
            identity = {
                "book": int(book),
                "chunk_id": chunk_id,
                "revision_number": revision_number,
                "created_at": created_at,
                "base_revision_id": supplied_base,
                "translation_digest": text_digest(translation),
                "content_format": content_format,
                "annotations": annotations,
                "resolutions": resolutions,
            }
            revision_id = f"editorial-{canonical_digest(identity)[:16]}"
            revision = {
                "schema_version": EDITORIAL_REVISION_SCHEMA_VERSION,
                "revision_id": revision_id,
                "revision_number": revision_number,
                "created_at": created_at,
                "book": int(book),
                "chunk_id": chunk_id,
                "base_revision_id": supplied_base,
                "machine": {
                    **machine,
                    "immutable": True,
                },
                "editorial": {
                    "state": editorial_state,
                    "translation": translation,
                    "translation_digest": text_digest(translation),
                    "content_format": content_format,
                    "annotations": annotations,
                    "issue_resolutions": resolutions,
                },
            }
            directory = self.chunk_path(book, chunk_id)
            directory.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            path = directory / f"revision-{revision_number:06d}-{stamp}-{revision_id}.json"
            with path.open("x", encoding="utf-8", newline="\n") as handle:
                json.dump(revision, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
            return revision


class EditorialMemoryIndex:
    """Human-approved project precedent, kept distinct from source evidence."""

    def __init__(self, root: Path):
        self.root = root

    def _approved_precedents(self) -> list[dict[str, Any]]:
        latest_by_issue: dict[tuple[int, str, str], dict[str, Any]] = {}
        if not self.root.exists():
            return []
        for path in sorted(self.root.glob("book*/**/revision-*.json")):
            revision = _read_revision(path)
            if not revision:
                continue
            editorial = revision.get("editorial", {})
            if editorial.get("state") != "approved":
                continue
            try:
                book = int(revision.get("book"))
            except (TypeError, ValueError):
                continue
            chunk_id = str(revision.get("chunk_id") or "")
            revision_number = int(revision.get("revision_number", 0))
            for item in editorial.get("issue_resolutions", []):
                if not isinstance(item, dict) or not item.get("issue_id"):
                    continue
                key = (book, chunk_id, str(item["issue_id"]))
                candidate = {
                    "book": book,
                    "chunk_id": chunk_id,
                    "issue_id": str(item["issue_id"]),
                    "revision_id": revision.get("revision_id"),
                    "revision_number": revision_number,
                    "approved_at": revision.get("created_at"),
                    "latin": item.get("latin"),
                    "normalized_latin": normalize_latin(str(item.get("latin") or "")),
                    "approved_english": item.get("approved_english"),
                    "note": item.get("note"),
                    "origin": item.get("origin"),
                    "type": item.get("type"),
                    "source_unit_ids": item.get("source_unit_ids", []),
                    "outcome": item.get("outcome"),
                    "reusable": item.get("reusable") is True,
                }
                current = latest_by_issue.get(key)
                if current is None or (
                    revision_number,
                    str(candidate.get("approved_at") or ""),
                    str(candidate.get("revision_id") or ""),
                ) > (
                    int(current.get("revision_number", 0)),
                    str(current.get("approved_at") or ""),
                    str(current.get("revision_id") or ""),
                ):
                    latest_by_issue[key] = candidate
        return sorted(
            [
                item
                for item in latest_by_issue.values()
                if item.get("outcome") == "resolved"
                and item.get("reusable") is True
                and item.get("normalized_latin")
                and item.get("approved_english")
            ],
            key=lambda item: (
                str(item.get("normalized_latin")),
                int(item.get("book", 0)),
                str(item.get("chunk_id")),
                str(item.get("issue_id")),
            ),
        )

    def cache_identity(self) -> dict[str, Any]:
        precedents = self._approved_precedents()
        return {
            "policy_version": EDITORIAL_MEMORY_POLICY_VERSION,
            "schema_version": EDITORIAL_REVISION_SCHEMA_VERSION,
            "approved_precedent_count": len(precedents),
            "approved_precedent_digest": canonical_digest(precedents),
        }

    def match(self, target_latin: str) -> list[dict[str, Any]]:
        normalized_target = normalize_latin(target_latin)
        bounded_target = f" {normalized_target} "
        matches = []
        for item in self._approved_precedents():
            phrase = item["normalized_latin"]
            if f" {phrase} " not in bounded_target:
                continue
            matches.append(
                {
                    "precedent_id": f"precedent-{canonical_digest(item)[:14]}",
                    "evidence_class": "editorial_precedent",
                    "latin": item.get("latin"),
                    "approved_english": item.get("approved_english"),
                    "note": item.get("note"),
                    "type": item.get("type"),
                    "source": {
                        "book": item.get("book"),
                        "chunk_id": item.get("chunk_id"),
                        "issue_id": item.get("issue_id"),
                        "revision_id": item.get("revision_id"),
                        "approved_at": item.get("approved_at"),
                    },
                    "limits": (
                        "Human-approved project wording; it guides consistency "
                        "but is not lexical, manuscript, or corpus proof."
                    ),
                }
            )
        return matches
