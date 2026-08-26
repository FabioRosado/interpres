from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from typing import Any

from .source import split_sentences


ADJUDICATOR_INPUT_BUDGET_POLICY_VERSION = 2


@dataclass(frozen=True)
class BudgetedAdjudicatorPrompt:
    """A provider-ready prompt plus an auditable, deterministic budget receipt."""

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
    source_units_data = [
        item for item in chunk.get("source_units", []) if isinstance(item, dict)
    ]
    source_units = "\n".join(
        f'<SOURCE_UNIT id="{item["source_unit_id"]}">\n{item["text"]}\n</SOURCE_UNIT>'
        for item in source_units_data
        if item.get("source_unit_id") and isinstance(item.get("text"), str)
    )
    if not source_units:
        fallback_ids = (chunk.get("source") or {}).get("source_unit_ids") or [
            chunk.get("chunk_id", "target")
        ]
        source_units = (
            f'<SOURCE_UNIT id="{fallback_ids[0]}">\n{chunk["target_latin"]}\n'
            "</SOURCE_UNIT>"
        )
    return f"""Translate the TARGET Latin source units from St Jerome into accurate English.

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
- Read-only context may resolve discourse, but MUST NOT be translated as target.
- Source-unit boundaries may split a sentence. Translate the supplied fragment
  exactly; never complete it from the read-only context.
- Produce one coherent full-context translation, not independent per-unit prose.
- Return only one JSON object. `translation` is the coherent translation.
  `source_mappings` is an audit receipt, not a second translation: include every
  source-unit ID exactly once and in order. For each unit provide only a short
  `english_end_quote` of 3-12 words (100 characters maximum) copied exactly from
  the end of that unit's rendering. Do not duplicate paragraphs in mappings.
  The final end quote must end `translation`. Report any genuinely
  untranslated source in `omissions`; otherwise use an empty list.

<TARGET_LATIN translate="all_and_only">
{source_units or chunk['target_latin']}
</TARGET_LATIN>

The target above is the only text to translate. The material below appears
after the target deliberately and is reference-only. Never copy, translate,
complete, or continue into it.

<READ_ONLY_CONTEXT_BEFORE translate="false">
{chunk.get('context_before') or '[None]'}
</READ_ONLY_CONTEXT_BEFORE>

<READ_ONLY_CONTEXT_AFTER translate="false">
{chunk.get('context_after') or '[None]'}
</READ_ONLY_CONTEXT_AFTER>

Required JSON shape:
{{
  "translation": "one complete coherent English translation",
  "source_mappings": [
    {{
      "source_unit_id": "exact supplied ID",
      "english_end_quote": "short exact quote ending this unit's rendering"
    }}
  ],
  "omissions": [],
  "uncertainties": []
}}
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
) -> str:
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
- Return at most 12 distinct substantive challenges. Consolidate overlapping
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

WITNESS A (independent):
<<<
{witness_a}

WITNESS B (independent):
<<<
{witness_b}

BLIND STRUCTURAL PARSE (immutable original):
<<<
{_compact_json(structural)}

COMPACT LEXICAL FLAGS (full deterministic morphology is stored separately):
<<<
{_compact_json(lexical.get('flags', []))}

DETERMINISTIC CHECKS:
<<<
{_compact_json(checks)}

SOURCE ANNOTATIONS:
<<<
{_compact_json(chunk.get('annotations', []))}
"""


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
) -> str:
    render_json = _compact_json if dense_json else _pretty
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

Statuses:
- accepted: a complete best draft with no substantive correction required;
- corrected: provide revised English and precise reasons;
- unresolved: preserve competing interpretations and missing evidence;
- human_review: identify an exact phrase/construction/source issue and exact
  check a human should perform, never a generic warning.

You may request targeted evidence only if it could materially change the
decision. Requests are bounded by software. Preserve complete target coverage
by selecting all of Witness A or all of Witness B as `base_witness`. Do not
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
  "base_witness": "a|b",
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

WITNESS A:
<<<
{witness_a}

WITNESS B:
<<<
{witness_b}

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
        _compact_adjudicator_checks(checks),
        prosecutor,
        _compact_adjudicator_evidence(evidence),
        context_before=str(chunk.get("context_before") or ""),
        context_after=str(chunk.get("context_after") or ""),
        compaction_notice="No additional budget compaction was applied.",
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
) -> BudgetedAdjudicatorPrompt:
    """Build an adjudicator prompt that cannot silently exceed configured limits.

    Target Latin, both complete witnesses, prosecutor objections, every
    non-pass deterministic finding, and the compact receipts referenced by a
    high-severity objection are mandatory. Lower-priority material is reduced
    in a fixed order. If the mandatory core does not fit, ``prompt`` is ``None``
    and callers must fail before invoking a provider.
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
        "checks": _compact_adjudicator_checks(checks),
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
            "witness_a_chars": len(witness_a),
            "witness_b_chars": len(witness_b),
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
