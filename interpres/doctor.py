"""Environment and project diagnostics for Interpres."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from .config import PipelineConfig, load_config


def _check(name: str, ok: bool, detail: str = "") -> dict[str, Any]:
    return {"check": name, "ok": ok, "detail": detail}


def _json(value: Any) -> None:
    print(json.dumps(value, indent=2, ensure_ascii=False))


def run_doctor(config: PipelineConfig) -> int:
    root = config.root
    checks: list[dict[str, Any]] = []

    # 1. Python version
    version = sys.version_info
    checks.append(_check(
        "python_version",
        version >= (3, 9),
        f"{version.major}.{version.minor}.{version.micro}",
    ))

    # 2. whitakers_words availability (optional but required for morphology)
    try:
        from whitakers_words.parser import Parser  # noqa: F401
        checks.append(_check("whitakers_words", True, "imports successfully"))
    except Exception as exc:
        checks.append(_check("whitakers_words", False, f"not available: {exc}"))

    # 3. Source files for configured books
    for book_str, source_path in config.data.get("source", {}).get("books", {}).items():
        path = Path(source_path)
        if not path.is_absolute():
            path = root / path
        checks.append(_check(
            f"source_book_{book_str}",
            path.exists(),
            str(path),
        ))

    # 4. Corpus corpora / vulgate
    vulgate = config.path_value("vulgate")
    checks.append(_check("vulgate_tsv", vulgate.exists(), str(vulgate)))

    # 5. CPDV (optional)
    cpcdv_path = config.path_value("cpdv")
    checks.append(_check(
        "cpdv_corpus",
        cpcdv_path.exists() and any(cpcdv_path.iterdir()),
        str(cpcdv_path),
    ))

    # 6. Artifacts directory
    artifacts = config.path_value("artifacts")
    checks.append(_check("artifacts_dir", artifacts.exists(), str(artifacts)))

    # 7. Cache directory
    cache = config.path_value("cache")
    checks.append(_check("cache_dir", cache.exists(), str(cache)))

    # 8. Concordance freshness
    concordance = config.path_value("concordance")
    if concordance.exists():
        checks.append(_check("concordance", True, str(concordance)))
    else:
        checks.append(_check("concordance", False, "run build-concordance first"))

    # 9. Retrieval index freshness
    retrieval = config.path_value("retrieval_index")
    if retrieval.exists():
        checks.append(_check("retrieval_index", True, str(retrieval)))
    else:
        checks.append(_check("retrieval_index", False, "run build-retrieval-index first"))

    # 10. OPENROUTER_API_KEY (optional)
    api_key = os.environ.get("OPENROUTER_API_KEY")
    checks.append(_check(
        "openrouter_api_key",
        bool(api_key),
        "set" if api_key else "not set (optional)",
    ))

    failed = [c for c in checks if not c["ok"]]
    result = {"ok": not failed, "checks": checks}
    _json(result)
    return 0 if not failed else 1


if __name__ == "__main__":
    config = load_config()
    raise SystemExit(run_doctor(config))
