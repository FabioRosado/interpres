from __future__ import annotations

import unittest
from os import environ
from unittest.mock import patch

from jerome_pipeline.config import load_config
from jerome_pipeline.providers import ModelProvider


class ProviderStructuredOutputTest(unittest.TestCase):
    def test_ollama_schema_and_stop_metadata_are_preserved(self):
        config = load_config()
        provider = ModelProvider(config)
        spec = config.model("structural_parser", profile="smoke")
        schema = {
            "type": "object",
            "properties": {"sentences": {"type": "array"}},
            "required": ["sentences"],
        }
        ollama_result = {
            "message": {"content": '{"sentences":[]}'},
            "done": True,
            "done_reason": "length",
            "prompt_eval_count": 100,
            "eval_count": 5200,
        }
        with patch.object(
            ModelProvider, "_post_json", return_value=ollama_result
        ) as post:
            response = provider.chat(
                spec,
                "test prompt",
                json_mode=True,
                response_schema=schema,
            )
        payload = post.call_args.args[1]
        self.assertEqual(payload["format"], schema)
        self.assertEqual(response.metadata["done_reason"], "length")
        self.assertEqual(response.metadata["eval_count"], 5200)
        self.assertEqual(response.attempts[-1]["done_reason"], "length")

    def test_openrouter_disables_reasoning_when_thinking_is_false(self):
        config = load_config()
        provider = ModelProvider(config)
        spec = config.model("prosecutor")
        openrouter_result = {
            "choices": [
                {
                    "message": {"content": '{"issues":[]}'},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 12,
            },
        }
        with patch.dict(environ, {"OPENROUTER_API_KEY": "fixture-key"}), patch.object(
            ModelProvider, "_post_json", return_value=openrouter_result
        ) as post:
            response = provider.chat(
                spec,
                "test prompt",
                json_mode=True,
                response_schema={"type": "object"},
            )

        payload = post.call_args.args[1]
        self.assertEqual(payload["reasoning"], {"effort": "none"})
        self.assertEqual(payload["max_tokens"], 4200)
        self.assertEqual(response.content, '{"issues":[]}')

    def test_timeout_retries_primary_then_uses_configured_fallback(self):
        config = load_config()
        provider = ModelProvider(config)
        spec = config.model("prosecutor")
        calls: list[tuple[str, str]] = []

        def fake_call(current, prompt, *, json_mode, response_schema):
            calls.append((current.provider, current.model))
            if current.provider == "openrouter":
                raise TimeoutError("fixture timeout")
            return '{"status":"ok"}', {"done_reason": "stop"}

        with patch.object(provider, "_call", side_effect=fake_call):
            response = provider.chat(spec, "fixture", json_mode=True)
        self.assertTrue(response.fallback_used)
        self.assertEqual(response.used_model["provider"], "ollama")
        self.assertEqual(response.used_model["model"], "gemma3:27b")
        self.assertEqual(
            calls,
            [
                ("openrouter", "nvidia/nemotron-3-ultra-550b-a55b:free"),
                ("openrouter", "nvidia/nemotron-3-ultra-550b-a55b:free"),
                ("ollama", "gemma3:27b"),
            ],
        )
        self.assertTrue(
            any(
                attempt.get("outcome") == "fallback_triggered"
                for attempt in response.attempts
            )
        )


if __name__ == "__main__":
    unittest.main()
