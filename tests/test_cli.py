from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from interpres.cache import StageCache, stage_record
from interpres.cli import _failed_chunk_jobs, build_parser
from interpres.config import PipelineConfig, load_config


class FailedChunkCommandTest(unittest.TestCase):
    def config(self, directory: str) -> PipelineConfig:
        base = load_config()
        data = copy.deepcopy(base.data)
        data["paths"]["artifacts"] = str(Path(directory) / "artifacts")
        data["paths"]["cache"] = str(Path(directory) / "cache")
        return PipelineConfig(path=base.path, root=Path(directory), data=data)

    @staticmethod
    def save_record(
        config: PipelineConfig,
        *,
        chunk_id: str,
        source_fingerprint: str,
        stage: str = "structural_parse",
        status: str = "failed",
        profile: str = "production",
        cache_key: str = "failure",
        finished_at: str = "2026-08-25T10:00:00Z",
    ) -> None:
        value = stage_record(
            stage=stage,
            chunk_id=chunk_id,
            cache_key=cache_key,
            cache_material={
                "source_fingerprint": source_fingerprint,
                "inputs": {},
                "dependencies": [],
            },
            pipeline_version="fixture",
            schema_version=1,
            prompt_version="fixture",
            status=status,
            started_at="2026-08-25T09:59:59Z",
            error=(
                {"category": "fixture_failure", "message": "fixture failed"}
                if status != "complete"
                else None
            ),
        )
        value["execution_profile"] = profile
        value["finished_at"] = finished_at
        StageCache(config.path_value("cache")).save(value)

    def test_failed_jobs_exclude_unstarted_stale_smoke_and_recovered_chunks(self):
        with tempfile.TemporaryDirectory() as directory:
            config = self.config(directory)
            chunks = [
                {
                    "chunk_id": f"book01-chunk-{index}",
                    "source_fingerprint": f"source-{index}",
                }
                for index in range(1, 6)
            ]
            path = config.path_value("artifacts") / "book01" / "chunks.jsonl"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                "".join(json.dumps(chunk) + "\n" for chunk in chunks),
                encoding="utf-8",
            )

            # Current production failure: selected.
            self.save_record(
                config,
                chunk_id="book01-chunk-1",
                source_fingerprint="source-1",
            )
            # Chunk 2 has never run: not a failed job.
            # Chunk 3 failed against older Latin: excluded.
            self.save_record(
                config,
                chunk_id="book01-chunk-3",
                source_fingerprint="old-source-3",
            )
            # Chunk 4 is a smoke failure: excluded from production.
            self.save_record(
                config,
                chunk_id="book01-chunk-4",
                source_fingerprint="source-4",
                profile="smoke",
            )
            # Chunk 5 recovered later: latest stage state is complete.
            self.save_record(
                config,
                chunk_id="book01-chunk-5",
                source_fingerprint="source-5",
                cache_key="old-failure",
            )
            self.save_record(
                config,
                chunk_id="book01-chunk-5",
                source_fingerprint="source-5",
                status="complete",
                cache_key="recovered",
                finished_at="2026-08-25T11:00:00Z",
            )

            jobs = _failed_chunk_jobs(config, 1, "production")

            self.assertEqual([job["chunk_id"] for job in jobs], ["book01-chunk-1"])
            self.assertEqual(jobs[0]["failed_stage"], "structural_parse")

    def test_failure_commands_have_safe_dry_run_and_batch_options(self):
        parser = build_parser()
        listed = parser.parse_args(["failed-chunks", "--book", "1"])
        resumed = parser.parse_args(
            [
                "resume-failed",
                "--book",
                "1",
                "--dry-run",
                "--limit",
                "2",
                "--through",
                "finalize",
            ]
        )
        self.assertEqual(listed.command, "failed-chunks")
        self.assertEqual(resumed.command, "resume-failed")
        self.assertTrue(resumed.dry_run)
        self.assertEqual(resumed.limit, 2)

    def test_command_reference_covers_every_parser_command(self):
        parser = build_parser()
        subparsers = next(
            action
            for action in parser._actions
            if getattr(action, "choices", None)
            and "preprocess" in action.choices
        )
        commands = set(subparsers.choices)
        reference = (
            Path(__file__).parents[1] / "docs" / "command-reference.md"
        ).read_text(encoding="utf-8")
        for command in commands - {"challenge", "project", "doctor"}:
            self.assertIn(f"### `{command}`", reference)
        for challenge_command in ("inspect", "run", "report"):
            self.assertIn(f"### `challenge {challenge_command}`", reference)
        for project_command in ("list", "show"):
            self.assertIn(f"### `project {project_command}`", reference)
        self.assertIn("### `doctor`", reference)


if __name__ == "__main__":
    unittest.main()
