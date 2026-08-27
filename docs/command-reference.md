# Command reference

This is the complete operator reference for the Interpres CLI.

```powershell
interpres --help
interpres COMMAND --help
```

The global `--config PATH` option must appear before the command. It defaults
to `pipeline.yaml`:

```powershell
interpres inspect-chunks jerome-ezekiel --book 1
```

## Shared chunk selection

`run`, `resume`, `inspect-chunks`, `validate-witnesses`, `refinalize`, and
`benchmark-witness` accept:

| Option | Meaning |
|---|---|
| `--book N` | Configured book number; default `1`. |
| `--chunk VALUE` | One-based index, exact chunk ID, or unique ID prefix. Repeat to select several specific chunks. |
| `--start N --end N` | Inclusive one-based range used when `--chunk` is absent. |
| `--limit N` | Cap the number selected after the other selectors. |

Pipeline stage names accepted by `--through` and `--force-stage` are:

```text
morphology
structural_parse
witness_a
witness_b
witness_a_validation
witness_b_validation
witness_gate
deterministic_checks
prosecutor_initial
research_prosecutor
prosecutor_grounded
adjudicator_initial
research_adjudicator
adjudicator
finalize
```

`--profile production` is the default and uses the configured outcome models.
`--profile smoke` uses lightweight Qwen 3.5 roles for transport/schema checks;
smoke results are isolated and must not be treated as translation outcomes.

## Project management

### `project list`

List available Interpres projects found under `projects/`.

```powershell
interpres project list
```

### `project show`

Show details for one project, including its pipeline and README paths.

```powershell
interpres project show jerome-ezekiel
```

## Diagnostics

### `doctor`

Verify the Python environment, optional dependencies, configured source files,
corpus paths, indexes, and API key presence without calling any model.

```powershell
interpres doctor
```

Exit code `0` means every required check passed; non-zero lists missing
dependencies or data files.

## Source and retrieval

### `preprocess`

Parse the configured source into canonical source units and chunks. It writes
derived files under `artifacts/bookNN/`; it does not call a model or alter LLM
cache records.

```powershell
interpres preprocess jerome-ezekiel --book 1
```

### `inspect-chunks`

Read canonical chunks without running the pipeline. The default view is a
summary; `--full` prints complete chunk JSON.

```powershell
interpres inspect-chunks jerome-ezekiel --book 1 --limit 5
interpres inspect-chunks jerome-ezekiel --book 1 --chunk 3 --full
```

### `build-concordance`

Build the exact/normalized/lemma Jerome concordance used by evidence lookup.
The command also writes a content-addressed canonical-source manifest. A
concordance whose unit fingerprints do not match the configured source is
refused by evidence lookup until rebuilt.
Repeat `--book` to include several configured books. `--no-lemmas` is a faster
source-diagnostic mode and is not recommended for a production evidence run.

```powershell
interpres build-concordance jerome-ezekiel --book 1
interpres build-concordance jerome-ezekiel --book 1 --no-lemmas
```

### `build-retrieval-index`

Build the persisted local Latin TF-IDF/LSA retrieval index from the
concordance. The index records the concordance and canonical-source digests;
stale combinations are refused. No model is called.

```powershell
interpres build-retrieval-index jerome-ezekiel
```

### `search-corpus`

Inspect local retrieval results for a query. It is read-only and exits with
code `1` when the retrieval index is unavailable.

```powershell
interpres search-corpus jerome-ezekiel `
  --query "concaluit cor meum" --limit 5
```

## Pipeline execution

### `run`

Run selected chunks, reusing complete content-addressed stages. A cached failed
stage is not retried unless `--retry-failed` is supplied. `--through STAGE`
stops deliberately after that stage. `--force-stage STAGE` reruns exactly that
stage; changed output naturally invalidates dependent downstream cache keys.

```powershell
interpres run jerome-ezekiel --book 1 --chunk 1
interpres run jerome-ezekiel --book 1 --start 1 --end 5
interpres run jerome-ezekiel --chunk 1 --through structural_parse
interpres run jerome-ezekiel --chunk 1 --force-stage prosecutor_initial
interpres run jerome-ezekiel --chunk 1 --retry-failed
```

This can invoke production models. It exits with code `1` if any selected
chunk remains incomplete.

### `resume`

Equivalent to `run` with failed-stage retry enabled. Complete compatible stages
are reused, so it resumes at the first missing or failed cache dependency.

```powershell
interpres resume --book 1 --chunk 3
interpres resume --book 1 --start 1 --end 5
interpres resume --profile smoke --chunk 1
```

This can invoke models and exits with code `1` if any selected chunk remains
incomplete.

### `failed-chunks`

List attempted chunks whose latest stage for the current source fingerprint
and selected profile is failed, unavailable, or incomplete. It excludes
never-started chunks, stale-source records, and successful editorial outcomes
such as `human_review`.

```powershell
interpres failed-chunks --book 1
interpres failed-chunks --book 1 --profile smoke
```

This is read-only and never calls a model.

### `resume-failed`

Take one snapshot of `failed-chunks` and retry only that batch. It continues to
later jobs when one fails, then exits with code `1` if any selected job remains
incomplete. `--dry-run` is the safe preview; `--limit N` bounds an overnight
batch. It does not start untouched chunks.

```powershell
interpres resume-failed --book 1 --dry-run
interpres resume-failed --book 1
interpres resume-failed --book 1 --limit 3
interpres resume-failed --book 1 `
  --through adjudicator_initial
```

Without `--dry-run`, this can invoke models.

### `refinalize`

Reapply only the deterministic acceptance/final-check policy to the latest
complete cached adjudicator and evidence records. This command never traverses
upstream stages and never calls a model provider. It is the safe command after
a finalization-policy upgrade.

```powershell
interpres refinalize --book 1 --start 1 --end 5
interpres refinalize --book 1 --chunk book01-pl-0020D
interpres refinalize --book 1 --start 5 --end 5 --force
```

`--force` archives and replaces an existing result for the same policy key;
normally it is unnecessary.

### `validate-witnesses`

Apply the deterministic witness contract and eligibility gate to the latest
compatible cached Witness A/B prompt pair. It checks persisted
raw-response integrity, provider stop/token receipts, structured source-unit
coverage where present in historical contracts, whole-target name multiplicity,
commentary/fences, and suspicious untranslated Latin or read-only context
leakage. Current v4 plain-text witnesses explicitly record mappings as
unavailable instead of asking the provider to manufacture them. It never calls a
model provider. It derives and persists one of the explicit quorum states
`both_valid`, `single_valid_a`, `single_valid_b`, or `both_invalid`.

```powershell
interpres validate-witnesses --book 1 --start 4 --end 5
interpres validate-witnesses --book 1 --chunk 5 --force
```

Exit code `0` means the pair is safe to process: either both are valid or one is
valid under the mandatory degraded path. A single-valid result permits only the
valid base and disables automatic acceptance. Exit code `1` is reserved for
blocked `both_invalid`, which stops before prosecution. All raw witness
responses remain unchanged for audit and human review.

### `benchmark-witness`

Run an explicitly configured experimental witness in isolation. Its output is
cached as experimental and is never promoted into the production witness or
adjudication path. `--force` reruns it and `--retry-failed` retries a failed
experimental record.

```powershell
interpres benchmark-witness `
  --model-role experimental_translategemma --chunk 1
```

This invokes the selected experimental model.

## Inspection, audits, and UI

### `inspect-cache`

Read persisted stage records. Filter by exact chunk ID and/or stage.
`--summary` hides large output/raw fields, `--attempts` includes archived
attempts, and `--challenge` switches to the isolated challenge cache.

```powershell
interpres inspect-cache `
  --chunk book01-pl-0015A--pl-0017A-f82ad2653b --summary
interpres inspect-cache `
  --stage adjudicator_initial --attempts
interpres inspect-cache --challenge --summary
```

This is read-only and never calls a model.

### `inspect-evidence`

Show the prosecutor/adjudicator evidence requests and research receipts stored
for one exact chunk ID.

```powershell
interpres inspect-evidence `
  --chunk book01-pl-0015A--pl-0017A-f82ad2653b
```

This is read-only.

### `review-flags`

List current production chunks whose completed status is `human_review` or
`unresolved`, plus incomplete chunks and their precise requests/issues.

```powershell
interpres review-flags --book 1
```

This is read-only.

### `export-audit`

Write complete per-chunk provenance as JSONL. The default path is
`artifacts/bookNN/audit.jsonl`; `--output PATH` overrides it. This writes a new
derived audit export but does not edit stage records or LLM output.

```powershell
interpres export-audit --book 1
interpres export-audit --book 1 `
  --output artifacts\book01\acceptance-audit.jsonl
```

### `review`

Start the local reviewer/editor server. It opens a browser unless
`--no-browser` is used. The machine output is read-only; editorial changes are
saved as append-only revision files.

```powershell
interpres review --book 1
interpres review --book 1 `
  --host 127.0.0.1 --port 8876 --no-browser
```

Use `--profile smoke` only to inspect isolated smoke artifacts.

### `compare-v4`

Compare the current audit with explicitly supplied legacy Qwen, Mistral,
prosecutor, and reviewed artifacts. Missing legacy files are reported rather
than inferred. `--audit` supplies a pre-exported current audit and `--output`
writes the comparison report.

```powershell
interpres compare-v4 --book 1 `
  --qwen C:\path\qwen.jsonl `
  --mistral C:\path\mistral.jsonl `
  --prosecutor C:\path\prosecutor.jsonl `
  --review C:\path\reviewed.jsonl `
  --output artifacts\book01\v4-comparison.json
```

This is read-only apart from the optional derived report file.

## Challenge/evaluation commands

### `challenge inspect`

Show challenge metadata without sending challenge labels to a model. Add
`--case CASE_ID` to select one case.

```powershell
interpres challenge inspect
interpres challenge inspect --case jerome-concaluit-polarity
```

### `challenge run`

Run the challenge harness and write its result artifact:

- with no mode flag, run deterministic checks plus the configured prosecutor
  as a focused reviewer;
- `--deterministic-only` calls no model;
- `--full-pipeline` runs the full staged challenge pipeline and can call every
  configured production role.

```powershell
interpres challenge run
interpres challenge run --deterministic-only
interpres challenge run --full-pipeline
```

`--deterministic-only` and `--full-pipeline` are mutually exclusive.

### `challenge report`

Read and summarize the most recent challenge result artifact. It calls no
model.

```powershell
interpres challenge report
```

## Append-only editorial records

### `record-editorial`

Append a structured project decision, human-review note, or resolution to the
configured editorial JSONL store. Repeat `--source-unit` when a record covers
several units. `--supersedes` links a replacement decision. This command does
not modify machine/LLM artifacts.

```powershell
interpres record-editorial `
  --kind human_review `
  --source-unit book01-pl-0017B `
  --issue "tribus Judae has an incomplete deterministic parse"
```

Accepted kinds are `decision`, `human_review`, and `resolution`. `--decision`
and `--supersedes` are optional.

### `inspect-editorial`

Read append-only editorial records. `--kind` filters to one of `decision`,
`human_review`, or `resolution`.

```powershell
interpres inspect-editorial
interpres inspect-editorial --kind resolution
```

## Exit codes and help

- `0`: command completed as defined, including a read-only listing that found
  failed jobs.
- `1`: a selected pipeline/benchmark batch remains incomplete, or
  `search-corpus` has no configured index.
- Other non-zero termination indicates invalid arguments, configuration, or an
  unhandled execution error.

For the parser-authoritative option list at any time:

```powershell
interpres --help
interpres resume-failed --help
interpres challenge run --help
```
