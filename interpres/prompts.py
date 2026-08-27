from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from typing import Any

from .source import split_sentences

ADJUDICATOR_INPUT_BUDGET_POLICY_VERSION = 2
PROSECUTOR_INPUT_BUDGET_POLICY_VERSION = 1


@dataclass(frozen=True)
class BudgetedAdjudicatorPrompt:
    """A provider-ready prompt plus an auditable, deterministic budget receipt."""

    prompt: str | None
    receipt: dict[str, Any]

    @property
    def fits(self) -> bool:
        return self.prompt is not None and bool(self.receipt.get("fits"))


@dataclass(frozen=True)
class BudgetedProsecutorPrompt:
    """A provider-ready prosecutor prompt and its deterministic input receipt."""

    prompt: str | None
    receipt: dict[str, Any]

    @property
    def fits(self) -> bool:
        return self.prompt is not None and bool(self.receipt.get("fits"))


def _pretty(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)


def _compact_adjudicator_structural(
    structural: dict[str, Any],
) -> dict[str, Any]:
    sentences = []
    for sentence in structural.get("sentences", []):
        sentences.append(
            {
                "latin": sentence.get("latin", ""),
                "main_verbs": [
                    {
                        key: verb.get(key, "")
                        for key in ("form", "lemma", "mood", "tense", "voice")
                    }
                    for verb in sentence.get("main_verbs", [])
                ],
                "subject": sentence.get("subject", {}),
                "alternatives": sentence.get("alternatives", []),
            }
        )
    return {
        "sentences": sentences,
        "intrinsic_ambiguity": structural.get("intrinsic_ambiguity", []),
        "context_dependent": structural.get("context_dependent", []),
        "unverified_analyses": structural.get("unverified_analyses", []),
    }


def _compact_adjudicator_flags(
    lexical: dict[str, Any], prosecutor: dict[str, Any]
) -> list[dict[str, Any]]:
    challenged_words = {
        word.casefold()
        for challenge in prosecutor.get("challenges", [])
        for word in re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿ]+", challenge.get("latin", ""))
    }
    selected = []
    for flag in lexical.get("flags", []):
        if (
            flag.get("flag_type") != "known_trap"
            and str(flag.get("token", "")).casefold() not in challenged_words
        ):
            continue
        selected.append(
            {
                "token": flag.get("token"),
                "offset": flag.get("offset"),
                "flag_type": flag.get("flag_type"),
                "senses": flag.get("senses", [])[:6],
                "note": str(flag.get("note", ""))[:320],
            }
        )
    return selected


def _compact_adjudicator_checks(checks: dict[str, Any]) -> dict[str, Any]:
    findings = [
        finding
        for finding in checks.get("findings", [])
        if finding.get("status") != "pass"
        or finding.get("check") == "number_words"
    ]
    return {
        "summary": checks.get("summary", {}),
        "findings": findings,
        "limits": checks.get("limits"),
        "editorial_precedents": checks.get("editorial_precedents", []),
        "editorial_precedent_policy": checks.get(
            "editorial_precedent_policy", {}
        ),
    }


def _compact_adjudicator_evidence(
    evidence: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    compact = []
    for receipt in evidence:
        results = []
        for result in receipt.get("results", [])[:3]:
            if not isinstance(result, dict):
                continue
            projected = {
                key: result[key]
                for key in (
                    "token",
                    "found",
                    "score",
                    "lexical_score",
                    "latent_score",
                    "match_kind",
                    "source_unit_id",
                    "book",
                    "page",
                    "reference",
                )
                if key in result
            }
            if "text" in result:
                projected["text"] = str(result["text"])[:700]
            if "senses" in result:
                projected["senses"] = result.get("senses", [])[:4]
            if "candidates" in result:
                projected["candidates"] = result.get("candidates", [])[:4]
            if "provenance" in result:
                projected["provenance"] = result.get("provenance")
            results.append(projected)
        compact.append(
            {
                "evidence_id": receipt.get("evidence_id"),
                "request": receipt.get("request"),
                "status": receipt.get("status"),
                "evidence_class": receipt.get("evidence_class"),
                "source_annotation_verified": receipt.get(
                    "source_annotation_verified", False
                ),
                "textual_match_verified": receipt.get(
                    "textual_match_verified", False
                ),
                "results": results,
            }
        )
    return compact


def _referenced_evidence_ids(value: Any) -> set[str]:
    """Collect persisted evidence IDs without inventing new relationships."""

    return set(re.findall(r"\bev-[A-Za-z0-9_-]+\b", _compact_json(value)))


def _decisive_evidence_ids(prosecutor: dict[str, Any]) -> list[str]:
    ids: set[str] = set()
    for challenge in prosecutor.get("challenges", []):
        if not isinstance(challenge, dict) or challenge.get("severity") != "high":
            continue
        ids.update(_referenced_evidence_ids(challenge))
    return sorted(ids)


def _compact_structural_issues(
    structural: dict[str, Any], prosecutor: dict[str, Any]
) -> dict[str, Any]:
    """Retain structural uncertainty while avoiding a second copy of all Latin."""

    challenged_latin = [
        str(item.get("latin", "")).strip()
        for item in prosecutor.get("challenges", [])
        if isinstance(item, dict) and str(item.get("latin", "")).strip()
    ]
    sentences = []
    for index, sentence in enumerate(structural.get("sentences", []), 1):
        if not isinstance(sentence, dict):
            continue
        latin = str(sentence.get("latin", ""))
        alternatives = sentence.get("alternatives", [])
        relevant_forms = {
            word.casefold()
            for phrase in challenged_latin
            if phrase and phrase in latin
            for word in re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿ]+", phrase)
        }
        verbs = []
        for verb in sentence.get("main_verbs", []):
            if not isinstance(verb, dict):
                continue
            form = str(verb.get("form", ""))
            if alternatives or any(
                token.casefold() in relevant_forms
                for token in re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿ]+", form)
            ):
                verbs.append(
                    {
                        key: verb.get(key, "")
                        for key in ("form", "lemma", "mood", "tense", "voice")
                    }
                )
        if alternatives or verbs:
            sentences.append(
                {
                    "sentence": index,
                    "latin_excerpt": latin[:320],
                    "main_verbs": verbs,
                    "alternatives": alternatives,
                }
            )
    return {
        "relevant_sentences": sentences,
        "intrinsic_ambiguity": structural.get("intrinsic_ambiguity", []),
        "context_dependent": structural.get("context_dependent", []),
        "unverified_analyses": structural.get("unverified_analyses", []),
        "notice": "Full blind structural record is preserved in the stage audit.",
    }


def _compact_deterministic_issues(checks: dict[str, Any]) -> dict[str, Any]:
    findings = []
    for finding in checks.get("findings", []):
        if not isinstance(finding, dict) or finding.get("status") == "pass":
            continue
        evidence = finding.get("evidence", {})
        if not isinstance(evidence, dict):
            evidence = {}
        projected_evidence = {
            key: evidence[key]
            for key in (
                "source_phrase",
                "matched_wrong_rendering",
                "expected",
                "witness",
                "curated_mismatches",
                "missing",
                "reference",
                "source_unit_ids",
                "textual_match_verified",
                "source_annotation_verified",
            )
            if key in evidence
        }
        findings.append(
            {
                "finding_id": finding.get("finding_id"),
                "check": finding.get("check"),
                "status": finding.get("status"),
                "severity": finding.get("severity"),
                "message": finding.get("message"),
                "evidence": projected_evidence,
            }
        )
    return {
        "summary": checks.get("summary", {}),
        "findings": findings,
        "limits": checks.get("limits"),
        "editorial_precedents": checks.get("editorial_precedents", []),
        "editorial_precedent_policy": checks.get(
            "editorial_precedent_policy", {}
        ),
        "notice": "Only non-pass deterministic findings are included; full checks remain audited.",
    }


def _compact_budget_flags(
    lexical: dict[str, Any], prosecutor: dict[str, Any]
) -> list[dict[str, Any]]:
    selected = _compact_adjudicator_flags(lexical, prosecutor)
    compact = []
    for flag in selected:
        known_trap = flag.get("flag_type") == "known_trap"
        compact.append(
            {
                **flag,
                "senses": flag.get("senses", [])[: (6 if known_trap else 2)],
                "note": str(flag.get("note", ""))[: (320 if known_trap else 160)],
            }
        )
    return compact


def _compact_budget_evidence(
    evidence: list[dict[str, Any]],
    decisive_ids: set[str],
    *,
    summarize_lower: bool = True,
) -> list[dict[str, Any]]:
    """Preserve decisive first results; summarize only lower-priority receipts."""

    baseline = _compact_adjudicator_evidence(evidence)
    raw_by_id = {
        str(receipt.get("evidence_id") or ""): receipt
        for receipt in evidence
        if isinstance(receipt, dict)
    }
    compact = []
    for receipt in baseline:
        evidence_id = str(receipt.get("evidence_id") or "")
        if evidence_id in decisive_ids:
            preserved = json.loads(json.dumps(receipt, ensure_ascii=False))
            raw_results = _list_dicts(raw_by_id.get(evidence_id, {}).get("results"))
            if raw_results and preserved.get("results"):
                first = preserved["results"][0]
                raw_first = raw_results[0]
                for key in ("text", "senses", "candidates", "provenance"):
                    if key in raw_first:
                        first[key] = raw_first[key]
            compact.append(preserved)
            continue
        if not summarize_lower:
            compact.append(receipt)
            continue
        results = []
        for result in receipt.get("results", [])[:1]:
            if not isinstance(result, dict):
                continue
            projected = {
                key: result[key]
                for key in (
                    "token",
                    "found",
                    "score",
                    "match_kind",
                    "source_unit_id",
                    "book",
                    "page",
                    "reference",
                    "provenance",
                )
                if key in result
            }
            if "text" in result:
                projected["text"] = str(result["text"])[:360]
            if "senses" in result:
                projected["senses"] = result.get("senses", [])[:2]
            if "candidates" in result:
                projected["candidates"] = result.get("candidates", [])[:2]
            results.append(projected)
        compact.append({**receipt, "results": results})
    return compact


def _list_dicts(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _prompt_measurement(
    prompt: str,
    *,
    response_schema: dict[str, Any],
    bytes_per_token: float,
) -> dict[str, int]:
    prompt_bytes = len(prompt.encode("utf-8"))
    schema_bytes = len(
        json.dumps(
            response_schema,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    )
    lexical_floor = len(re.findall(r"\w+|[^\w\s]", prompt, re.UNICODE))
    estimated_tokens = max(
        lexical_floor,
        math.ceil(prompt_bytes / bytes_per_token),
    )
    return {
        "prompt_chars": len(prompt),
        "prompt_utf8_bytes": prompt_bytes,
        "schema_utf8_bytes": schema_bytes,
        "request_utf8_bytes": prompt_bytes + schema_bytes,
        "estimated_prompt_tokens": estimated_tokens,
    }


def _compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _compact_morphology(
    morphology: list[dict[str, Any]], *, max_forms: int
) -> list[dict[str, Any]]:
    """Retain parse candidates without flooding syntax prompts with glosses.

    Full original dictionary senses/candidates remain in the immutable
    morphology stage. A structural parser needs lemma/POS/inflection evidence,
    not repeated English dictionary prose.
    """
    def priority(item: tuple[int, dict[str, Any]]) -> tuple[int, int]:
        index, record = item
        candidates = record.get("candidates", [])
        poses = {candidate.get("pos") for candidate in candidates}
        if not record.get("found", False):
            rank = 0
        elif poses & {"v", "vpar"}:
            rank = 1
        elif len(candidates) > 1:
            rank = 2
        elif poses & {"pron", "num"}:
            rank = 3
        else:
            rank = 4
        return rank, index

    selected_indices = {
        index
        for index, _ in sorted(enumerate(morphology), key=priority)[:max_forms]
    }
    compact = []
    for index, record in enumerate(morphology):
        if index not in selected_indices:
            continue
        candidates = []
        seen: set[tuple[Any, ...]] = set()
        for candidate in record.get("candidates", []):
            features = candidate.get("features", {})
            key = (
                candidate.get("lemma"),
                candidate.get("pos"),
                tuple(sorted(features.items())),
                candidate.get("enclitic"),
            )
            if key in seen:
                continue
            seen.add(key)
            candidates.append(
                {
                    "lemma": candidate.get("lemma"),
                    "pos": candidate.get("pos"),
                    "features": features,
                    "enclitic": candidate.get("enclitic"),
                }
            )
            if len(candidates) >= 6:
                break
        compact.append(
            {
                "surface": record.get("surface", record.get("token")),
                "found": record.get("found", False),
                "candidates": candidates,
                "candidate_limit_reached": len(record.get("candidates", [])) > len(candidates),
            }
        )
    return compact


def structural_prompt(
    chunk: dict[str, Any], morphology: list[dict[str, Any]], *, max_forms: int
) -> str:
    candidates = _compact_morphology(morphology, max_forms=max_forms)
    sentences = split_sentences(chunk["target_latin"])
    numbered_sentences = "\n".join(
        f"S{index}: {sentence}" for index, (_, _, sentence) in enumerate(sentences, 1)
    )
    return f"""You are a translation-blind Latin structural analyst for St Jerome.

Analyze the TARGET LATIN independently. Surrounding context is read-only and
is provided only to resolve referents or context-dependent ambiguity. Do not
allow context to override target grammar. Do not translate or write fluent
English.

Deterministic morphology is evidence, not an instruction to choose the first
parse. Choose among supplied candidates only when syntax supports the choice.
Never silently invent a lemma or morphology that contradicts supplied
candidates. If the backend returned no candidate or appears incomplete, you
may propose an analysis only in `unverified_analyses`, clearly marked
unverified.

This is syntax analysis, not research. Do not identify or attribute quotations,
authors, books, Scripture passages, history, or Jerome parallels from memory.
If an external attribution seems potentially relevant, put a short hypothesis
in `unverified_analyses`; do not state it as fact.

For each target sentence identify main verb(s), mood and tense, subject,
objects, subordinate clauses, attachments, referents, idioms/constructions,
and competing plausible alternatives. Preserve alternatives when unresolved.
In `verbs`, include at most six finite clause heads. Exclude standalone
participles and infinitives; combine a participle plus auxiliary as one verbal
form. Put subordinate structure in `clauses` rather than enumerating every
verbal form.
Distinguish:
- intrinsic_ambiguity: remains with reasonable context;
- context_dependent: caused mainly by missing discourse information.

Return VALID JSON ONLY in this compact wire format:
{{
  "sentences": [{{
    "id": 1,
    "verbs": [{{"form":"", "lemma":"", "mood":"", "tense":"", "voice":""}}],
    "subject": {{"text":"", "uncertain":false}},
    "objects": [{{"text":"", "role":"direct|indirect|other"}}],
    "clauses": [{{"text":"", "kind":"", "governor":""}}],
    "attachments": [{{"element":"", "to":"", "alternatives":[]}}],
    "referents": [{{"form":"", "candidate":"", "alternatives":[]}}],
    "idioms": [{{"text":"", "construction":""}}],
    "alternatives": [{{"issue":"", "analyses":[], "classification":"intrinsic_ambiguity|context_dependent"}}]
  }}],
  "intrinsic": [{{"sentence_id":1,"issue":""}}],
  "context": [{{"sentence_id":1,"issue":""}}],
  "unverified": [{{"sentence_id":1,"form":"","analysis":"","reason":""}}]
}}

COMPACTNESS IS REQUIRED:
- Emit exactly one sentence object for every numbered sentence, using each ID
  exactly once. Do not copy the full sentence into the response.
- Emit minified JSON on one line, without indentation or spaces after JSON
  separators. Whitespace is part of the output budget.
- The provider enforces this compact JSON schema. Do not add fields such as
  `latin`, `basis`, commentary, summaries, or morphology candidates.
- Keep every construction, issue, and alternative short and grammatical.
- Use empty lists instead of prose when there is no meaningful issue.
- Include at most two genuinely plausible alternatives per issue.
- Do not reproduce, summarize, or reformat the morphology input.

NUMBERED TARGET SENTENCES:
<<<
{numbered_sentences}

READ-ONLY CONTEXT BEFORE:
<<<
{chunk.get('context_before') or '[None]'}

READ-ONLY CONTEXT AFTER:
<<<
{chunk.get('context_after') or '[None]'}

DETERMINISTIC MORPHOLOGICAL CANDIDATES (original full evidence is stored outside this prompt):
<<<
{_compact_json(candidates)}

FINAL OUTPUT REMINDER: the only top-level keys are exactly `sentences`,
`intrinsic`, `context`, and `unverified`. Do not repeat target sentences or
morphology. Do not translate and make no external attributions.
"""


def witness_prompt(chunk: dict[str, Any]) -> str:
    return f"""Translate the TARGET Latin passage from St Jerome into accurate English.

Priorities:
- Preserve every clause and meaningful distinction.
- Stay relatively close to the Latin syntax where readable.
- Do not add historical or theological explanations.
- Do not silently omit difficult wording.
- Preserve technical, biblical, Hebrew, Greek, and textual-critical terms.
- Do not modernize an unfamiliar ancient term because it resembles a modern word.
- Preserve names, negation, number, chronology, and textual variants carefully.
- If genuinely uncertain, mark `[UNCERTAIN: precise explanation]`.
- Do not reconstruct quotations or references from memory.
- No auxiliary Latin context is supplied. Translate all and only the target.
- Return only the continuous English translation. Do not return JSON, headings,
  commentary, introductions, notes, source-unit markers, or Markdown fences.
- Preserve an incomplete opening or terminal fragment as an incomplete English
  fragment. Do not complete a quotation or sentence from memory.

<TARGET_LATIN translate="all_and_only">
{chunk['target_latin']}
</TARGET_LATIN>

The target above is the complete request. Do not infer or continue text beyond
its beginning or end, even when a quotation or sentence fragment is incomplete.
"""


def _quorum_filtered_checks(
    checks: dict[str, Any], witness_gate: dict[str, Any] | None
) -> dict[str, Any]:
    """Exclude invalid-witness findings from model evidence, not from audit."""

    if not witness_gate or witness_gate.get("mode") != "degraded":
        return checks
    invalid = set(witness_gate.get("invalid_witnesses") or [])
    copied = json.loads(json.dumps(checks, ensure_ascii=False))
    kept = []
    excluded = []
    for finding in copied.get("findings", []):
        evidence = finding.get("evidence") if isinstance(finding, dict) else None
        witness = evidence.get("witness") if isinstance(evidence, dict) else None
        if witness in invalid:
            excluded.append(
                {
                    "finding_id": finding.get("finding_id"),
                    "check": finding.get("check"),
                    "witness": witness,
                }
            )
        else:
            kept.append(finding)
    copied["findings"] = kept
    copied["model_evidence_filter"] = {
        "quorum": witness_gate.get("quorum"),
        "invalid_witness_findings_excluded": excluded,
        "invalid_witness_output_is_evidence": False,
    }
    return copied


def _quorum_witness_sections(
    witness_a: str,
    witness_b: str,
    witness_gate: dict[str, Any] | None,
    *,
    prosecutor: bool,
) -> tuple[str, str]:
    if not witness_gate or witness_gate.get("mode") != "degraded":
        qualifier = " (independent)" if prosecutor else ""
        return (
            f"WITNESS A{qualifier}:\n<<<\n{witness_a}",
            f"WITNESS B{qualifier}:\n<<<\n{witness_b}",
        )
    valid = set(witness_gate.get("valid_witnesses") or [])

    def section(name: str, text: str) -> str:
        label = name.removeprefix("witness_").upper()
        if name in valid:
            return f"VALID WITNESS {label} (ONLY ELIGIBLE PROPOSAL):\n<<<\n{text}"
        return (
            f"INVALID WITNESS {label} (AUDIT CLUE, NOT MODEL EVIDENCE):\n<<<\n"
            "[TEXT WITHHELD FROM THIS MODEL REQUEST; preserved immutably in audit]"
        )

    return section("witness_a", witness_a), section("witness_b", witness_b)


def _quorum_notice(witness_gate: dict[str, Any] | None) -> str:
    if not witness_gate or witness_gate.get("mode") != "degraded":
        return ""
    allowed = ", ".join(witness_gate.get("allowed_base_witnesses") or [])
    return f"""
DETERMINISTIC DEGRADED WITNESS QUORUM:
- Quorum: {witness_gate.get('quorum')}.
- Only witness {allowed} is a valid translation proposal and permitted base.
- Invalid witness text is preserved for human audit but is not supplied as
  evidence, may not corroborate a claim, and may not raise an evidence grade.
- Review the valid witness directly against the target Latin, structure,
  morphology, deterministic findings, and retrieved receipts.
- Do not generate or infer a replacement second witness.
"""


def prosecutor_prompt(
    chunk: dict[str, Any],
    structural: dict[str, Any],
    lexical: dict[str, Any],
    checks: dict[str, Any],
    witness_a: str,
    witness_b: str,
    *,
    max_evidence_requests: int = 6,
    witness_gate: dict[str, Any] | None = None,
) -> str:
    witness_a_section, witness_b_section = _quorum_witness_sections(
        witness_a, witness_b, witness_gate, prosecutor=True
    )
    visible_checks = _quorum_filtered_checks(checks, witness_gate)
    return f"""You are the adversarial prosecutor for an evidence-first English edition
of St Jerome's Commentary on Ezekiel. Run a serious review on this chunk even
when the witnesses agree.

Your job is not to retranslate or manufacture disagreement. Try to construct a
grounded reason a proposed translation may be wrong, incomplete, internally
incoherent, overconfident, or dependent on unverified evidence. Agreement is
not proof. A failure to find an issue is not proof.

Use only visible Latin/context, the original blind structural parse,
deterministic lexical evidence, and deterministic checks as current evidence.
Human-approved editorial precedents in the checks are project consistency
guidance, not lexical, manuscript, or corpus proof. Test them against the
visible Latin and request source evidence when their interpretation matters.
Pretrained memories of Scripture, Jerome usage, lexicons, chronology, names,
or history are hypotheses only. Request precise evidence whenever such a claim
matters. Inspect especially omissions/additions, subject-object reversal,
negation, numbers, lexical sense, attachment, referents, names, Scripture,
textual issues, excessive certainty, and contradictions with later information
visible in the same target passage.
{_quorum_notice(witness_gate)}

Return VALID JSON ONLY:
{{
  "status": "no_issue_found|insufficient_basis_to_challenge|requires_evidence|grounded_challenge|unresolved",
  "summary": "one precise sentence",
  "challenges": [{{
    "latin": "exact short target substring",
    "type": "negation|subject_object|number|lexical|attachment|omission|addition|unsupported_certainty|scripture|proper_name|idiom|hebrew_greek|textual|chronology|morphology|source_text|internal_consistency|other",
    "severity": "low|medium|high",
    "witness_target": "witness_a|witness_b|both|final_question",
    "claim": "precise allegation",
    "visible_basis": "specific supplied evidence that warrants investigation",
    "requires_external_evidence": true
  }}],
  "evidence_requests": [{{
    "kind": "jerome_phrase|jerome_lemma|scripture|glossary|morphology|semantic_rag|corpus_related|source_edition|chronology|proper_name|web_research",
    "query": "specific retrievable query",
    "reason": "which challenge it tests and how"
  }}]
}}

OUTPUT BUDGET RULES:
- Return at most 15 distinct substantive challenges. Consolidate overlapping
  lexical, morphology, and attachment allegations instead of repeating them.
- Return at most {max(0, max_evidence_requests)} evidence requests, ordered by
  which could most materially change the decision. Software cannot execute
  requests beyond this bound.
- Keep `summary`, `claim`, `visible_basis`, `query`, and `reason` concise.
- Emit minified JSON on one line without indentation or display whitespace.

TARGET LATIN:
<<<
{chunk['target_latin']}

READ-ONLY CONTEXT BEFORE / AFTER:
<<<
{chunk.get('context_before') or '[None]'}
---
{chunk.get('context_after') or '[None]'}

{witness_a_section}

{witness_b_section}

BLIND STRUCTURAL PARSE (immutable original):
<<<
{_compact_json(structural)}

COMPACT LEXICAL FLAGS (full deterministic morphology is stored separately):
<<<
{_compact_json(lexical.get('flags', []))}

DETERMINISTIC CHECKS:
<<<
{_compact_json(visible_checks)}

SOURCE ANNOTATIONS:
<<<
{_compact_json(chunk.get('annotations', []))}
"""


def _prosecutor_terms(findings: list[dict[str, Any]]) -> set[str]:
    terms: set[str] = set()
    for finding in findings:
        evidence = finding.get("evidence") if isinstance(finding, dict) else {}
        values: list[Any] = [finding.get("message")]
        if isinstance(evidence, dict):
            values.extend(
                (evidence.get("source_phrase"), evidence.get("matched_wrong_rendering"))
            )
            for mismatch in evidence.get("curated_mismatches", []):
                if isinstance(mismatch, dict):
                    values.extend((mismatch.get("source_form"), mismatch.get("expected")))
        for value in values:
            terms.update(
                word.casefold()
                for word in re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿ]+", str(value or ""))
                if len(word) >= 3
            )
    return terms


def _prosecutor_finding(finding: dict[str, Any]) -> dict[str, Any]:
    evidence = finding.get("evidence")
    evidence = evidence if isinstance(evidence, dict) else {}
    return {
        "finding_id": finding.get("finding_id"),
        "check": finding.get("check"),
        "status": finding.get("status"),
        "severity": finding.get("severity"),
        "message": finding.get("message"),
        "evidence": {
            key: evidence[key]
            for key in (
                "source_phrase",
                "matched_wrong_rendering",
                "expected",
                "witness",
                "curated_mismatches",
                "missing",
                "reference",
                "source_unit_ids",
            )
            if key in evidence
        },
    }


def _prosecutor_flag(flag: dict[str, Any]) -> dict[str, Any]:
    return {
        "token": flag.get("token"),
        "offset": flag.get("offset"),
        "flag_type": flag.get("flag_type"),
        "senses": flag.get("senses", [])[:4],
        "note": str(flag.get("note", ""))[:240],
    }


def _prosecutor_structure(
    structural: dict[str, Any], target: str, relevant_terms: set[str]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Project structure to offsets and relationships without duplicating Latin."""

    relevant: list[dict[str, Any]] = []
    lower: list[dict[str, Any]] = []
    cursor = 0
    for index, sentence in enumerate(structural.get("sentences", []), 1):
        if not isinstance(sentence, dict):
            continue
        latin = str(sentence.get("latin") or "")
        start = target.find(latin, cursor) if latin else -1
        if start < 0 and latin:
            start = target.find(latin)
        end = start + len(latin) if start >= 0 else None
        if end is not None:
            cursor = end
        item: dict[str, Any] = {
            "sentence": index,
            "target_start": start if start >= 0 else None,
            "target_end": end,
            "main_verbs": [
                {key: verb.get(key, "") for key in ("form", "lemma", "mood", "tense", "voice")}
                for verb in sentence.get("main_verbs", [])
                if isinstance(verb, dict)
            ],
        }
        for key in (
            "subject",
            "objects",
            "subordinate_clauses",
            "attachments",
            "referents",
            "idioms",
            "alternatives",
        ):
            if sentence.get(key):
                item[key] = sentence[key]
        terms = {
            word.casefold()
            for word in re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿ]+", latin)
        }
        uncertain = any(
            sentence.get(key)
            for key in ("alternatives", "attachments", "referents")
        ) or bool(
            isinstance(sentence.get("subject"), dict)
            and sentence["subject"].get("uncertain")
        )
        (relevant if uncertain or terms & relevant_terms else lower).append(item)
    for label in ("intrinsic_ambiguity", "context_dependent", "unverified_analyses"):
        for observation in structural.get(label, []):
            if isinstance(observation, dict):
                relevant.append({"observation_type": label, **observation})
    return relevant, lower


def _prosecutor_annotations(chunk: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            key: item[key]
            for key in (
                "annotation_id",
                "type",
                "marker",
                "reference",
                "source_unit_id",
                "clean_offset",
                "value",
            )
            if key in item
        }
        for item in chunk.get("annotations", [])
        if isinstance(item, dict)
    ]


def _render_budgeted_prosecutor(
    chunk: dict[str, Any],
    witness_a: str,
    witness_b: str,
    materials: dict[str, Any],
    *,
    max_evidence_requests: int,
    witness_gate: dict[str, Any] | None,
    notice: str,
) -> str:
    witness_a_section, witness_b_section = _quorum_witness_sections(
        witness_a, witness_b, witness_gate, prosecutor=True
    )
    return f"""You are the adversarial prosecutor for an evidence-first English edition
of St Jerome's Commentary on Ezekiel. Challenge omissions, additions,
subject-object reversal, negation, numbers, lexical sense, attachment,
referents, names, Scripture, textual issues, and unsupported certainty.
Agreement and fluency are not proof. Do not retranslate, manufacture a second
witness, or treat pretrained memory as evidence. Request precise evidence when
an external claim matters.
{_quorum_notice(witness_gate)}

Return minified VALID JSON with exactly: status
(no_issue_found|insufficient_basis_to_challenge|requires_evidence|
grounded_challenge|unresolved), summary, challenges, and evidence_requests.
Each challenge has latin (an exact short target substring), type, severity,
witness_target, claim, visible_basis, and requires_external_evidence. Return at
most 12 distinct challenges and at most {max(0, max_evidence_requests)} evidence
requests, each with kind, query, and reason.
Allowed challenge types: negation|subject_object|number|lexical|attachment|
omission|addition|unsupported_certainty|scripture|proper_name|idiom|
hebrew_greek|textual|chronology|morphology|source_text|internal_consistency|other.
Allowed severities: low|medium|high. Allowed witness targets:
witness_a|witness_b|both|final_question. Allowed evidence kinds:
jerome_phrase|jerome_lemma|scripture|glossary|morphology|semantic_rag|
corpus_related|source_edition|chronology|proper_name|web_research.

INPUT BUDGET NOTICE: {notice}

TARGET LATIN:
<<<
{chunk['target_latin']}

{witness_a_section}

{witness_b_section}

PRIORITIZED NON-PASS DETERMINISTIC FINDINGS:
<<<
{_compact_json(materials['checks'])}

RELEVANT STRUCTURE (target offsets; Latin is not duplicated):
<<<
{_compact_json(materials['structural'])}

RELEVANT LEXICAL FLAGS (full morphology remains in immutable audit):
<<<
{_compact_json(materials['flags'])}

SOURCE ANNOTATION REFERENCES (source text omitted):
<<<
{_compact_json(materials['annotations'])}

OPTIONAL READ-ONLY CONTEXT:
<<<
{materials['context_before'] or '[None]'}
---
{materials['context_after'] or '[None]'}
"""


def budgeted_prosecutor_prompt(
    chunk: dict[str, Any],
    structural: dict[str, Any],
    lexical: dict[str, Any],
    checks: dict[str, Any],
    witness_a: str,
    witness_b: str,
    *,
    max_evidence_requests: int,
    budget: dict[str, Any],
    witness_gate: dict[str, Any] | None = None,
) -> BudgetedProsecutorPrompt:
    """Build a prioritized bounded request; mandatory overflow returns no prompt."""

    max_prompt_bytes = int(budget.get("max_prompt_utf8_bytes", 44_000))
    max_request_bytes = int(budget.get("max_request_utf8_bytes", 44_000))
    max_tokens = int(budget.get("max_estimated_prompt_tokens", 16_000))
    bytes_per_token = float(budget.get("estimator_bytes_per_token", 2.75))
    if min(max_prompt_bytes, max_request_bytes, max_tokens) <= 0 or bytes_per_token <= 0:
        raise ValueError("Prosecutor input budget limits must be positive")

    visible = _quorum_filtered_checks(checks, witness_gate)
    non_pass = [
        item for item in visible.get("findings", [])
        if isinstance(item, dict) and item.get("status") != "pass"
    ]
    high = [item for item in non_pass if item.get("severity") == "high"]
    lower_findings = [item for item in non_pass if item.get("severity") != "high"]
    terms = _prosecutor_terms(non_pass)
    all_flags = [item for item in lexical.get("flags", []) if isinstance(item, dict)]
    mandatory_flags = [
        item for item in all_flags
        if item.get("flag_type") == "known_trap"
        or str(item.get("token") or "").casefold() in terms
    ]
    optional_flags = [
        item for item in all_flags
        if item not in mandatory_flags
        and item.get("flag_type") in {"ambiguous_senses", "not_found"}
    ]
    relevant_structure, lower_structure = _prosecutor_structure(
        structural, str(chunk.get("target_latin") or ""), terms
    )
    materials: dict[str, Any] = {
        "checks": [_prosecutor_finding(item) for item in high],
        # Every directly relevant/known-trap flag is mandatory. If that core
        # cannot fit, preflight fails closed rather than silently dropping the
        # 25th high-value lexical record.
        "flags": [_prosecutor_flag(item) for item in mandatory_flags],
        "structural": relevant_structure[:16],
        "annotations": _prosecutor_annotations(chunk)[:16],
        "context_before": "",
        "context_after": "",
    }
    admitted: list[str] = []

    def render() -> str:
        notice = ", ".join(admitted) if admitted else "mandatory core only"
        return _render_budgeted_prosecutor(
            chunk, witness_a, witness_b, materials,
            max_evidence_requests=max_evidence_requests,
            witness_gate=witness_gate,
            notice=notice,
        )

    def measure(prompt: str) -> dict[str, int]:
        return _prompt_measurement(prompt, response_schema={}, bytes_per_token=bytes_per_token)

    def fits(value: dict[str, int]) -> bool:
        return (
            value["prompt_utf8_bytes"] <= max_prompt_bytes
            and value["request_utf8_bytes"] <= max_request_bytes
            and value["estimated_prompt_tokens"] <= max_tokens
        )

    historical = measure(
        prosecutor_prompt(
            chunk, structural, lexical, checks, witness_a, witness_b,
            max_evidence_requests=max_evidence_requests,
            witness_gate=witness_gate,
        )
    )
    prompt = render()
    mandatory = measure(prompt)
    limits = {
        "max_prompt_utf8_bytes": max_prompt_bytes,
        "max_request_utf8_bytes": max_request_bytes,
        "max_estimated_prompt_tokens": max_tokens,
        "estimator_bytes_per_token": bytes_per_token,
    }
    if not fits(mandatory):
        return BudgetedProsecutorPrompt(
            prompt=None,
            receipt={
                "policy": "prosecutor_input_budget",
                "policy_version": PROSECUTOR_INPUT_BUDGET_POLICY_VERSION,
                "limits": limits,
                "historical_unbounded": historical,
                "mandatory": mandatory,
                "final": mandatory,
                "fits": False,
                "failure_reason": "Mandatory prosecutor material exceeds the configured safe input budget.",
            },
        )

    tiers = [
        ("non_high_non_pass_findings", "checks", [_prosecutor_finding(item) for item in lower_findings[:12]]),
        ("ambiguous_or_unresolved_lexical_flags", "flags", [_prosecutor_flag(item) for item in optional_flags[:24]]),
        ("remaining_compact_structural_relationships", "structural", lower_structure[:12]),
    ]
    for name, component, additions in tiers:
        if not additions:
            continue
        original = list(materials[component])
        materials[component] = original + additions
        candidate = render()
        if fits(measure(candidate)):
            prompt = candidate
            admitted.append(name)
        else:
            materials[component] = original

    before = str(chunk.get("context_before") or "")[-400:]
    after = str(chunk.get("context_after") or "")[:400]
    materials["context_before"], materials["context_after"] = before, after
    candidate = render()
    if fits(measure(candidate)):
        prompt = candidate
        admitted.append("bounded_read_only_context_400_chars_each")
    else:
        materials["context_before"] = materials["context_after"] = ""
        prompt = render()

    final = measure(prompt)
    supplied_sections = _quorum_witness_sections(
        witness_a, witness_b, witness_gate, prosecutor=True
    )
    witness_a_supplied = "[TEXT WITHHELD" not in supplied_sections[0]
    witness_b_supplied = "[TEXT WITHHELD" not in supplied_sections[1]
    component_utf8_bytes = {
        "target_latin": len(str(chunk.get("target_latin") or "").encode("utf-8")),
        "witness_a": len(witness_a.encode("utf-8")) if witness_a_supplied else 0,
        "witness_b": len(witness_b.encode("utf-8")) if witness_b_supplied else 0,
        "deterministic_findings": len(
            _compact_json(materials["checks"]).encode("utf-8")
        ),
        "structural": len(_compact_json(materials["structural"]).encode("utf-8")),
        "lexical_flags": len(_compact_json(materials["flags"]).encode("utf-8")),
        "annotations": len(_compact_json(materials["annotations"]).encode("utf-8")),
        "context": len(
            (
                str(materials["context_before"])
                + str(materials["context_after"])
            ).encode("utf-8")
        ),
    }
    component_utf8_bytes["boilerplate_and_section_labels"] = max(
        0, final["prompt_utf8_bytes"] - sum(component_utf8_bytes.values())
    )
    receipt = {
        "policy": "prosecutor_input_budget",
        "policy_version": PROSECUTOR_INPUT_BUDGET_POLICY_VERSION,
        "limits": limits,
        "historical_unbounded": historical,
        "mandatory": mandatory,
        "final": final,
        "priority_tiers_included": admitted,
        "component_utf8_bytes": component_utf8_bytes,
        "included": {
            "high_findings": len(high),
            "non_high_findings": max(0, len(materials["checks"]) - len(high)),
            "lexical_flags": len(materials["flags"]),
            "structural_records": len(materials["structural"]),
            "annotations": len(materials["annotations"]),
            "context_chars": len(materials["context_before"]) + len(materials["context_after"]),
        },
        "filtered": {
            "findings": max(0, len(non_pass) - len(materials["checks"])),
            "lexical_flags": max(0, len(all_flags) - len(materials["flags"])),
            "structural_sentence_records": max(0, len(structural.get("sentences", [])) - len([item for item in materials["structural"] if "sentence" in item])),
            "annotations": max(0, len(chunk.get("annotations", [])) - len(materials["annotations"])),
            "reason": "Only non-pass, dispute-relevant, ambiguity-bearing, or explicitly bounded components enter the model-facing view.",
        },
        "preserved": {
            "target_latin_chars": len(str(chunk.get("target_latin") or "")),
            "witness_a_chars_supplied": len(witness_a) if witness_a_supplied else 0,
            "witness_b_chars_supplied": len(witness_b) if witness_b_supplied else 0,
            "invalid_witnesses_withheld": list((witness_gate or {}).get("invalid_witnesses") or []) if (witness_gate or {}).get("mode") == "degraded" else [],
            "high_severity_finding_ids": [
                item.get("finding_id") or item.get("check") or "deterministic"
                for item in high
            ],
            "known_trap_tokens": [item.get("token") for item in mandatory_flags if item.get("flag_type") == "known_trap"],
        },
        "fits": fits(final),
    }
    if not receipt["fits"]:
        receipt["failure_reason"] = "Prioritized prosecutor prompt exceeded its configured safe input budget."
        return BudgetedProsecutorPrompt(prompt=None, receipt=receipt)
    return BudgetedProsecutorPrompt(prompt=prompt, receipt=receipt)


def grounded_prosecutor_prompt(
    chunk: dict[str, Any], initial: dict[str, Any], evidence: list[dict[str, Any]]
) -> str:
    return f"""Ground the earlier prosecutor report using ONLY the receipts supplied below.

Do not treat a model assertion as evidence. Distinguish `no_evidence_found`
from an unavailable subsystem. A retrieved Latin occurrence is evidence that
text exists, but its interpretation may remain uncertain. CPDV is comparison
help, not Latin authority. External research leads are not verified evidence.
Withdraw or mark unresolved any allegation the receipts do not support.

Return the same VALID JSON prosecutor schema as minified one-line JSON, with
concrete receipt IDs cited inside `visible_basis` or the claim marked
unresolved. New evidence requests must be empty because this is the bounded
grounding round.

TARGET LATIN:
<<<
{chunk['target_latin']}

INITIAL PROSECUTOR REPORT:
<<<
{_compact_json(initial)}

RETRIEVED EVIDENCE RECEIPTS:
<<<
{_compact_json(evidence)}
"""


def _render_adjudicator_prompt(
    chunk: dict[str, Any],
    witness_a: str,
    witness_b: str,
    compact_structural: dict[str, Any],
    compact_flags: list[dict[str, Any]],
    compact_checks: dict[str, Any],
    prosecutor: dict[str, Any],
    compact_evidence: list[dict[str, Any]],
    *,
    context_before: str,
    context_after: str,
    compaction_notice: str,
    dense_json: bool = False,
    witness_gate: dict[str, Any] | None = None,
) -> str:
    render_json = _compact_json if dense_json else _pretty
    witness_a_section, witness_b_section = _quorum_witness_sections(
        witness_a, witness_b, witness_gate, prosecutor=False
    )
    allowed_bases = (witness_gate or {}).get("allowed_base_witnesses") or ["a", "b"]
    base_contract = "|".join(allowed_bases)
    permitted_base_text = ", ".join(
        f"Witness {item.upper()}" for item in allowed_bases
    )
    return f"""You are the final evidence-aware adjudicator for St Jerome's Commentary on
Ezekiel. Decide from the authoritative TARGET LATIN; do not majority-vote.

Evidence hierarchy:
A. deterministic/source-verifiable evidence;
B. retrieved corpus evidence requiring interpretation;
C. model inference grounded in visible Latin/context;
D. unsupported model claim.

Human-approved editorial precedents are separate project consistency guidance.
They may support consistent English wording but are not automatically grade A
or B evidence and never overrule the authoritative target Latin.

Agreement is weak evidence. Fluency is not evidence. Source-backed evidence
outranks unsupported claims. Serious issues must not be resolved solely from C
or D. Do not invent Scripture references, Jerome usage, lexicon facts,
history, chronology, or citations. Preserve unresolved ambiguity instead of
forcing a choice. Check target coverage clause by clause.
A/B evidence must support each cited finding; it never supports another.
{_quorum_notice(witness_gate)}

EDIT PRECISION EXAMPLES:
These examples illustrate the exacting standard required. Study them carefully.

Example 1 — Unique exact span (CORRECT):
Selected witness: "He did not come. He has not arrived."
Edit: {{"old": "He did not come.", "new": "He did not arrive.", "reason": "Consistent verb choice.", "evidence_ids": ["ev-1"]}}
Rationale: "He did not come." occurs exactly once. Clear, unambiguous.

Example 2 — Repeated phrase with disambiguating context (CORRECT):
Selected witness: "The man saw the light. The light was bright."
Edit: {{"old": "The man saw the light.", "new": "The man beheld the light.", "reason": "More precise verb.", "evidence_ids": ["ev-2"]}}
Rationale: "the light" appears twice but "The man saw the light." occurs once. Sufficient context included.

Example 3 — Ambiguous repeated span without disambiguation (INCORRECT — DO NOT DO THIS):
Selected witness: "light appears. light is good."
WRONG edit: {{"old": "light", "new": "lux", "reason": "Latin term.", "evidence_ids": []}}
Rationale: "light" occurs twice (or more). Software will reject. If you cannot include enough context to make the span unique, DO NOT GUESS. Return "human_review" or "unresolved" for that phrase with the exact substring and the specific check a human must perform.

Example 4 — Sequential edits against evolving base (CORRECT):
Selected witness: "He did not come. He has not arrived."
Edit 1: {{"old": "He did not come.", "new": "He did not arrive.", "reason": "Consistent verb.", "evidence_ids": ["ev-3"]}}
Edit 2: {{"old": "He has not arrived.", "new": "He has not come.", "reason": "Second verb aligned.", "evidence_ids": ["ev-4"]}}
Rationale: After Edit 1, the evolving base is "He did not arrive. He has not arrived." Edit 2's "old" matches the SECOND sentence in that evolving base exactly once. Each old matches the current draft state at its application point.

Example 5 — Sequential edit using stale reference (INCORRECT — DO NOT DO THIS):
Selected witness: "A B C"
WRONG edits: [{{"old": "B", "new": "X"}}, {{"old": "C", "new": "Y"}}] where "C" appears twice in original but once in evolving base after first edit.
Rationale: If "C" appears in original before and after "B", the second edit's "old" must match the evolving base after the first edit, not the original. Verify each "old" against the draft state at its turn.

KEY RULES:
- Each "old" MUST occur exactly ONCE in the evolving base at its application point.
- Include enough surrounding text to make the span unique (sentence-level or clause-level).
- Copy "old" byte-for-byte from the SELECTED witness only.
- If you cannot construct a unique span for a necessary change, return "human_review" or "unresolved" for that specific phrase with the exact substring and the exact check a human should perform. NEVER guess or use ambiguous spans.
- Empty edits array means the selected witness needs no change.

Statuses:
- accepted: a complete best draft with no substantive correction required;
- corrected: provide revised English and precise reasons;
- unresolved: preserve competing interpretations and missing evidence;
- human_review: identify an exact phrase/construction/source issue and exact
  check a human should perform, never a generic warning.

You may request targeted evidence only if it could materially change the
decision. Requests are bounded by software. Preserve complete target coverage
by selecting one complete permitted base ({permitted_base_text}) as
`base_witness`. Do not
rewrite or repeat the full translation. Supply only necessary exact substring
edits against that base, in application order. Each `old` value must occur
exactly once in the evolving base. Copy every `old` value byte-for-byte from
the SELECTED witness only; never use wording found only in the unselected
witness. Re-read the selected witness and verify each exact occurrence before
returning. Use an empty edits array when the selected witness needs no change.
Software applies the edits and preserves all other base text. Return VALID
JSON ONLY:
{{
  "status": "accepted|corrected|unresolved|human_review",
  "base_witness": "{base_contract}",
  "edits": [{{"old":"exact unique substring from selected/evolving witness", "new":"replacement text", "reason":"", "evidence_ids":[]}}],
  "summary": "precise decision summary",
  "coverage": {{"all_clauses_accounted_for": true, "omissions_corrected": []}},
  "findings": [{{"latin":"exact substring", "english":"exact final wording", "type":"negation|subject_object|number|lexical|attachment|omission|addition|unsupported_certainty|scripture|proper_name|idiom|hebrew_greek|textual|chronology|morphology|source_text|internal_consistency|other", "severity":"low|medium|high", "resolution":"", "reason":"", "evidence_ids":[]}}],
  "unresolved_issues": [{{"latin":"exact substring", "english":"provisional wording or empty", "alternatives":[], "missing_evidence":""}}],
  "human_review_requests": [{{"latin":"exact substring", "english":"provisional wording or empty", "issue":"", "action":"specific source/construction to inspect"}}],
  "evidence_requests": [{{"kind":"jerome_phrase|jerome_lemma|scripture|glossary|morphology|semantic_rag|corpus_related|source_edition|chronology|proper_name|web_research", "query":"", "reason":""}}],
  "decision_basis": [{{"grade":"A|B|C|D", "claim":"", "evidence_ids":[]}}]
}}

INPUT BUDGET NOTICE:
{compaction_notice}

TARGET LATIN:
<<<
{chunk['target_latin']}

READ-ONLY CONTEXT:
<<<
{context_before or '[None]'}
---
{context_after or '[None]'}

{witness_a_section}

{witness_b_section}

COMPACT ORIGINAL BLIND STRUCTURAL PARSE (full record is persisted separately):
<<<
{render_json(compact_structural)}

RELEVANT DETERMINISTIC LEXICAL FLAGS (full morphology is persisted separately):
<<<
{render_json(compact_flags)}

COMPACT DETERMINISTIC CHECKS (warnings plus number-equivalence receipts):
<<<
{render_json(compact_checks)}

GROUNDED PROSECUTOR RESULT:
<<<
{render_json(prosecutor)}

COMPACT RELEVANT RETRIEVED EVIDENCE (full receipts are persisted separately):
<<<
{render_json(compact_evidence)}
"""


def adjudicator_prompt(
    chunk: dict[str, Any],
    witness_a: str,
    witness_b: str,
    structural: dict[str, Any],
    lexical: dict[str, Any],
    checks: dict[str, Any],
    prosecutor: dict[str, Any],
    evidence: list[dict[str, Any]],
    witness_gate: dict[str, Any] | None = None,
) -> str:
    """Render the historical compact prompt without applying a provider guard.

    Live orchestration must use :func:`budgeted_adjudicator_prompt`; this
    wrapper remains useful for deterministic inspection and compatibility.
    """

    return _render_adjudicator_prompt(
        chunk,
        witness_a,
        witness_b,
        _compact_adjudicator_structural(structural),
        _compact_adjudicator_flags(lexical, prosecutor),
        _compact_adjudicator_checks(_quorum_filtered_checks(checks, witness_gate)),
        prosecutor,
        _compact_adjudicator_evidence(evidence),
        context_before=str(chunk.get("context_before") or ""),
        context_after=str(chunk.get("context_after") or ""),
        compaction_notice="No additional budget compaction was applied.",
        witness_gate=witness_gate,
    )


def budgeted_adjudicator_prompt(
    chunk: dict[str, Any],
    witness_a: str,
    witness_b: str,
    structural: dict[str, Any],
    lexical: dict[str, Any],
    checks: dict[str, Any],
    prosecutor: dict[str, Any],
    evidence: list[dict[str, Any]],
    *,
    response_schema: dict[str, Any],
    budget: dict[str, Any],
    witness_gate: dict[str, Any] | None = None,
) -> BudgetedAdjudicatorPrompt:
    """Build an adjudicator prompt that cannot silently exceed configured limits.

    Target Latin, every quorum-eligible witness, prosecutor objections, every
    eligible non-pass deterministic finding, and the compact receipts
    referenced by a high-severity objection are mandatory. Invalid witness text
    is retained in audit but withheld from degraded-mode model requests.
    Lower-priority material is reduced in a fixed order. If the mandatory core
    does not fit, ``prompt`` is ``None`` and callers must fail before invoking a
    provider.
    """

    max_prompt_bytes = int(budget.get("max_prompt_utf8_bytes", 45_000))
    max_request_bytes = int(budget.get("max_request_utf8_bytes", 52_000))
    max_tokens = int(budget.get("max_estimated_prompt_tokens", 15_000))
    bytes_per_token = float(budget.get("estimator_bytes_per_token", 3.0))
    if min(max_prompt_bytes, max_request_bytes, max_tokens) <= 0:
        raise ValueError("Adjudicator input budget limits must be positive")
    if bytes_per_token <= 0:
        raise ValueError("adjudicator_input_budget.estimator_bytes_per_token must be positive")

    decisive_ids = set(_decisive_evidence_ids(prosecutor))
    materials: dict[str, Any] = {
        "context_before": str(chunk.get("context_before") or ""),
        "context_after": str(chunk.get("context_after") or ""),
        "structural": _compact_adjudicator_structural(structural),
        "flags": _compact_adjudicator_flags(lexical, prosecutor),
        "checks": _compact_adjudicator_checks(
            _quorum_filtered_checks(checks, witness_gate)
        ),
        "prosecutor": prosecutor,
        "evidence": _compact_budget_evidence(
            evidence, decisive_ids, summarize_lower=False
        ),
        "dense_json": False,
    }
    steps: list[str] = []

    def render() -> str:
        notice = (
            "Deterministic budget compaction applied: " + ", ".join(steps) + "."
            if steps
            else "No additional budget compaction was applied."
        )
        return _render_adjudicator_prompt(
            chunk,
            witness_a,
            witness_b,
            materials["structural"],
            materials["flags"],
            materials["checks"],
            materials["prosecutor"],
            materials["evidence"],
            context_before=materials["context_before"],
            context_after=materials["context_after"],
            compaction_notice=notice,
            dense_json=materials["dense_json"],
            witness_gate=witness_gate,
        )

    def fits(measurement: dict[str, int]) -> bool:
        return (
            measurement["prompt_utf8_bytes"] <= max_prompt_bytes
            and measurement["request_utf8_bytes"] <= max_request_bytes
            and measurement["estimated_prompt_tokens"] <= max_tokens
        )

    prompt = render()
    initial = _prompt_measurement(
        prompt,
        response_schema=response_schema,
        bytes_per_token=bytes_per_token,
    )
    final = initial
    transformations = [
        (
            "trim_read_only_context_to_600_chars_each",
            lambda: materials.update(
                {
                    "context_before": materials["context_before"][-600:],
                    "context_after": materials["context_after"][:600],
                }
            ),
        ),
        (
            "structural_uncertainty_and_challenged_verbs_only",
            lambda: materials.update(
                {"structural": _compact_structural_issues(structural, prosecutor)}
            ),
        ),
        (
            "non_pass_deterministic_findings_only",
            lambda: materials.update(
                {"checks": _compact_deterministic_issues(checks)}
            ),
        ),
        (
            "lower_priority_evidence_summarized",
            lambda: materials.update(
                {
                    "evidence": _compact_budget_evidence(
                        evidence, decisive_ids
                    )
                }
            ),
        ),
        (
            "non_trap_lexical_flags_reduced",
            lambda: materials.update(
                {"flags": _compact_budget_flags(lexical, prosecutor)}
            ),
        ),
        (
            "prosecutor_summary_and_empty_requests_removed",
            lambda: materials.update(
                {
                    "prosecutor": {
                        "status": prosecutor.get("status"),
                        "challenges": prosecutor.get("challenges", []),
                        "evidence_requests": prosecutor.get("evidence_requests", []),
                    }
                }
            ),
        ),
        (
            "dense_json_encoding_without_semantic_loss",
            lambda: materials.update({"dense_json": True}),
        ),
    ]
    for name, transform in transformations:
        if fits(final):
            break
        transform()
        steps.append(name)
        prompt = render()
        final = _prompt_measurement(
            prompt,
            response_schema=response_schema,
            bytes_per_token=bytes_per_token,
        )

    receipt: dict[str, Any] = {
        "policy": "adjudicator_input_budget",
        "policy_version": ADJUDICATOR_INPUT_BUDGET_POLICY_VERSION,
        "limits": {
            "max_prompt_utf8_bytes": max_prompt_bytes,
            "max_request_utf8_bytes": max_request_bytes,
            "max_estimated_prompt_tokens": max_tokens,
            "estimator_bytes_per_token": bytes_per_token,
        },
        "initial": initial,
        "final": final,
        "compaction_steps": steps,
        "serialization": "dense_json" if materials["dense_json"] else "pretty_json",
        "preserved": {
            "target_latin_chars": len(str(chunk.get("target_latin") or "")),
            "witness_a_chars_supplied": (
                len(witness_a)
                if not witness_gate
                or witness_gate.get("mode") != "degraded"
                or "witness_a" in (witness_gate.get("valid_witnesses") or [])
                else 0
            ),
            "witness_b_chars_supplied": (
                len(witness_b)
                if not witness_gate
                or witness_gate.get("mode") != "degraded"
                or "witness_b" in (witness_gate.get("valid_witnesses") or [])
                else 0
            ),
            "invalid_witnesses_withheld": (
                list(witness_gate.get("invalid_witnesses") or [])
                if witness_gate and witness_gate.get("mode") == "degraded"
                else []
            ),
            "prosecutor_challenges": len(prosecutor.get("challenges", [])),
            "non_pass_deterministic_findings": len(
                [
                    item
                    for item in checks.get("findings", [])
                    if isinstance(item, dict) and item.get("status") != "pass"
                ]
            ),
            "decisive_evidence_ids": sorted(decisive_ids),
        },
        "fits": fits(final),
    }
    if not receipt["fits"]:
        receipt["failure_reason"] = (
            "Mandatory adjudicator material exceeds the configured safe input budget "
            "after every permitted lower-priority compaction step."
        )
        return BudgetedAdjudicatorPrompt(prompt=None, receipt=receipt)
    return BudgetedAdjudicatorPrompt(prompt=prompt, receipt=receipt)
