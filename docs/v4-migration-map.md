# v4/v4.1 inspection and evidence-first migration map

This document records the required baseline inspection performed before the
evidence-first refactor. It is deliberately descriptive: the legacy scripts
remain the benchmark definition, while the active `translate_book_v4_1.py`
entry point is migrated onto the new package.

## Located baseline

- Active v4.1 entry point: `translate_book_v4_1.py`
- Preserved v4 entry point: `legacy/translate_book_v4.py` (already moved by
  the repository owner; the working-tree move is not modified here)
- Deterministic lexical layer: `glossary.py`
- Corpus Corporum Book I source: `book1.txt`
- Local Vulgate: `data/clementine-vulgate/vul.tsv`
- Local English comparison corpus: `data/cpdv/*.json`
- Lexicon sources installed/editable from `dependencies/whitakers_words` and
  `dependencies/PyWhitakersWords`

The hard-coded v4/v4.1 JSONL paths under `C:\Users\FabioRosado` do not
currently exist. Consequently, compatibility reports must accept explicit
legacy artifact paths and report missing artifacts rather than fabricating a
comparison.

## How v4 works

1. `parse_source()` removes the download header and footnote-definition
   blocks, extracts PL page markers, queues reused footnote numbers, strips
   edition pagination without deleting verse numbers, and produces one clean
   Latin string with offset-bearing annotations.
2. `make_chunks()` uses sentence-ish punctuation and target/max character
   sizes. It records PL page range, clean-text offsets, annotations, and stable
   sequential chunk IDs.
3. Two independent witness passes invoke Ollama with the same translation
   prompt, using Qwen 3.5 9B and Mistral Small 3.2 24B. Each pass appends one
   record per chunk to a separate JSONL file.
4. A Qwen reviewer receives Latin, both witnesses, and source annotations. It
   returns JSON with a final draft, `low_risk|needs_review`, risk score,
   coverage, and corrected/human-check findings.
5. Python validates the main review fields, derives review status from
   findings/coverage, locates quoted Latin/English substrings
   deterministically, and appends a combined audit record.

## What v4.1 adds

- Source-unit grouping (nominal target four units), one-unit discourse
  context, and safety splitting of oversized units.
- OpenRouter Nemotron prosecutor with local Gemma fallback selection.
- A prosecutor JSON schema and inclusion of the prosecutor report in Qwen 3.8
  adjudication.
- Qwen 3.8's v4.1 configured tag: `qwen38-27b-q4ks`. A later read-only runtime
  probe found that tag installed as IQ3_XXS and found the actual installed
  Q4_K_M tag as `qwen3.8:27b`; the active configuration therefore uses the
  latter while retaining the former here as baseline provenance.

## Baseline behavior worth retaining

- Corpus/PL parsing rules that preserve parenthesized Scripture numbers.
- Queued footnote definitions, page provenance, and annotation offsets.
- Independent witness execution and separately stored raw outputs.
- `think: false`, conservative temperatures, per-role context/output limits,
  and long Ollama timeouts.
- Defensive JSON extraction, structured validation, and invalid-output debug
  retention.
- Append-only/resumable records and source fingerprints.
- Deterministic exact-substring locators with ambiguity counts.
- Explicit coverage, disagreement, and targeted human-check language in the
  reviewer prompt.

## Concrete baseline conflicts and defects

- All paths, model names, limits, and URLs are module constants, so changing a
  role requires code edits.
- v4.1 finds only two canonical source units in Book I (`1-2` and `23`). Most
  apparent edition numbers occur mid-wrapped-line or are verse text, so it
  creates five enormous 13k-19k-character chunks. The Corpus download's page
  blocks and annotated verse blocks need canonical identities of their own.
- Chunk IDs are sequential processing-batch IDs, so regrouping invalidates
  notes. Stable source-span IDs must be distinct from run/group IDs.
- Witness prompts omit the read-only context that v4.1 stores.
- There is no deterministic morphology or blind structural stage.
- `glossary.py` has a stub backend; known traps use a six-character surface
  prefix instead of observed lemma output.
- v4.1's prosecutor prompt ends with a `PROSECUTOR REPORT: {prosecutor}` field,
  but `run_prosecutor_pass()` does not provide that format argument. Prompt
  construction therefore fails before any prosecutor call.
- Prosecutor remote failure does not automatically try the configured local
  fallback and failures are not persisted distinctly from valid outcomes.
- Evidence requests are not executed; adjudication sees unresolved requests
  only.
- Cache identity checks only target Latin text, not prompt/model/provider
  configuration, and errors are generally not saved.
- No final states for `accepted`, `corrected`, `unresolved`, and
  `human_review`; no independently cached stage records; no challenge harness.

## Old-to-new stage map

| v4/v4.1 stage or field | Evidence-first stage | Reuse/change |
| --- | --- | --- |
| `parse_source()` | `source.parse_source()` | Reuse pagination, note queues, and offset principles; retain raw markers and create page/annotation-based canonical units. |
| `make_chunks()` | `source.make_chunks()` | Keep natural-boundary safety splitting and context separation; group 3-4 stable units and give source spans stable IDs independent of grouping. |
| Qwen/Mistral JSONL passes | `witness_a`, `witness_b` | Keep prompts' accuracy rules, independence, raw output, and `think=false`; route through providers/config and stage cache. |
| absent | `morphology` | Deterministic `whitakers_words` adapter, full candidates plus compact lexical flags. |
| absent | `structural_parse` | Blind structured LLM stage consuming Latin/context and deterministic candidates only. |
| implicit reviewer checks | `deterministic_checks` | Extract cheap number, negation, names, marker/note, coverage-signal, and annotation-reference checks as visible evidence. |
| v4.1 prosecutor | `prosecutor_initial` | Retain adversarial/evidence-request language; add structural, lexical, and deterministic inputs and persist failures. |
| absent | `research_prosecutor` | Deterministic Jerome concordance, Scripture, glossary/morphology, configured authorities, and persisted inspectable local semantic retrieval; explicit unavailable/no-hit distinction. |
| absent | `prosecutor_grounded` | Give only requested results back to the prosecutor; preserve initial and grounded outputs. |
| Qwen review | `adjudicator_initial` | Reuse clause coverage and offset language; add evidence hierarchy, four final states, unresolved ambiguity, and exact human actions. |
| absent | `research_adjudicator` | Execute at most one separately cached targeted evidence round; preserve unavailable versus no-hit receipts. |
| Qwen review | `adjudicator` | Re-run only when targeted receipts were requested, otherwise retain the validated initial decision deterministically. |
| combined reviewed JSONL | `audit export` | Assemble immutable stage-cache records, provenance, prompt/config hashes, failures, final draft/status, and review requests into JSONL. |
| skip-if-ID-exists | content-addressed stage cache | Independently key every stage by source, dependencies, provider/model/options, schema, and prompt version; support force/retry/inspect. |
| no equivalent | challenge/evaluation | Blind corrupted/clean cases, stage detection, misses, false positives, and unresolved metrics. |
| no equivalent | legacy comparison | Join explicit v4/v4.1 artifacts to new records by legacy chunk ID/source fingerprint and report available fields plus missing inputs. |

## Planned active file layout

- `pipeline.yaml`: all role, provider, path, chunking, retry, cache, and evidence
  limits; initial tested model assignments, including the observed Q4_K_M tag
  `qwen3.8:27b`.
- `jerome_pipeline/`: active source, schemas, providers, cache, evidence,
  orchestration, checks, prompts, reports, and challenge modules.
- `translate_book_v4_1.py`: compatibility entry point forwarding into the
  refactored CLI instead of remaining a second abandoned implementation.
- `tests/fixtures/` and `tests/`: model-free deterministic tests.
- `style_decisions.md` and `editorial/`: versioned editorial conventions and
  append-only review/resolution records, separate from lexical evidence.

This mapping is the implementation boundary: behavior listed as reusable is
ported or wrapped; the legacy files remain benchmark references, not a second
production pipeline.
