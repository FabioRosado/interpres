# Usage Guide

This guide explains how to use Interpres for translation projects, from initial setup through human review.

## Table of contents

- [Project management](#project-management)
- [Running the pipeline](#running-the-pipeline)
- [Inspecting results](#inspecting-results)
- [Human review](#human-review)
- [Evidence and indexes](#evidence-and-indexes)
- [Challenges and evaluation](#challenges-and-evaluation)
- [Troubleshooting](#troubleshooting)

## Project management

### List projects

```powershell
interpres project list
```

Shows all configured projects under `projects/`.

### Show project details

```powershell
interpres project show jerome-ezekiel
```

Displays project metadata, pipeline config path, README path, and available books.

## Running the pipeline

### Preprocess source

Parse raw Latin text into canonical source units and processing chunks:

```powershell
interpres preprocess jerome-ezekiel --book 1
```

Output: `artifacts/book01/source.json`, `source_units.jsonl`, `chunks.jsonl`

### Run chunks

```powershell
# Run one chunk
interpres run jerome-ezekiel --book 1 --chunk 1

# Run multiple specific chunks
interpres run jerome-ezekiel --book 1 --chunk 1 --chunk 5 --chunk 10

# Run a range
interpres run jerome-ezekiel --book 1 --start 1 --end 10

# Use smoke profile (lightweight models, no API costs)
interpres run jerome-ezekiel --book 1 --chunk 1 --profile smoke

# Stop after a specific stage
interpres run jerome-ezekiel --book 1 --chunk 1 --through structural_parse

# Force rerun of a specific stage
interpres run jerome-ezekiel --book 1 --chunk 1 --force-stage prosecutor_initial

# Retry failed stages
interpres run jerome-ezekiel --book 1 --chunk 1 --retry-failed
```

### Resume interrupted runs

```powershell
interpres resume jerome-ezekiel --book 1
```

Continues from the last incomplete stage for each chunk.

### Retry failed chunks

```powershell
# List failed chunks
interpres failed-chunks jerome-ezekiel --book 1

# Retry only failed chunks
interpres resume-failed jerome-ezekiel --book 1

# Dry run to see what would be retried
interpres resume-failed jerome-ezekiel --book 1 --dry-run

# Limit batch size
interpres resume-failed jerome-ezekiel --book 1 --limit 10
```

### Refinalize

Reapply finalization policy without recomputing upstream stages:

```powershell
interpres refinalize jerome-ezekiel --book 1 --start 1 --end 5
```

Use after changing acceptance policy (evidence requirements, edit size limits, etc.).

## Inspecting results

### List review flags

```powershell
interpres review-flags jerome-ezekiel --book 1
```

Shows chunks with status `human_review`, `unresolved`, or incomplete.

### Inspect cache

```powershell
# Summary view
interpres inspect-cache --chunk book01-pl-0015A --summary

# Full details
interpres inspect-cache --chunk book01-pl-0015A

# Include archived attempts
interpres inspect-cache --chunk book01-pl-0015A --attempts

# Inspect challenge cache
interpres inspect-cache --challenge --summary
```

### Inspect evidence

```powershell
interpres inspect-evidence --chunk book01-pl-0015A
```

Shows prosecutor/adjudicator evidence requests and research receipts.

### Inspect editorial records

```powershell
# All editorial records
interpres inspect-editorial

# Filter by kind
interpres inspect-editorial --kind resolution
interpres inspect-editorial --kind human_review
interpres inspect-editorial --kind decision
```

### Export audit trail

```powershell
interpres export-audit jerome-ezekiel --book 1
interpres export-audit jerome-ezekiel --book 1 --output artifacts/book01/audit.jsonl
```

## Human review

### Start reviewer UI

```powershell
interpres review jerome-ezekiel --book 1
```

Opens browser at `http://127.0.0.1:8765/`.

Options:
```powershell
interpres review jerome-ezekiel --book 1 --no-browser
interpres review jerome-ezekiel --book 1 --host 127.0.0.1 --port 8876
```

### Using the reviewer

1. **Select a chunk** from the list
2. **Read the immutable machine final** — this is the AI-generated draft, never edited
3. **Edit the human translation** — your approved translation
4. **Resolve issues** — for each issue in the ledger:
   - `open` — still needs attention
   - `resolved` — you fixed it
   - `accepted` — reviewed and accepted as-is
5. **Save** — creates append-only revision file

### Record editorial decisions

```powershell
# Record a human review note
interpres record-editorial --kind human_review `
  --source-unit book01-pl-0017B `
  --issue "tribus Judae has an incomplete deterministic parse"

# Record a resolution
interpres record-editorial --kind resolution `
  --source-unit book01-pl-0017B `
  --issue "lexical trap: concaluit means grew hot, not cold" `
  --decision "approved translation 'grew hot' with Whitaker evidence"

# Record a decision with supersedes
interpres record-editorial --kind decision `
  --source-unit book01-pl-0017B `
  --issue "translation of concaluit" `
  --decision "grew hot" `
  --supersedes revision-20260101-0001.json
```

## Evidence and indexes

### Build concordance

```powershell
interpres build-concordance jerome-ezekiel --book 1
interpres build-concordance jerome-ezekiel --book 1 --no-lemmas  # faster, no morphology
```

### Build retrieval index

```powershell
interpres build-retrieval-index jerome-ezekiel
```

### Search corpus

```powershell
interpres search-corpus jerome-ezekiel --query "concaluit cor meum" --limit 5
```

### Validate witnesses

```powershell
interpres validate-witnesses jerome-ezekiel --book 1 --start 1 --end 5
interpres validate-witnesses jerome-ezekiel --book 1 --chunk 5 --force
```

Applies deterministic witness contract and derives quorum state.

## Challenges and evaluation

### Run challenges

```powershell
# Deterministic checks only (no models)
interpres challenge run --deterministic-only

# Full pipeline (calls models)
interpres challenge run --full-pipeline

# Inspect challenge metadata
interpres challenge inspect
interpres challenge inspect --case jerome-concaluit-polarity

# Read latest results
interpres challenge report
```

## Troubleshooting

### Common issues

| Issue | Solution |
|-------|----------|
| Source file not found | Place `book1.txt` in `projects/jerome-ezekiel/` |
| Concordance stale | Rebuild concordance and retrieval index |
| Model unavailable | Check Ollama is running or API key is set |
| Both witnesses invalid | Chunk is too ambiguous; mark for human review |
| Tests fail | Run `interpres doctor` and rebuild indexes |

### Getting help

```powershell
# General help
interpres --help

# Command-specific help
interpres run --help
interpres resume-failed --help
interpres challenge run --help
```

## Exit codes

| Code | Meaning |
|------|---------|
| 0 | Command completed successfully |
| 1 | Pipeline batch incomplete, or search-corpus has no index |
| Other | Invalid arguments, configuration error, or unhandled exception |
