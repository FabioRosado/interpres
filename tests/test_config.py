from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from jerome_pipeline.config import ConfigurationError, load_config, load_env_file


class DotenvTest(unittest.TestCase):
    def test_loads_values_without_overriding_process_environment(self):
        first = "JEROME_TEST_DOTENV_FIRST"
        second = "JEROME_TEST_DOTENV_SECOND"
        previous = {name: os.environ.get(name) for name in (first, second)}
        try:
            os.environ[first] = "from-process"
            os.environ.pop(second, None)
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / ".env"
                path.write_text(
                    f'{first}=from-file\n{second}="value=with#symbols"\n',
                    encoding="utf-8",
                )
                loaded = load_env_file(path)
            self.assertEqual(os.environ[first], "from-process")
            self.assertEqual(os.environ[second], "value=with#symbols")
            self.assertEqual(loaded, [second])
        finally:
            for name, value in previous.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value

    def test_rejects_malformed_entries_without_echoing_the_value(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text("NOT A NAME=secret-value\n", encoding="utf-8")
            with self.assertRaises(ConfigurationError) as raised:
                load_env_file(path)
            self.assertNotIn("secret-value", str(raised.exception))


class ProductionModelConfigTest(unittest.TestCase):
    def test_structural_parser_has_selective_live_chunk_two_output_headroom(self):
        config = load_config()
        self.assertEqual(
            config.model("structural_parser").max_output_tokens,
            5200,
        )
        self.assertEqual(
            config.model("structural_parser", profile="smoke").max_output_tokens,
            5200,
        )
        self.assertEqual(
            config.section("structural_output_budget"),
            {
                "large_sentence_threshold": 12,
                "large_max_output_tokens": 7200,
            },
        )

    def test_production_prosecutor_has_closing_margin_but_smoke_stays_small(self):
        config = load_config()
        self.assertEqual(config.model("prosecutor").max_output_tokens, 4200)
        self.assertEqual(
            config.model("prosecutor", profile="smoke").max_output_tokens,
            3200,
        )
        self.assertEqual(
            config.section("prosecutor_input_budget")["max_estimated_prompt_tokens"],
            16000,
        )
        self.assertEqual(
            config.section("adjudicator_edit_budget"),
            {
                "max_words_per_edit": 48,
                "max_cumulative_words": 96,
                "max_base_replacement_ratio": 0.25,
            },
        )


if __name__ == "__main__":
    unittest.main()
