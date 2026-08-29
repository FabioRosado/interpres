from __future__ import annotations

import json
import math
import re
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any

from .cache import canonical_digest, utc_now

INDEX_VERSION = 1
INDEX_METHOD = "latin_tfidf_lsa_v1"
SOURCE_INDEX_METHOD = "source_tfidf_lsa_v1"
SUPPORTED_INDEX_METHODS = {INDEX_METHOD, SOURCE_INDEX_METHOD}


def _normalize_latin(value: str) -> str:
    value = unicodedata.normalize("NFKD", value.casefold())
    value = value.replace("æ", "ae").replace("œ", "oe")
    value = value.replace("j", "i").replace("v", "u")
    value = "".join(char for char in value if not unicodedata.combining(char))
    return " ".join(re.findall(r"[a-z]+", value))


def _normalize_source(value: str) -> str:
    value = unicodedata.normalize("NFKD", value.casefold())
    value = "".join(char for char in value if not unicodedata.combining(char))
    return " ".join(re.findall(r"[a-z0-9]+", value))


def _features(value: str, *, method: str = INDEX_METHOD) -> list[str]:
    if method == INDEX_METHOD:
        tokens = _normalize_latin(value).split()
    elif method == SOURCE_INDEX_METHOD:
        tokens = _normalize_source(value).split()
    else:
        raise ValueError(f"Unsupported retrieval index method: {method}")
    unigrams = [f"w:{token}" for token in tokens]
    bigrams = [f"b:{left}_{right}" for left, right in zip(tokens, tokens[1:])]
    return unigrams + bigrams


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"Expected object at {path}:{line_number}")
            records.append(value)
    return records


def build_local_retrieval_index(
    concordance_path: Path,
    output_path: Path,
    *,
    dimensions: int = 48,
    min_document_frequency: int = 1,
    method: str = INDEX_METHOD,
    source_identity: dict[str, Any] | None = None,
    concordance_identity: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build an inspectable deterministic latent retrieval index.

    This is local RAG retrieval, not a pretrained semantic authority. LSA can
    surface co-occurring vocabulary beyond exact phrases while every result
    still returns the original Latin and source provenance.
    """
    try:
        import numpy as np
    except ImportError as exc:  # pragma: no cover - environment contract
        raise RuntimeError("NumPy is required to build the local retrieval index") from exc

    if method not in SUPPORTED_INDEX_METHODS:
        raise ValueError(f"Unsupported retrieval index method: {method}")
    records = _read_jsonl(concordance_path)
    if not records:
        raise ValueError("Cannot build retrieval index from an empty concordance")
    feature_lists = [
        _features(str(record.get("text", "")), method=method) for record in records
    ]
    document_frequency: Counter[str] = Counter()
    for features in feature_lists:
        document_frequency.update(set(features))
    minimum = max(1, int(min_document_frequency))
    vocabulary = sorted(
        feature for feature, count in document_frequency.items() if count >= minimum
    )
    if not vocabulary:
        raise ValueError("Retrieval vocabulary is empty after frequency filtering")
    positions = {feature: index for index, feature in enumerate(vocabulary)}
    document_count = len(records)
    idf = np.array(
        [
            math.log(
                (document_count + 1) / (document_frequency[feature] + 1)
            )
            + 1.0
            for feature in vocabulary
        ],
        dtype=np.float64,
    )
    matrix = np.zeros((document_count, len(vocabulary)), dtype=np.float64)
    for row, features in enumerate(feature_lists):
        counts = Counter(features)
        for feature, count in counts.items():
            column = positions.get(feature)
            if column is not None:
                matrix[row, column] = (1.0 + math.log(count)) * idf[column]
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    matrix = np.divide(matrix, norms, out=np.zeros_like(matrix), where=norms != 0)

    requested_dimensions = max(1, int(dimensions))
    rank = min(requested_dimensions, matrix.shape[0], matrix.shape[1])
    _u, _s, components = np.linalg.svd(matrix, full_matrices=False)
    components = components[:rank]
    # SVD component signs are arbitrary. Canonicalize them for reproducible
    # JSON/digests across rebuilds using the largest absolute loading.
    for index in range(components.shape[0]):
        pivot = int(np.argmax(np.abs(components[index])))
        if components[index, pivot] < 0:
            components[index] *= -1
    document_vectors = matrix @ components.T
    vector_norms = np.linalg.norm(document_vectors, axis=1, keepdims=True)
    document_vectors = np.divide(
        document_vectors,
        vector_norms,
        out=np.zeros_like(document_vectors),
        where=vector_norms != 0,
    )

    payload: dict[str, Any] = {
        "index_version": INDEX_VERSION,
        "method": method,
        "built_at": utc_now(),
        "source": {
            "concordance_path": str(concordance_path),
            "records": document_count,
            "records_digest": canonical_digest(records),
            "canonical_source_digest": (source_identity or {}).get(
                "canonical_source_digest"
            ),
            "concordance_records_digest": (concordance_identity or {}).get(
                "records_digest"
            ),
        },
        "parameters": {
            "features": (
                "normalized Latin word unigrams+bigrams"
                if method == INDEX_METHOD
                else "normalized source word/number unigrams+bigrams"
            ),
            "tf": "1+log(count)",
            "idf": "log((N+1)/(df+1))+1",
            "normalization": "l2 before and after LSA",
            "requested_dimensions": requested_dimensions,
            "dimensions": rank,
            "min_document_frequency": minimum,
            "ranking": "0.60 lexical cosine + 0.40 nonnegative LSA cosine",
        },
        "vocabulary": vocabulary,
        "idf": [round(float(value), 10) for value in idf],
        "components": [
            [round(float(value), 10) for value in row] for row in components
        ],
        "documents": [
            {
                "source_unit_id": record.get("source_unit_id"),
                "book": record.get("book"),
                "page": record.get("page"),
                "text": record.get("text", ""),
                "provenance": record.get("provenance", {}),
                "source_fingerprint": record.get("source_fingerprint"),
                "vector": [round(float(value), 10) for value in vector],
                "tfidf": [
                    [int(position), round(float(weight), 10)]
                    for position, weight in enumerate(term_vector)
                    if weight != 0
                ],
            }
            for record, vector, term_vector in zip(
                records, document_vectors, matrix
            )
        ],
    }
    # built_at is intentionally excluded from semantic identity.
    payload["index_digest"] = canonical_digest(
        {key: value for key, value in payload.items() if key != "built_at"}
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(output_path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    temporary.replace(output_path)
    return {
        "path": str(output_path),
        "method": method,
        "records": document_count,
        "vocabulary": len(vocabulary),
        "dimensions": rank,
        "index_digest": payload["index_digest"],
        "records_digest": payload["source"]["records_digest"],
        "canonical_source_digest": payload["source"].get(
            "canonical_source_digest"
        ),
    }


class LocalRetrievalIndex:
    def __init__(self, path: Path):
        self.path = path
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict) or value.get("method") not in SUPPORTED_INDEX_METHODS:
            raise ValueError(f"Unsupported retrieval index: {path}")
        self.value = value
        self.vocabulary = {
            feature: index for index, feature in enumerate(value["vocabulary"])
        }

    @property
    def identity(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "method": self.value["method"],
            "index_version": self.value["index_version"],
            "index_digest": self.value["index_digest"],
            "records_digest": self.value["source"]["records_digest"],
            "canonical_source_digest": self.value["source"].get(
                "canonical_source_digest"
            ),
            "dimensions": self.value["parameters"]["dimensions"],
        }

    def search(self, query: str, *, limit: int = 8) -> list[dict[str, Any]]:
        try:
            import numpy as np
        except ImportError as exc:  # pragma: no cover - environment contract
            raise RuntimeError("NumPy is required for local retrieval") from exc
        method = str(self.value.get("method", INDEX_METHOD))
        counts = Counter(_features(query, method=method))
        vector = np.zeros(len(self.vocabulary), dtype=np.float64)
        idf = self.value["idf"]
        for feature, count in counts.items():
            position = self.vocabulary.get(feature)
            if position is not None:
                vector[position] = (1.0 + math.log(count)) * float(idf[position])
        norm = float(np.linalg.norm(vector))
        if norm == 0.0:
            return []
        vector /= norm
        components = np.asarray(self.value["components"], dtype=np.float64)
        projected = vector @ components.T
        projected_norm = float(np.linalg.norm(projected))
        if projected_norm == 0.0:
            return []
        projected /= projected_norm
        scored: list[tuple[float, float, float, dict[str, Any]]] = []
        for document in self.value["documents"]:
            latent_score = float(
                np.dot(projected, np.asarray(document["vector"], dtype=np.float64))
            )
            lexical_score = sum(
                float(vector[int(position)]) * float(weight)
                for position, weight in document.get("tfidf", [])
            )
            score = 0.60 * lexical_score + 0.40 * max(0.0, latent_score)
            if score > 0:
                scored.append((score, lexical_score, latent_score, document))
        scored.sort(
            key=lambda item: (
                -item[0],
                -item[1],
                str(item[3].get("source_unit_id", "")),
            )
        )
        return [
            {
                "score": round(score, 8),
                "lexical_score": round(lexical_score, 8),
                "latent_score": round(latent_score, 8),
                "match_kind": method,
                "text": document["text"],
                "provenance": document["provenance"],
                "source_unit_id": document["source_unit_id"],
                "book": document["book"],
                "page": document["page"],
                "index_digest": self.value["index_digest"],
            }
            for score, lexical_score, latent_score, document in scored[
                : max(0, int(limit))
            ]
        ]
