from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from .config import ModelSpec, PipelineConfig

OPENROUTER_CONTRACT_VERSION = 2


@dataclass
class ProviderResponse:
    content: str
    seconds: float
    used_model: dict[str, Any]
    attempts: list[dict[str, Any]]
    fallback_used: bool
    metadata: dict[str, Any] = field(default_factory=dict)


class ProviderCallError(RuntimeError):
    def __init__(self, message: str, *, category: str, attempts: list[dict[str, Any]]):
        super().__init__(message)
        self.category = category
        self.attempts = attempts


class ModelProvider:
    def __init__(self, config: PipelineConfig):
        self.config = config

    def chat(
        self,
        spec: ModelSpec,
        prompt: str,
        *,
        json_mode: bool,
        response_schema: dict[str, Any] | None = None,
    ) -> ProviderResponse:
        attempts: list[dict[str, Any]] = []
        try:
            return self._with_retries(
                spec,
                prompt,
                json_mode=json_mode,
                response_schema=response_schema,
                attempts=attempts,
            )
        except ProviderCallError as primary:
            if spec.fallback is None:
                raise
            attempts.append(
                {
                    "provider": spec.provider,
                    "model": spec.model,
                    "outcome": "fallback_triggered",
                    "category": primary.category,
                    "message": str(primary),
                }
            )
            try:
                response = self._with_retries(
                    spec.fallback,
                    prompt,
                    json_mode=json_mode,
                    response_schema=response_schema,
                    attempts=attempts,
                )
                response.fallback_used = True
                return response
            except ProviderCallError as fallback:
                raise ProviderCallError(
                    f"Primary and fallback model calls failed: {fallback}",
                    category=fallback.category,
                    attempts=attempts,
                ) from fallback

    def _with_retries(
        self,
        spec: ModelSpec,
        prompt: str,
        *,
        json_mode: bool,
        response_schema: dict[str, Any] | None,
        attempts: list[dict[str, Any]],
    ) -> ProviderResponse:
        last_error: Exception | None = None
        category = "provider_failure"
        for attempt_number in range(1, spec.retries + 2):
            started = time.perf_counter()
            try:
                content, metadata = self._call(
                    spec,
                    prompt,
                    json_mode=json_mode,
                    response_schema=response_schema,
                )
                seconds = time.perf_counter() - started
                attempt = {
                    "provider": spec.provider,
                    "model": spec.model,
                    "attempt": attempt_number,
                    "outcome": "complete",
                    "seconds": round(seconds, 3),
                }
                attempt.update(metadata)
                attempts.append(attempt)
                return ProviderResponse(
                    content=content,
                    seconds=seconds,
                    used_model=spec.cache_identity(),
                    attempts=attempts,
                    fallback_used=False,
                    metadata=metadata,
                )
            except Exception as exc:
                last_error = exc
                category = getattr(exc, "category", "provider_unavailable")
                attempts.append(
                    {
                        "provider": spec.provider,
                        "model": spec.model,
                        "attempt": attempt_number,
                        "outcome": "failed",
                        "category": category,
                        "message": str(exc),
                        "seconds": round(time.perf_counter() - started, 3),
                    }
                )
        raise ProviderCallError(
            str(last_error or "provider call failed"), category=category, attempts=attempts
        )

    def _call(
        self,
        spec: ModelSpec,
        prompt: str,
        *,
        json_mode: bool,
        response_schema: dict[str, Any] | None,
    ) -> tuple[str, dict[str, Any]]:
        if spec.provider == "ollama":
            return self._ollama(
                spec,
                prompt,
                json_mode=json_mode,
                response_schema=response_schema,
            )
        if spec.provider == "openrouter":
            return self._openrouter(
                spec,
                prompt,
                json_mode=json_mode,
                response_schema=response_schema,
            )
        raise ProviderCallError(
            f"Unsupported provider: {spec.provider}",
            category="configuration_error",
            attempts=[],
        )

    def _ollama(
        self,
        spec: ModelSpec,
        prompt: str,
        *,
        json_mode: bool,
        response_schema: dict[str, Any] | None,
    ) -> tuple[str, dict[str, Any]]:
        provider = self.config.section("providers").get("ollama", {})
        url = provider.get("base_url")
        timeout = int(provider.get("timeout_seconds", 1800))
        payload: dict[str, Any] = {
            "model": spec.model,
            "stream": False,
            "think": spec.thinking,
            "messages": [{"role": "user", "content": prompt}],
            "options": {
                "temperature": spec.temperature,
                "num_ctx": spec.context,
                "num_predict": spec.max_output_tokens,
                **spec.extra,
            },
        }
        if json_mode:
            payload["format"] = response_schema or "json"
        result = self._post_json(str(url), payload, timeout=timeout, headers={})
        try:
            content = str(result["message"]["content"]).strip()
        except Exception as exc:
            raise RuntimeError(
                "Ollama response missing message.content: "
                + json.dumps(result, ensure_ascii=False)[:800]
            ) from exc
        metadata = {
            key: result[key]
            for key in (
                "done",
                "done_reason",
                "prompt_eval_count",
                "eval_count",
                "prompt_eval_duration",
                "eval_duration",
            )
            if key in result
        }
        return content, metadata

    def _openrouter(
        self,
        spec: ModelSpec,
        prompt: str,
        *,
        json_mode: bool,
        response_schema: dict[str, Any] | None,
    ) -> tuple[str, dict[str, Any]]:
        provider = self.config.section("providers").get("openrouter", {})
        key_name = str(provider.get("api_key_env", "OPENROUTER_API_KEY"))
        api_key = os.environ.get(key_name)
        if not api_key:
            error = ProviderCallError(
                f"{key_name} is not set",
                category="provider_unavailable",
                attempts=[],
            )
            raise error
        payload: dict[str, Any] = {
            "model": spec.model,
            "stream": False,
            "temperature": spec.temperature,
            "max_tokens": spec.max_output_tokens,
            "reasoning": {
                "enabled": True,
            }
            if spec.thinking
            else {
                "effort": "none",
            },
            "messages": [{"role": "user", "content": prompt}],
        }
        if json_mode:
            payload["response_format"] = (
                {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "structured_response",
                        "strict": True,
                        "schema": response_schema,
                    },
                }
                if response_schema
                else {"type": "json_object"}
            )
        result = self._post_json(
            str(provider.get("base_url")),
            payload,
            timeout=int(provider.get("timeout_seconds", 1800)),
            headers={"Authorization": f"Bearer {api_key}"},
        )
        try:
            choice = result["choices"][0]
            content = str(choice["message"]["content"]).strip()
        except Exception as exc:
            raise RuntimeError(
                "OpenRouter response missing choices[0].message.content: "
                + json.dumps(result, ensure_ascii=False)[:800]
            ) from exc
        metadata = {
            "finish_reason": choice.get("finish_reason"),
            "usage": result.get("usage"),
        }
        return content, metadata

    @staticmethod
    def _post_json(
        url: str,
        payload: dict[str, Any],
        *,
        timeout: int,
        headers: dict[str, str],
    ) -> dict[str, Any]:
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", **headers},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                result = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            error = RuntimeError(f"HTTP {exc.code}: {body[:1000]}")
            error.category = "provider_http_error"  # type: ignore[attr-defined]
            raise error from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            error = RuntimeError(f"Provider unavailable: {exc}")
            error.category = "provider_unavailable"  # type: ignore[attr-defined]
            raise error from exc
        if not isinstance(result, dict):
            raise RuntimeError("Provider response was not a JSON object")
        return result
