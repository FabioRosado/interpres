from __future__ import annotations

import copy
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


class ConfigurationError(ValueError):
    """Raised when required pipeline configuration is absent or malformed."""


ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def load_env_file(path: Path, *, override: bool = False) -> list[str]:
    """Load a small, predictable dotenv subset without exposing values.

    Existing process variables win by default.  Values may be unquoted,
    single-quoted, or double-quoted; the first ``=`` separates name and value,
    so provider keys containing ``=`` remain intact.
    """
    if not path.exists():
        return []
    loaded: list[str] = []
    with path.open("r", encoding="utf-8-sig") as handle:
        for line_number, original in enumerate(handle, 1):
            line = original.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[7:].lstrip()
            name, separator, raw_value = line.partition("=")
            name = name.strip()
            if not separator or not ENV_NAME_RE.fullmatch(name):
                raise ConfigurationError(
                    f"Invalid dotenv entry at {path}:{line_number}"
                )
            value = raw_value.strip()
            if value.startswith(("'", '"')):
                quote = value[0]
                if len(value) < 2 or not value.endswith(quote):
                    raise ConfigurationError(
                        f"Unclosed dotenv quote at {path}:{line_number}"
                    )
                value = value[1:-1]
                if quote == '"':
                    value = (
                        value.replace(r"\n", "\n")
                        .replace(r"\r", "\r")
                        .replace(r"\t", "\t")
                        .replace(r'\"', '"')
                        .replace(r"\\", "\\")
                    )
            else:
                # Treat a whitespace-prefixed # as a comment. A literal #
                # inside an unspaced secret remains part of the value.
                value = re.split(r"\s+#", value, maxsplit=1)[0].rstrip()
            if override or name not in os.environ:
                os.environ[name] = value
                loaded.append(name)
    return loaded


@dataclass(frozen=True)
class ModelSpec:
    role: str
    provider: str
    model: str
    profile: str = "production"
    temperature: float = 0.1
    context: int = 8192
    max_output_tokens: int = 1600
    thinking: bool = False
    retries: int = 1
    fallback: ModelSpec | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def cache_identity(self) -> dict[str, Any]:
        value = {
            "role": self.role,
            "provider": self.provider,
            "model": self.model,
            "profile": self.profile,
            "temperature": self.temperature,
            "context": self.context,
            "max_output_tokens": self.max_output_tokens,
            "thinking": self.thinking,
            "extra": self.extra,
        }
        if self.fallback:
            value["fallback"] = self.fallback.cache_identity()
        return value


@dataclass
class PipelineConfig:
    path: Path
    root: Path
    data: dict[str, Any]

    @property
    def pipeline_version(self) -> str:
        return str(self.data["pipeline"]["version"])

    @property
    def schema_version(self) -> int:
        return int(self.data["pipeline"]["schema_version"])

    @property
    def prompt_version(self) -> str:
        return str(self.data["pipeline"]["prompt_version"])

    def path_value(self, key: str) -> Path:
        raw = self.data.get("paths", {}).get(key)
        if not isinstance(raw, str) or not raw.strip():
            raise ConfigurationError(f"paths.{key} must be a non-empty path")
        expanded = Path(os.path.expandvars(raw))
        return expanded if expanded.is_absolute() else self.root / expanded

    def source_path(self, book: int) -> Path:
        books = self.data.get("source", {}).get("books", {})
        raw = books.get(str(book), books.get(book))
        if not raw:
            raise ConfigurationError(f"No source.books entry configured for book {book}")
        value = Path(os.path.expandvars(str(raw)))
        return value if value.is_absolute() else self.root / value

    def model(self, role: str, *, profile: str = "production") -> ModelSpec:
        models = self.data.get("models", {})
        base = models.get(role)
        if not isinstance(base, Mapping):
            raise ConfigurationError(f"models.{role} is not configured")
        profiles = self.data.get("profiles", {})
        if profile not in profiles:
            raise ConfigurationError(f"Unknown model profile: {profile}")
        profile_data = profiles.get(profile, {})
        overrides = profile_data.get("models", {}) if isinstance(profile_data, Mapping) else {}
        override = overrides.get(role, {}) if isinstance(overrides, Mapping) else {}
        if override and not isinstance(override, Mapping):
            raise ConfigurationError(f"profiles.{profile}.models.{role} must be an object")
        raw = {**base, **override}
        if raw.get("enabled") is False:
            raise ConfigurationError(f"models.{role} is disabled")
        return _model_spec(role, raw, profile=profile)

    def section(self, name: str) -> dict[str, Any]:
        value = self.data.get(name, {})
        if not isinstance(value, dict):
            raise ConfigurationError(f"{name} must be an object")
        return copy.deepcopy(value)


def _model_spec(
    role: str, raw: Mapping[str, Any], *, profile: str = "production"
) -> ModelSpec:
    provider = str(raw.get("provider", "")).strip()
    model = str(raw.get("model", "")).strip()
    if not provider or not model or model == "config-required-before-use":
        raise ConfigurationError(
            f"models.{role} requires explicit provider and actual model name"
        )
    known = {
        "enabled",
        "provider",
        "model",
        "temperature",
        "context",
        "max_output_tokens",
        "thinking",
        "retries",
        "fallback",
    }
    fallback_raw = raw.get("fallback")
    fallback = (
        _model_spec(f"{role}.fallback", fallback_raw, profile=profile)
        if isinstance(fallback_raw, Mapping)
        else None
    )
    return ModelSpec(
        role=role,
        provider=provider,
        model=model,
        profile=profile,
        temperature=float(raw.get("temperature", 0.1)),
        context=int(raw.get("context", 8192)),
        max_output_tokens=int(raw.get("max_output_tokens", 1600)),
        thinking=bool(raw.get("thinking", False)),
        retries=max(0, int(raw.get("retries", 1))),
        fallback=fallback,
        extra={str(k): v for k, v in raw.items() if k not in known},
    )


def load_config(path: str | Path = "pipeline.yaml") -> PipelineConfig:
    config_path = Path(path).resolve()
    if not config_path.exists():
        raise ConfigurationError(f"Configuration file not found: {config_path}")
    load_env_file(config_path.parent / ".env")
    with config_path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise ConfigurationError("Configuration root must be an object")
    for required in ("pipeline", "source", "paths", "models"):
        if not isinstance(data.get(required), dict):
            raise ConfigurationError(f"Missing required configuration section: {required}")
    return PipelineConfig(path=config_path, root=config_path.parent, data=data)
