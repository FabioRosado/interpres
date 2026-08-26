# St Jerome evidence-first translation pipeline

This repository refactors the v4/v4.1 *Commentaria in Ezechielem* workflow
into an auditable Latin-to-English pipeline. Its governing rule is:

> Models may propose; evidence must verify. Agreement is not proof.

The system aims to produce a strong draft while making dangerous uncertainty
difficult to hide. `unresolved` and `human_review` are successful, honest
outcomes when the available evidence cannot support approval.

The required baseline inspection and exact old-to-new stage map are in
[`docs/v4-migration-map.md`](docs/v4-migration-map.md).

## Architecture

```text
Corpus source -> canonical page units -> 3-4-unit processing chunks
  -> deterministic morphology + compact glossary flags
  -> blind structural parse
  -> independent Witness A
  -> independent Witness B
  -> deterministic witness validation + eligibility gate
  -> deterministic checks
  -> prosecutor_initial (every chunk)
  -> research_prosecutor (bounded deterministic evidence receipts)
  -> prosecutor_grounded
  -> adjudicator_initial
  -> research_adjudicator (optional bounded targeted receipts)
  -> adjudicator
  -> accepted | corrected | unresolved | human_review
  -> audit JSONL with immutable stage provenance
```

Witnesses receive target Latin as explicitly closed, ID-bearing source units
and clearly separated read-only context. They return one coherent chunk-level
translation plus small ordered source-unit mapping receipts; they are not
forced to translate each unit independently. They do
not receive morphology, structural output, each other, the prosecutor,
adjudication, external English, or reviewed translations. The structural
parser runs before witnesses and never receives English witnesses.

Witness responses are untrusted proposals. Before either can reach prosecution
or be selected as an adjudicator base, a local gate verifies the exact stored
target, immutable raw response, provider stop/token receipt, strict JSON-only
schema, every expected source-unit ID, ordered compact translation end-markers,
reported omissions, commentary/fences, suspicious source copying, and
coverage-length signals. Two valid witnesses are required to continue. One or
zero valid witnesses fails closed before prosecution while preserving all raw
responses for audit and human review.

The cached chunk 4/5 investigation and exact provider receipts are recorded in
[`docs/witness-boundary-diagnosis.md`](docs/witness-boundary-diagnosis.md).

Every expensive stage has an independent content-addressed JSON cache. Keys
include source, prompt/schema/pipeline version, model/provider/options, and the
actual output hash of dependencies. A forced stochastic rerun therefore makes
downstream cache entries stale without deleting the archived attempt.

Evidence grades used in adjudication are:

- A: deterministic or source-verifiable evidence;
- B: retrieved corpus evidence requiring interpretation;
- C: inference grounded in visible Latin/context;
- D: unsupported model claim.

Serious issues may not be resolved solely from C/D evidence.

Adjudicator requests are preflighted by a hard input-budget gate before any
provider call. The gate preserves the complete target Latin, both complete
witnesses, prosecutor objections, non-pass deterministic findings, and the
receipts cited by high-severity objections. It deterministically reduces only
lower-priority context/debug material. Every reduction is written into the
stage cache as a budget receipt. As a final lossless step it may encode those
same JSON sections without display whitespace; it never summarizes or drops
mandatory evidence. If the mandatory core still does not fit, the stage fails
with `adjudicator_input_budget_exceeded` and the provider is never called.

The adjudicator is not a trusted editor. Its structured response is an
immutable proposal that selects one complete witness and supplies bounded
exact edits. A separately versioned deterministic finalization policy then:

- reconstructs the draft from the selected witness rather than accepting
  free-form replacement text;
- sends any single edit over 48 words to human review, closing the loophole
  where an exact edit could replace an entire witness paragraph;
- blocks automatic acceptance when eight or more contiguous target-Latin
  words remain in the purported English draft;
- verifies positive evidence citations against persisted receipts, so
  `no_evidence_found`, `unavailable`, errors, unknown IDs, and unverified
  research leads cannot support Grade-A/B claims;
- requires each high-severity finding to have a source-verifiable Grade-A
  basis or its own successful receipt;
- normalizes decisions carrying unresolved or human-review items away from
  `accepted`/`corrected`.

Raw provider responses and adjudicator-stage outputs remain read-only. These
gates create only a derived finalization decision and precise review request.
Fluency or confidence therefore cannot promote a wholesale rewrite, copied
Latin, or unsupported evidence claim into an approved draft.

Audit assembly follows the exact cache-key and output-digest dependency chain
from the selected finalization record. A newer partial/orphan stage attempt is
kept in history but cannot silently replace the stage that actually fed the
adjudicator. `refinalize` reapplies only this local acceptance policy to a
cached coherent adjudication chain and is guaranteed not to call a provider.

## Environment and configuration

Use the prepared environment:

```powershell
conda activate jerome
```

All paths, providers, role assignments, model options, chunk sizes, cache
paths, retries, and evidence limits are in [`pipeline.yaml`](pipeline.yaml).
The initial production assignments are:

- Witness A: Ollama `qwen3.5:9b`
- Witness B: Ollama `mistral-small3.2:24b`
- Blind structural parser: Ollama `qwen3.8:27b`
- Prosecutor: OpenRouter `nvidia/nemotron-3-ultra-550b-a55b:free`, with
  automatic Ollama `gemma3:27b` fallback
- Adjudicator: Ollama `qwen3.8:27b`

The v4.1 script named `qwen38-27b-q4ks`, but a read-only Ollama tag probe on
2026-08-24 reported that tag as IQ3_XXS. The installed `qwen3.8:27b` reports
Q4_K_M, so the latter is the evidence-based Q4 assignment requested here.

For OpenRouter, put the key in the ignored project-root `.env` file:

```dotenv
OPENROUTER_API_KEY=your-key-here
```

The committed [`.env.example`](.env.example) contains the supported name but
no secret. The loader reads `.env` beside `pipeline.yaml`; an existing process
environment variable takes precedence. Never put the key in `pipeline.yaml`,
source code, or Git. If the key is absent or the endpoint is unavailable, the
prosecutor attempts its configured local fallback and records the fallback.
Primary plus fallback failure is stored as `unavailable` or `failed`; it is
never confused with `no_issue_found`.

TranslateGemma remains disabled and outside production. Its observed local tag
is `translategemma:27b`; set `enabled: true` under
`models.experimental_translategemma`, then use `benchmark-witness` if you want
to evaluate it. It is never silently substituted for a production witness.

## Core commands

All examples can use `python -m jerome_pipeline` or the compatible active
entry point `python translate_book_v4_1.py`. The complete option-by-option
operator guide is [`docs/command-reference.md`](docs/command-reference.md).

Preprocess Book I and inspect canonical chunks:

```powershell
python translate_book_v4_1.py preprocess --book 1
python translate_book_v4_1.py inspect-chunks --book 1 --limit 5
python translate_book_v4_1.py inspect-chunks --book 1 --chunk 1 --full
```

Build the exact/normalized/lemma concordance, then the persisted inspectable
TF-IDF + LSA retrieval index:

```powershell
python translate_book_v4_1.py build-concordance --book 1
python translate_book_v4_1.py build-retrieval-index
python translate_book_v4_1.py search-corpus --query "concaluit cor meum" --limit 5
```

The retrieval artifact stores its vocabulary, IDF weights, LSA components,
document vectors, exact Latin, stable source IDs, and provenance. Ranking is a
deterministic lexical/LSA hybrid; no model summary is substituted for the
retrieved Latin.

The Jerome semantic index is deliberately separate from Scripture retrieval.
`paths.vulgate` points to the local Clementine Latin Vulgate and is used for
reference lookup plus exact/near Latin phrase matching. `paths.cpdv` points to
the 74-file local CPDV corpus and supplies optional English comparison text for
matched verses. ODR is a second optional English comparison adapter; it is not
required for either Vulgate or CPDV lookup. A real configured Psalm 38:4 check
returns the local Vulgate `Concaluit cor meum...` together with its CPDV
comparison, while keeping Vulgate as textual evidence and CPDV as comparison
help.

Run one chunk, a range, or a whole configured book:

```powershell
python translate_book_v4_1.py run --book 1 --chunk 1
python translate_book_v4_1.py run --book 1 --start 1 --end 5
python translate_book_v4_1.py run --book 1
```

For live plumbing/schema smoke tests, use the explicit lightweight profile:

```powershell
python translate_book_v4_1.py run --profile smoke --chunk 1 --through structural_parse
python translate_book_v4_1.py resume --profile smoke --chunk 1
```

`smoke` uses Qwen 3.5 9B for every LLM role. Its translations and decisions
are not outcome evaluations and must not be promoted into production audits.
Smoke calls have no model fallback and no automatic transport retry. Their
cache/audit records carry `execution_profile: smoke`; normal audit export reads
only `production`, so a smoke attempt cannot silently replace a proper result.
Unit/mocked tests remain fully fake-provider based and call no model at all.
Omit `--profile smoke` (the default is `production`) only when evaluating real
translation outcomes with the configured proper models.

Stop after a stage, retry failures, or force exactly one stage:

```powershell
python translate_book_v4_1.py run --chunk 1 --through structural_parse
python translate_book_v4_1.py resume --chunk 1
python translate_book_v4_1.py run --chunk 1 --force-stage prosecutor_initial
```

List only attempted chunks whose latest current-source production stage
failed, preview the overnight retry snapshot, or resume that snapshot:

```powershell
python translate_book_v4_1.py failed-chunks --book 1
python translate_book_v4_1.py resume-failed --book 1 --dry-run
python translate_book_v4_1.py resume-failed --book 1
```

`resume-failed` continues through every selected job even if an earlier job
fails, then exits non-zero if any remain incomplete. `--limit N` bounds a
batch. It excludes never-started chunks, stale-source records, smoke failures
when using the production profile, and successful `human_review`/`unresolved`
outcomes. Thus it does not silently start the rest of a book.

Apply the new witness gate to an existing cached pair without calling a model:

```powershell
python translate_book_v4_1.py validate-witnesses --book 1 --start 4 --end 5
```

The command exits non-zero unless both witnesses are eligible. It never edits
their raw responses or translations.

Inspect cache/evidence/review output and export audits:

```powershell
python translate_book_v4_1.py inspect-cache --chunk book01-pl-0015A--pl-0017A-f82ad2653b --summary
python translate_book_v4_1.py inspect-evidence --chunk book01-pl-0015A--pl-0017A-f82ad2653b
python translate_book_v4_1.py review-flags --book 1
python translate_book_v4_1.py export-audit --book 1
```

Open the local reviewer/editor workspace over the persisted Book I artifacts:

```powershell
python translate_book_v4_1.py review --book 1
```

The machine audit remains read-only. Human edits and issue resolutions are
saved as new append-only revision files; neither the LLM output nor a prior
editorial revision is edited. Explicitly approved reusable resolutions become
separate editorial precedent for matching later Latin while the blind
witnesses remain unaffected. See [`docs/reviewer-ui.md`](docs/reviewer-ui.md).

Compare against explicit v4/v4.1 artifacts (none were present at their former
hard-coded locations during this refactor):

```powershell
python translate_book_v4_1.py compare-v4 --book 1 `
  --qwen C:\path\book1-qwen35-v4.1.jsonl `
  --mistral C:\path\book1-mistral-v4.1.jsonl `
  --prosecutor C:\path\book1-prosecutor-v4.1.jsonl `
  --review C:\path\book1-reviewed-v4.1.jsonl `
  --output artifacts\book01\v4-comparison.json
```

The report shows available old witnesses/adjudication, new structure,
prosecutor/evidence rounds, new decision, status change, and newly surfaced
human flags. It reports absent legacy material rather than pretending a match.

Benchmark an optional isolated witness without changing production roles:

```powershell
python translate_book_v4_1.py benchmark-witness --model-role experimental_translategemma --chunk 1
```

## Challenge/evaluation harness

Challenge labels are kept in the curated JSONL but omitted from the reviewer
prompt. The set includes real difficult passages, a clean control, and planted
negation, number, lexical-polarity, proper-name, Scripture, subject/object,
omission, attachment, and unsupported-certainty errors.

```powershell
python translate_book_v4_1.py challenge inspect
python translate_book_v4_1.py challenge run
python translate_book_v4_1.py challenge report
```

For a model-free calibration of deterministic detection:

```powershell
python translate_book_v4_1.py challenge run --deterministic-only
```

For the real staged challenge path, each frozen candidate is injected into
both witness slots. This intentionally creates agreement around the candidate
under test; the normal structural parser, deterministic checks, prosecutor,
research rounds, and adjudicator must still find and resolve planted errors:

```powershell
python translate_book_v4_1.py challenge run --full-pipeline
```

This command uses the configured production models unless a caller injects a
fake provider in tests. It stores resumable stage records under
`artifacts/challenge-cache`; challenge labels and mutation metadata are never
included in model prompts.

```powershell
python translate_book_v4_1.py inspect-cache --challenge `
  --chunk challenge-jerome-concaluit-polarity --summary
```

Metrics include planted errors detected/missed, first detecting stage,
unexpected flags, clean-case false positives, unresolved rate, and reviewer
failures. They are regression/calibration measures for this project, not a
universal accuracy percentage.

The current model-free baseline covers all 11 curated cases: deterministic
signals catch 4 of 12 planted errors and flag none on the clean control. This
is a floor, not an accuracy target—attachment, subject/object, subtle omission,
and unsupported-certainty cases are intentionally left for structural and
adversarial model stages rather than guessed by brittle heuristics.

## Tests

Ordinary tests never invoke live models:

```powershell
python -m unittest discover -s tests -v
```

The installed Whitaker adapter contract tests do use the local deterministic
dictionary package. They cover `memoriae`, `concaluit`, `plagas`,
`tribus/tribusque`, proper names, and unknown forms. Other offline regressions
cover Roman-numeral/date preservation, query-window Scripture near matches,
provider timeout/retry/fallback, adjacent-unit concordance context, and failed
research-stage receipt preservation.

## Editorial memory

Human style conventions belong in [`style_decisions.md`](style_decisions.md),
not the glossary. Structured decisions/reviews are append-only:

```powershell
python translate_book_v4_1.py record-editorial --kind human_review `
  --source-unit book01-pl-0017B `
  --issue "tribus Judae has an incomplete deterministic parse" 
python translate_book_v4_1.py inspect-editorial
```

The browser editor also writes chunk-level revision snapshots to
`editorial/reviews/`. Only approved, resolved, explicitly reusable wording is
indexed as editorial precedent. This stays separate from claims about Latin
meaning and from corpus/Scripture/CPDV evidence.

## Files created or refactored

- `translate_book_v4_1.py`: active compatibility entry point into the new CLI
- `pipeline.yaml`: centralized configuration and actual tested model tags
- `jerome_pipeline/source.py`: canonical parsing, provenance, and chunking
- `glossary.py`: observed Whitaker adapter, full morphology, lemma-based traps
- `jerome_pipeline/providers.py`: configurable Ollama/OpenRouter with fallback
- `jerome_pipeline/cache.py`: independent, auditable stage cache
- `jerome_pipeline/prompts.py` and `schemas.py`: blinded prompts and validation
- `jerome_pipeline/checks.py`: cheap deterministic signals
- `jerome_pipeline/evidence.py`: concordance, Scripture, morphology, local
  authorities, ODR comparison, and bounded evidence receipts
- `jerome_pipeline/retrieval.py`: persisted inspectable TF-IDF/LSA retrieval
- `jerome_pipeline/pipeline.py`: resumable bounded orchestration and audit
- `jerome_pipeline/review.py`: stable reviewer view model and immutable
  machine-artifact adapter
- `jerome_pipeline/editorial.py`: append-only revisions and approved editorial
  precedent index
- `jerome_pipeline/review_server.py` and `reviewer_ui/`: local API and browser
  review application
- `jerome_pipeline/challenge.py`: blinded challenge runner and metrics
- `jerome_pipeline/reports.py`: v4/v4.1 compatibility report
- `docs/structural-parse-validation.md`: observed cutoff diagnosis and repeated
  chunk 1 live receipts
- `docs/command-reference.md`: every CLI command, option family, model-call
  boundary, failure-batch behavior, and exit code
- `docs/research-evidence.md`: RAG, authority, ODR, and optional-web contracts
- `docs/reviewer-ui.md`: editing, immutability, and precedent operating guide
- `tests/`: deterministic and mocked vertical-slice coverage

## Known limitations and manual preparation before full Book I

- Verify that the four configured local Ollama tags are installed and callable.
  This task does not install models, CUDA, Ollama, or system dependencies.
- The OpenRouter key is now configured in the ignored `.env`. Keep it there;
  verify the Nemotron endpoint only when starting controlled live acceptance.
  The local Gemma fallback should also be checked before a long run.
- Build the concordance with lemmas and then `build-retrieval-index` before a
  production run. The no-lemma mode is useful only for fast source diagnostics.
- The observed Whitaker data recognizes `tribus/tribusque` as the numeral
  “three” but fails to expose the noun “tribe” in `tribus Judae`. The structural
  parser must put that noun analysis under `unverified_analyses`; this is a
  recorded backend gap, not a reason to fabricate morphology.
- The lexicon is primarily classical and will miss patristic/biblical forms and
  names. `not_found` means unresolved by this backend, not rare or wrong.
- Deterministic coverage/name/number/Roman-numeral checks are conservative
  signals, not semantic proofs. The adjudicator still needs to inspect the
  Latin.
- The original structural prompt exhausted 3,000/3,600-token ceilings, and an
  earlier Qwen 3.5 smoke response exhausted 5,200. The model-facing structural
  schema is now compact and provider-constrained, while the canonical audit
  schema is restored deterministically. Three forced `qwen3.8:27b` chunk 1
  runs passed consecutively at 2,229, 2,974, and 3,230 tokens with natural
  `stop` reasons and 1,970–2,971 tokens of remaining margin. Diagnosis and
  receipts are in [`docs/structural-parse-validation.md`](docs/structural-parse-validation.md).
  A later, larger 20-sentence chunk completed its sentence records but reached
  the 5,200-token ceiling in its final ambiguity array. Production now allows
  7,200 output tokens for targets with at least 12 sentences while keeping the
  same compact schema and validation; smaller production inputs and smoke
  remain at 5,200. This lets chunk 1 reuse its validated structural cache. The
  five-chunk acceptance attempt produced three
  complete human-review records and two targeted failures that now require
  reruns through Reviewer UI v1:

  ```powershell
  python translate_book_v4_1.py preprocess --book 1
  python translate_book_v4_1.py resume --book 1 --start 2 --end 2 --through structural_parse
  # Only after the live structural schema gate passes:
  python translate_book_v4_1.py resume --book 1 --start 1 --end 1
  python translate_book_v4_1.py resume --book 1 --start 2 --end 2
  python translate_book_v4_1.py resume --book 1 --start 3 --end 3
  python translate_book_v4_1.py resume --book 1 --start 5 --end 5
  python translate_book_v4_1.py review --book 1
  ```

  The requested 5–10 complete live chunks remain an acceptance step, not a
  unit-test requirement. Use production roles only for those outcome tests;
  keep `--profile smoke` for quick transport/schema checks.
- A corrective chunk 3 run subsequently reached the prosecutor's exact 3,200-
  token output ceiling after completing 13 challenges and overproducing 11
  evidence requests, although only six can be executed. Prosecutor inputs are
  now losslessly minified, reports are capped at 12 consolidated challenges
  and six prioritized requests, and production has 4,200 output tokens to
  close the JSON. On the observed input this reduces the prompt from 111,210
  to 85,363 UTF-8 bytes; smoke remains at 3,200 output tokens.
- Corpus Corporum's sequential edition-pagination tokens may occur inside a
  prose line as either a range or a single number. Preprocessing records and
  removes those tokens outside parentheses/brackets, while preserving biblical
  citation numbers and page-broken continuations such as `2).`. Correcting this
  changed the target fingerprint for Book I chunks 3 and 5. Stable chunk IDs
  remain unchanged, but the reviewer refuses cache records belonging to the
  previous source fingerprint; those chunks must be rerun before their old
  decisions can be treated as current.
- The local Vulgate TSV repeats identical canon rows; the loader deterministically
  de-duplicates references. CPDV is always labelled comparison help.
- Only Book I is configured. `Full corpus (Book I-XIV).txt` is now a valid
  fourteen-book Corpus Corporum download, but combined-corpus book/footnote
  splitting is intentionally deferred while Book I acceptance is completed.
- Semantic retrieval is an inspectable persisted local TF-IDF/LSA index. Local
  chronology, proper-name, source-edition, and ODR files are optional: missing
  files produce `unavailable`, while a configured index with no match produces
  `no_evidence_found`. Optional web research requires an injected backend, is
  disabled by default, and can emit only unverified `research_lead` records.
- No copyrighted published translation was added or used as drafting input.
- The local editor writes only append-only revision files. Reviewer accounts,
  shared multi-user locking, deployment, and automatic/fuzzy replacement
  remain deliberately deferred.


## Architecture diagram

```
                         ST JEROME TRANSLATION PIPELINE
                    "Models propose; evidence must verify"


 Full Corpus: Commentaria in Ezechielem, Books I–XIV
                              |
                              v
          +-------------------------------------------+
          | Combined-corpus book splitter [PENDING]   |
          | - recognise Books I–XIV                   |
          | - preserve PL pages and footnotes         |
          +-------------------------------------------+
                              |
                              v
          +-------------------------------------------+
          | Canonical source parser                   |
          | PL page units -> 3–4-unit chunks          |
          | target Latin + read-only context          |
          +-------------------------------------------+
                              |
                 one independently cached chunk
                              |
           +------------------+------------------+
           |                                     |
           v                                     v
 +----------------------+              +----------------------+
 | Deterministic        |              | Blind structural     |
 | morphology/glossary  |------------->| parser               |
 | Whitaker backends    | candidates   | Qwen 3.8 27B         |
 +----------------------+              | NO English witnesses |
                                       +----------------------+

                              |
               +--------------+--------------+
               |                             |
               v                             v
     +-------------------+         +-------------------------+
     | Witness A         |         | Witness B               |
     | Qwen 3.5 9B       |         | Mistral Small 3.2 24B   |
     | Latin -> English  |         | Latin -> English        |
     | independent/blind |         | independent/blind       |
     +-------------------+         +-------------------------+
               |                             |
               +--------------+--------------+
                              |
                              v
                +---------------------------+
                | Deterministic checks      |
                | - omissions/additions     |
                | - numbers and negations   |
                | - proper names            |
                | - known lexical traps     |
                | - Scripture/source checks |
                +---------------------------+
                              |
                              v
                +---------------------------+
                | Prosecutor: initial review|
                | Nemotron via OpenRouter   |
                | Gemma local fallback      |
                | Reviews every chunk       |
                +---------------------------+
                              |
                    structured evidence requests
                              |
                              v
       +-----------------------------------------------------+
       | RESEARCH AGENT / EVIDENCE SERVICE                   |
       |                                                     |
       |  1. Jerome exact/lemma concordance                  |
       |  2. Jerome semantic RAG (TF-IDF + LSA)              |
       |  3. Latin Clementine Vulgate                        |
       |  4. CPDV English comparison                         |
       |  5. Whitaker morphology/glossary                    |
       |  6. Optional curated authorities                    |
       |     - proper names                                  |
       |     - chronology                                    |
       |     - source editions                               |
       |                                                     |
       | Returns source text + provenance, not model memory  |
       +-----------------------------------------------------+
                              |
                       evidence receipts
                              |
                              v
                +---------------------------+
                | Grounded prosecutor       |
                | - accepts/revises claims  |
                | - cites evidence IDs      |
                | - preserves uncertainty   |
                +---------------------------+
                              |
                              v
                +---------------------------+
                | Initial adjudicator       |
                | Qwen 3.8 27B              |
                |                           |
                | Selects Witness A or B    |
                | Returns exact edits only  |
                | Does NOT rewrite full text|
                +---------------------------+
                              |
                Does it request more evidence?
                         /             \
                       yes              no
                       /                 \
                      v                   |
       +-----------------------------+    |
       | Targeted evidence round     |    |
       | bounded by configured limit |    |
       +-----------------------------+    |
                      |                   |
                      +---------+---------+
                                |
                                v
                 +----------------------------+
                 | Final adjudication         |
                 | base witness + exact edits |
                 +----------------------------+
                                |
                                v
                 +----------------------------+
                 | Deterministic finalizer    |
                 | - applies exact edits      |
                 | - reconstructs full draft  |
                 | - rejects ambiguous edits  |
                 | - reruns final checks      |
                 +----------------------------+
                                |
                                v
          +-----------+-----------+------------+--------------+
          |           |           |            |              |
       ACCEPTED    CORRECTED   UNRESOLVED   HUMAN_REVIEW   INCOMPLETE
          |           |           |            |              |
          +-----------+-----------+------------+--------------+
                                |
                                v
                 +----------------------------+
                 | Audit and provenance JSONL |
                 | - prompts and raw responses|
                 | - model/provider/options   |
                 | - evidence receipts        |
                 | - dependency hashes        |
                 | - checks and final draft   |
                 +----------------------------+


 Every stage is content-addressed and independently cached.
 A changed input or dependency invalidates downstream cached results.
 ```
