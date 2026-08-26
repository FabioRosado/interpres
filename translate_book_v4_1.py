"""Compatibility entry point for the refactored evidence-first pipeline.

New usage is subcommand based; run ``python translate_book_v4_1.py --help``.
The old ``--phase`` spelling remains mapped to the nearest auditable stage so
existing developer commands do not silently execute the abandoned v4.1 code.
"""

from __future__ import annotations

import sys

from jerome_pipeline.cli import main


def _legacy_arguments(argv: list[str]) -> list[str]:
    if "--phase" not in argv:
        return argv
    index = argv.index("--phase")
    try:
        phase = argv[index + 1]
    except IndexError as exc:
        raise SystemExit("--phase requires a value") from exc
    mapping = {
        "diagnose": ["inspect-chunks", "--limit", "5"],
        "qwen": ["run", "--through", "witness_a"],
        "mistral": ["run", "--through", "witness_b"],
        "draft": ["run", "--through", "witness_b"],
        "prosecutor": ["run", "--through", "prosecutor_grounded"],
        "review": ["run", "--through", "finalize"],
        "all": ["run", "--through", "finalize"],
    }
    if phase not in mapping:
        raise SystemExit(f"Unknown legacy phase: {phase}")
    translated = list(mapping[phase])
    if "--limit" in argv and phase != "diagnose":
        limit_index = argv.index("--limit")
        translated += ["--limit", argv[limit_index + 1]]
    print(
        f"Legacy --phase {phase!r} mapped to: {' '.join(translated)}. "
        "Provider/model selection now comes from pipeline.yaml.",
        file=sys.stderr,
    )
    return translated


if __name__ == "__main__":
    raise SystemExit(main(_legacy_arguments(sys.argv[1:])))
