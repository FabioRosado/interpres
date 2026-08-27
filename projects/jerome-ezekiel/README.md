# Jerome-Ezekiel Project

This is the first configured project for Interpres, providing an evidence-first,
human-in-the-loop translation pipeline for St Jerome's *Commentaria in Ezechielem*
(Books I–XIV).

## Source

- **Author**: Hieronymus Stridonensis (St Jerome)
- **Work**: Commentaria in Ezechielem
- **Corpus**: Patrologia Latina (Corpus 2)
- **Corpus Corporum ID**: `cps_2.HieStr.CoInEz` (cc_idno 21347)
- **Permalink**: https://mlat.uzh.ch/browser/cps_2.HieStr.CoInEz

## Current status

Book I is the current validation corpus. The pipeline uses:

- Witness A: Ollama `qwen3.5:9b`
- Witness B: Ollama `mistral-small3.2:24b`
- Structural parser: Ollama `qwen3.8:27b`
- Prosecutor: OpenRouter `nvidia/nemotron-3-ultra-550b-a55b:free` (with local Gemma fallback)
- Adjudicator: Ollama `qwen3.8:27b`

## Files

- `project.yaml` — project metadata
- `pipeline.yaml` — runtime configuration (models, paths, budgets)
- `challenges/` — curated challenge cases for evaluation
- `editorial/` — human review decisions and resolutions

## Usage

```powershell
interpres preprocess jerome-ezekiel --book 1
interpres run jerome-ezekiel --book 1 --chunk 1
interpres review jerome-ezekiel --book 1
```