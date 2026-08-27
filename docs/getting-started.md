# Getting Started

This guide walks you through setting up Interpres and running your first translation pipeline on Jerome's *Commentaria in Ezechielem* Book I.

## Prerequisites

- **Python 3.9+** (3.10+ recommended)
- **8GB+ RAM** (16GB recommended for larger books)
- **Ollama** (optional, for local models) or **OpenRouter API key**
- **Git** (for cloning)
- **PowerShell** or terminal

## Step 1: Clone and install

```powershell
# Clone the repository
git clone https://github.com/your-org/interpres.git
cd interpres

# Create and activate virtual environment
python -m venv .venv
.venv\Scripts\activate

# Install Interpres
pip install -r requirements.txt
pip install -e .

# Optional: Install Whitaker's Words (Latin morphology)
pip install -e dependencies/whitakers_words
```

## Step 2: Obtain source data

Interpres does not bundle copyrighted corpus files. You must obtain them separately.

### Jerome Book I source

1. Visit [Corpus Corporum](https://mlat.uzh.ch/browser/cps_2.HieStr.CoInEz)
2. Navigate to Jerome, *Commentaria in Ezechielem*, Liber I
3. Download the plain text
4. Save as `projects/jerome-ezekiel/book1.txt`

### Clementine Vulgate (optional)

```powershell
git clone https://github.com/theunpleasantowl/vul-complete.git
cd vul-complete
# Follow project instructions to generate vul.tsv
# Copy to: data/clementine-vulgate/vul.tsv
```

### CPDV (optional)

```powershell
git clone https://github.com/following-imperfectly/cpdv-json.git
# Copy JSON files to: data/cpdv/
```

### Whitaker's Words (optional but recommended)

```powershell
pip install -e dependencies/whitakers_words
```

## Step 3: Verify setup

```powershell
interpres doctor
```

This checks:
- Python dependencies
- Source file presence
- Corpus paths
- Index availability
- API key presence (does not validate keys)

Expected output:
```
[OK] whitakers_words: installed
[MISSING] Clementine Vulgate: data/clementine-vulgate/vul.tsv
    Obtain from: https://github.com/theunpleasantowl/vul-complete
...
All required data present. Run: interpres doctor
```

Exit code 0 = all required checks passed. Non-zero = missing dependencies or data.

## Step 4: Configure models

Edit `projects/jerome-ezekiel/pipeline.yaml` or create `.env`:

```powershell
# .env (git-ignored)
OPENROUTER_API_KEY=sk-or-your-key-here
```

Or configure Ollama (default: `http://localhost:11434`):

```powershell
# Start Ollama
ollama serve

# Pull recommended models
ollama pull qwen3:9b
ollama pull mistral:small3.2
ollama pull qwen3:8
```

## Step 5: Preprocess the source

```powershell
interpres preprocess jerome-ezekiel --book 1
```

This:
- Parses `book1.txt` into canonical source units (page-based)
- Groups units into processing chunks
- Writes artifacts to `artifacts/book01/`

Output files:
- `source.json` — parsed document structure
- `source_units.jsonl` — individual source units
- `chunks.jsonl` — processing chunks (target + context)

## Step 6: Build indexes

```powershell
# Build concordance (exact/normalized/lemma lookup)
interpres build-concordance jerome-ezekiel --book 1

# Build TF-IDF/LSA semantic index
interpres build-retrieval-index jerome-ezekiel
```

Indexes are content-addressed. If the source changes, rebuild them.

## Step 7: Run your first chunk

```powershell
# Smoke test (uses lightweight models, no API costs)
interpres run jerome-ezekiel --book 1 --chunk 1 --profile smoke --through structural_parse

# Full pipeline on one chunk
interpres run jerome-ezekiel --book 1 --chunk 1

# Full pipeline on first 5 chunks
interpres run jerome-ezekiel --book 1 --start 1 --end 5
```

## Step 8: Inspect results

```powershell
# List chunks needing review
interpres review-flags jerome-ezekiel --book 1

# Inspect a specific chunk's cache
interpres inspect-cache --chunk book01-pl-0015A --summary

# See evidence used
interpres inspect-evidence --chunk book01-pl-0015A

# Export full audit trail
interpres export-audit jerome-ezekiel --book 1 --output audit.jsonl
```

## Step 9: Human review

```powershell
# Start reviewer UI
interpres review jerome-ezekiel --book 1
```

The UI opens at `http://127.0.0.1:8765/`.

### In the reviewer:
1. Select a chunk from the list
2. Read the **immutable machine final** (read-only)
3. Edit the **human translation** field
4. Resolve issues in the **ledger** (open / resolved / accepted)
5. Click **Save** — creates append-only revision file
6. Approved precedents become reusable for future chunks

## Step 10: Resume interrupted work

```powershell
# Resume all incomplete chunks
interpres resume jerome-ezekiel --book 1

# Retry only failed chunks
interpres resume-failed jerome-ezekiel --book 1

# List failed chunks first
interpres failed-chunks jerome-ezekiel --book 1
```

## Troubleshooting

### "Source file not found"
Ensure `projects/jerome-ezekiel/book1.txt` exists. Check `interpres doctor` output.

### "Concordance is stale"
Source file changed after building concordance. Rebuild:
```powershell
interpres build-concordance jerome-ezekiel --book 1
interpres build-retrieval-index jerome-ezekiel
```

### "Model provider unavailable"
Check Ollama is running or `OPENROUTER_API_KEY` is set in `.env`.

### "Both witnesses invalid"
The chunk's Latin is too corrupted or ambiguous. Mark for human review. Do not force-run.

### Tests fail with "stale index"
Run tests in a clean environment or rebuild indexes:
```powershell
interpres build-concordance jerome-ezekiel --book 1
interpres build-retrieval-index jerome-ezekiel
python -m unittest discover -s tests -v
```

## Next steps

- Read [docs/architecture.md](architecture.md) for how the pipeline works
- Read [docs/command-reference.md](command-reference.md) for all CLI options
- Read [docs/reviewer-ui.md](reviewer-ui.md) for the review workflow
- Read [CONTRIBUTING.md](../CONTRIBUTING.md) to contribute
