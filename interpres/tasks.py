from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .config import PipelineConfig
from .source import split_sentences


@dataclass(frozen=True)
class TaskProfile:
    """Small project/task adapter for behavior that is not engine-generic."""

    project_id: str
    task_type: str
    operation_label: str
    source_language: str
    target_language: str
    source_label: str
    target_label: str
    morphology_enabled: bool
    structural_enabled: bool

    @classmethod
    def from_config(cls, config: PipelineConfig) -> "TaskProfile":
        return cls(
            project_id=config.project_id,
            task_type=config.task_type,
            operation_label=config.operation_label,
            source_language=config.source_language,
            target_language=config.target_language,
            source_label=config.source_label,
            target_label=config.target_label,
            morphology_enabled=config.stage_enabled("morphology"),
            structural_enabled=config.stage_enabled("structural_parse"),
        )

    @property
    def is_modernization(self) -> bool:
        return self.task_type == "modernization"

    @property
    def is_translation(self) -> bool:
        return self.task_type == "translation"

    @property
    def source_field_label(self) -> str:
        return "latin" if self.is_translation and self.source_language == "la" else "source"

    @property
    def final_noun(self) -> str:
        return "modernization" if self.is_modernization else "translation"

    def source_text(self, chunk: dict[str, Any]) -> str:
        value = chunk.get("source_text")
        if isinstance(value, str):
            return value
        return str(chunk.get("target_latin") or "")

    def skipped_morphology_output(self) -> dict[str, Any]:
        return {
            "backend": {"name": "disabled", "contract": "not_applicable"},
            "morphology": [],
            "flags": [],
            "status": "skipped",
            "reason": f"Morphology is disabled for {self.task_type}.",
        }

    def skipped_structural_output(self, chunk: dict[str, Any]) -> dict[str, Any]:
        return {
            "sentences": [],
            "intrinsic_ambiguity": [],
            "context_dependent": [],
            "unverified_analyses": [],
            "status": "skipped",
            "reason": f"Latin structural parsing is disabled for {self.task_type}.",
            "source_sentence_count": len(split_sentences(self.source_text(chunk))),
        }

    def witness_prompt(self, chunk: dict[str, Any]) -> str:
        source = self.source_text(chunk)
        if self.is_modernization:
            return f"""Conservatively modernize this historical English passage into clear contemporary literary/theological English.

Core task:
- Edit only what a modern reader genuinely needs modernized.
- This is not a rewrite, paraphrase, literary polish, style variation, or restoration of older English.
- Prefer the smallest change necessary to make genuinely archaic or obsolete English read naturally to a modern reader.
- If two phrasings are equally clear and faithful, choose the one closer to the source.
- A good modernization may be almost identical to the source.

Priorities:
- Preserve every clause, claim, contrast, negation, number, name, Scripture reference, quotation, and theological term.
- Modernize genuinely archaic pronouns, obsolete verb forms, obsolete spellings, archaic syntax, unnecessarily archaic prepositions, and words whose old form is no longer normal contemporary English.
- Preserve already-modern wording exactly unless a change is necessary for grammar, clarity, obsolete meaning, genuinely archaic syntax, or semantic accuracy.
- Never introduce archaic forms that were absent from the source unless reproducing a span explicitly marked protected/verbatim in project metadata.
- Do not summarize, paraphrase, embellish, synonym-swap, vary vocabulary, simplify doctrine, imitate Victorian prose, imitate biblical archaism, or make the text conversational.
- Do not make the prose more literary, more Victorian, more biblical, or more modern than necessary.
- Preserve the author's argument, rhetorical force, structure, tone, paragraph/section completeness, and repeated phrases where repetition appears intentional.
- Quotation marks alone do not protect historical English. Modernize ordinary quoted text too; preserve wording verbatim only for spans explicitly marked protected/verbatim in project metadata.
- Leave already-clear contemporary English unchanged.
- If genuinely uncertain, mark `[UNCERTAIN: precise explanation]`.
- Return only the continuous modernized English text. Do not return JSON, headings, commentary, notes, source-unit markers, or Markdown fences.

Task direction:
- The direction is historical/archaic English -> modern English. Never move backward into older English.
- Treat reverse modernization as a task-direction error, not a style preference.
- Forbidden introduced forms include thou, thee, thy, thine, hath, doth, saith, mayest, hast, shalt, wilt, wherein, unto, and shew outside explicitly protected spans.
- Forbidden examples: says -> saith; has -> hath; have -> hast; show -> shew; to -> unto; you -> thou.

Examples:
SOURCE: And that thou mayest learn that this was far better, hear what He saith by the Prophet.
GOOD: And that you may learn that this was far better, hear what He says through the Prophet.
BAD: And so that you can understand this better, consider what the Prophet tells us.

SOURCE: But if there were any hostility in their statements, neither would the sects have received all.
GOOD: But if there were any hostility in their statements, neither would the sects have received all.
BAD: But if their statements had shown hostility, the sects would not have accepted everything.

SOURCE: For many sects have arisen since their time.
GOOD: For many sects have arisen since their time.
BAD: For many sects had birth since their time.

SOURCE: Some have separated a portion.
GOOD: Some have separated a portion.
BAD: Some have parted off a portion.

SOURCE: For he says that this is manifest.
GOOD: For he says that this is manifest.
BAD: For he saith that this is manifest.

SOURCE: “that thou mayest hold,” saith he, “the certainty of the words wherein thou hast been instructed;”
GOOD: “that you may hold,” he says, “the certainty of the words in which you have been instructed;”
BAD: “that thou mayest hold,” saith he, “the certainty of the words wherein thou hast been instructed;”

SOURCE: God hath made manifest both by His words and by His doings.
GOOD: God has made manifest both by His words and by His deeds.
BAD: God clearly demonstrated this through everything He said and did.

<SOURCE_TEXT modernize="all_and_only">
{source}
</SOURCE_TEXT>

The source above is the complete request. Do not infer or continue text beyond
its beginning or end, even when a quotation or sentence fragment is incomplete.
"""
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
{source}
</TARGET_LATIN>

The target above is the complete request. Do not infer or continue text beyond
its beginning or end, even when a quotation or sentence fragment is incomplete.
"""

    def prosecutor_brief(self) -> dict[str, str]:
        if self.is_modernization:
            return {
                "role": (
                    "You are the adversarial prosecutor for an evidence-first "
                    "historical-English modernization."
                ),
                "focus": (
                    "Challenge omissions, additions, meaning shifts, weakened "
                    "theological terms, altered Scripture references or quotations, "
                    "lost negation, altered numbers/names, archaic residue, archaic "
                    "introduction, reverse-modernization direction errors, less-modern "
                    "synonyms, unnecessary lexical churn, unnecessary stylistic rewriting, "
                    "lexical traps, paraphrase, lost rhetorical structure, and "
                    "over-modernization. Ask whether the witness changed already-modern "
                    "wording without a clear modernization need; preserved archaic "
                    "wording merely because it appeared inside quotation marks; "
                    "introduced archaic English absent from the source; chose a less modern synonym; "
                    "paraphrased rather than modernized; or could have safely left the "
                    "source wording unchanged. Agreement and fluency are not proof, and "
                    "unchanged text may be the best result."
                ),
                "source_heading": "SOURCE HISTORICAL ENGLISH",
                "structure_label": "STRUCTURAL PARSE (may be skipped for this task)",
                "lexical_label": "LEXICAL FLAGS (project-specific where available)",
                "evidence_kinds": "semantic_rag|corpus_related|source_edition|web_research",
                "challenge_types": (
                    "negation|subject_object|number|lexical|attachment|omission|"
                    "addition|unsupported_certainty|scripture|proper_name|idiom|"
                    "textual|source_text|internal_consistency|meaning_shift|"
                    "paraphrase|preposition|theological_term|archaic_residue|archaic_introduction|"
                    "reverse_modernization|over_modernization|rhetorical_structure|"
                    "quotation|other"
                ),
            }
        return {
            "role": (
                "You are the adversarial prosecutor for an evidence-first English "
                "edition of St Jerome's Commentary on Ezekiel."
            ),
            "focus": (
                "Challenge omissions, additions, subject-object reversal, negation, "
                "numbers, lexical sense, attachment, referents, names, Scripture, "
                "textual issues, and unsupported certainty."
            ),
            "source_heading": "TARGET LATIN",
            "structure_label": "RELEVANT STRUCTURE (target offsets; Latin is not duplicated)",
            "lexical_label": "RELEVANT LEXICAL FLAGS (full morphology remains in immutable audit)",
            "evidence_kinds": (
                "jerome_phrase|jerome_lemma|scripture|glossary|morphology|"
                "semantic_rag|corpus_related|source_edition|chronology|proper_name|web_research"
            ),
            "challenge_types": (
                "negation|subject_object|number|lexical|attachment|omission|"
                "addition|unsupported_certainty|scripture|proper_name|idiom|"
                "hebrew_greek|textual|chronology|morphology|source_text|"
                "internal_consistency|other"
            ),
        }

    def prosecutor_challenge_limit(self, *, budgeted: bool) -> int:
        if self.is_modernization:
            return 8 if budgeted else 10
        return 12 if budgeted else 15

    def adjudicator_brief(self) -> dict[str, str]:
        if self.is_modernization:
            return {
                "role": (
                    "You are the final evidence-aware adjudicator for a conservative "
                    "historical-English modernization. Decide from the authoritative "
                    "source text; do not majority-vote."
                ),
                "source_heading": "SOURCE HISTORICAL ENGLISH",
                "task_rules": (
                    "This is conservative modernization, not rewriting. Prefer the "
                    "smallest change necessary to make genuinely archaic or obsolete "
                    "English read naturally to a modern reader. When two valid witnesses "
                    "are semantically equivalent, prefer the one with fewer unnecessary "
                    "changes from the source. Do not use edit distance mechanically as "
                    "proof of quality, and never reward a draft merely for changing more "
                    "words. Do not prefer more archaic wording, more literary wording, "
                    "more elaborate wording, or more extensive rewriting. Do not restore "
                    "archaic forms; says -> saith, has -> hath, show -> shew, to -> unto, "
                    "or you -> thou are task-direction errors outside explicitly protected "
                    "spans. Quotation marks alone do not protect historical English; do "
                    "not prefer an archaic quotation merely because it is closer to the "
                    "source edition. Preserve already-modern wording exactly when possible. Fix only "
                    "concrete review problems. Preserve doctrine, argument structure, "
                    "quotation, Scripture references, names, numbers, negation, rhetorical "
                    "force, and intentional repetition."
                ),
                "final_noun": "modernization",
                "evidence_kinds": "semantic_rag|corpus_related|source_edition|web_research",
                "source_field": "source",
            }
        return {
            "role": (
                "You are the final evidence-aware adjudicator for St Jerome's "
                "Commentary on Ezekiel. Decide from the authoritative TARGET LATIN; "
                "do not majority-vote."
            ),
            "source_heading": "TARGET LATIN",
            "task_rules": (
                "Check target coverage clause by clause. Preserve unresolved "
                "ambiguity instead of forcing a choice."
            ),
            "final_noun": "translation",
            "evidence_kinds": (
                "jerome_phrase|jerome_lemma|scripture|glossary|morphology|"
                "semantic_rag|corpus_related|source_edition|chronology|proper_name|web_research"
            ),
            "source_field": "latin",
        }


def task_profile_from_chunk(chunk: dict[str, Any]) -> TaskProfile:
    project = chunk.get("project") if isinstance(chunk.get("project"), dict) else {}
    task_type = str(chunk.get("task_type") or project.get("task_type") or "translation")
    source_language = str(chunk.get("source_language") or project.get("source_language") or "la")
    target_language = str(chunk.get("target_language") or project.get("target_language") or "en")
    labels = {
        "la": "Latin",
        "historical_english": "Historical English",
        "modern_english": "Modern English",
        "en": "English",
    }
    return TaskProfile(
        project_id=str(project.get("id") or chunk.get("project_id") or "jerome-ezekiel"),
        task_type=task_type,
        operation_label=str(project.get("operation_label") or task_type),
        source_language=source_language,
        target_language=target_language,
        source_label=str(chunk.get("source_label") or project.get("source_label") or labels.get(source_language, source_language.replace("_", " ").title())),
        target_label=str(chunk.get("target_label") or project.get("target_label") or labels.get(target_language, target_language.replace("_", " ").title())),
        morphology_enabled=bool(project.get("morphology_enabled", task_type == "translation")),
        structural_enabled=bool(project.get("structural_enabled", task_type == "translation")),
    )


def word_tokens(value: str) -> list[str]:
    return re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿ']+", value)
