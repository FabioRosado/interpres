from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


TERMINAL_STATUSES = {"complete", "failed", "unavailable", "incomplete"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def canonical_digest(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class StageCache:
    """Boring, inspectable, content-addressed JSON stage cache."""

    def __init__(self, root: Path):
        self.root = root

    def key(
        self,
        *,
        stage: str,
        chunk: dict[str, Any],
        pipeline_version: str,
        schema_version: int,
        prompt_version: str,
        inputs: Any,
        dependencies: Iterable[dict[str, Any]] = (),
        model: dict[str, Any] | None = None,
    ) -> tuple[str, dict[str, Any]]:
        material = {
            "stage": stage,
            "chunk_id": chunk["chunk_id"],
            "source_fingerprint": chunk["source_fingerprint"],
            "pipeline_version": pipeline_version,
            "schema_version": schema_version,
            "prompt_version": prompt_version,
            "inputs": inputs,
            "dependencies": [
                {
                    "stage": item.get("stage"),
                    "cache_key": item.get("cache_key"),
                    "status": item.get("status"),
                    # A forced stochastic rerun can keep the same input key but
                    # produce a different output. Downstream cache identity
                    # must notice that without destroying the archived attempt.
                    "output_digest": canonical_digest(item.get("output")),
                }
                for item in dependencies
            ],
            "model": model,
        }
        return canonical_digest(material), material

    def path(self, stage: str, chunk_id: str, key: str) -> Path:
        safe_chunk = chunk_id.replace("/", "_").replace("\\", "_")
        return self.root / "stages" / stage / safe_chunk / f"{key}.json"

    def load(self, stage: str, chunk_id: str, key: str) -> dict[str, Any] | None:
        path = self.path(stage, chunk_id, key)
        if not path.exists():
            return None
        with path.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
        if not isinstance(value, dict):
            raise ValueError(f"Stage cache record is not an object: {path}")
        return value

    def save(self, record: dict[str, Any], *, preserve_existing: bool = True) -> Path:
        status = record.get("status")
        if status not in TERMINAL_STATUSES:
            raise ValueError(f"Invalid terminal stage status: {status!r}")
        path = self.path(record["stage"], record["chunk_id"], record["cache_key"])
        path.parent.mkdir(parents=True, exist_ok=True)
        if preserve_existing and path.exists():
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            archived = path.with_name(f"{path.stem}.attempt-{stamp}.json")
            path.replace(archived)
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(record, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)
        return path

    def inspect(
        self,
        *,
        chunk_id: str | None = None,
        stage: str | None = None,
        include_attempts: bool = False,
    ) -> list[dict[str, Any]]:
        stage_root = self.root / "stages"
        if not stage_root.exists():
            return []
        paths = (
            [stage_root / stage] if stage else [item for item in stage_root.iterdir() if item.is_dir()]
        )
        results: list[dict[str, Any]] = []
        for current_stage in paths:
            if not current_stage.exists():
                continue
            for path in current_stage.rglob("*.json"):
                if ".attempt-" in path.name and not include_attempts:
                    continue
                try:
                    value = json.loads(path.read_text(encoding="utf-8"))
                except Exception as exc:
                    results.append(
                        {
                            "stage": current_stage.name,
                            "path": str(path),
                            "status": "cache_read_error",
                            "error": str(exc),
                        }
                    )
                    continue
                if chunk_id and value.get("chunk_id") != chunk_id:
                    continue
                if ".attempt-" in path.name:
                    value["archived_attempt_path"] = str(path)
                results.append(value)
        return sorted(results, key=lambda item: (item.get("chunk_id", ""), item.get("stage", "")))


def stage_record(
    *,
    stage: str,
    chunk_id: str,
    cache_key: str,
    cache_material: dict[str, Any],
    pipeline_version: str,
    schema_version: int,
    prompt_version: str,
    status: str,
    started_at: str,
    output: Any = None,
    raw_response: str | None = None,
    error: dict[str, Any] | None = None,
    model: dict[str, Any] | None = None,
    provider_attempts: list[dict[str, Any]] | None = None,
    provenance: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": schema_version,
        "pipeline_version": pipeline_version,
        "prompt_version": prompt_version,
        "stage": stage,
        "chunk_id": chunk_id,
        "cache_key": cache_key,
        "input_digest": canonical_digest(cache_material.get("inputs")),
        "cache_material": cache_material,
        "status": status,
        "started_at": started_at,
        "finished_at": utc_now(),
        "model": model,
        "provider_attempts": provider_attempts or [],
        "output": output,
        "raw_response": raw_response,
        "error": error,
        "provenance": provenance or [],
    }
