# Data and Licensing

This document records the provenance, copyright status, and redistribution policy for every corpus and data source used by Interpres.

## Summary table

| Asset | Source | Copyright / License | Redistributable? | Committed to repo? |
|-------|--------|---------------------|------------------|-------------------|
| Interpres source code | This repository | MIT | Yes | Yes |
| Jerome Book I source | Corpus Corporum (mlat.uzh.ch) | Unknown digital edition license | **No** | No |
| Clementine Vulgate | vul-complete (GitHub) | Public domain text, MIT tooling | Text: yes; tooling: MIT | No (user obtains) |
| CPDV | Following Imperfectly | Permission granted by owner | **With attribution** | No (user obtains) |
| Whitaker's Words | blagae/whitakers_words | MIT | Yes | No (git dependency) |
| Challenge cases | Curated by repo owner | Owner copyright | Yes | Yes |
| Editorial decisions | Human reviewers | Owner copyright | Yes | Yes |
| Derived artifacts | Pipeline execution | Derived | No | No |

## Detailed notes

### Jerome / Corpus Corporum

The Latin text of Jerome's *Commentaria in Ezechielem* is in the public domain as a classical text. However, the specific digital transcription in Corpus Corporum may have its own licensing terms. We have not confirmed that redistribution is permitted.

**Policy**: Do not commit corpus files. Users download from [Corpus Corporum](https://mlat.uzh.ch/browser/cps_2.HieStr.CoInEz) and place the file locally. The `scripts/bootstrap-jerome.py` script documents the acquisition steps.

### Clementine Vulgate

The Vulgate text is public domain. The `vul-complete` tooling is MIT-licensed. The 14MB TSV export is not committed to this repository.

**Policy**: User clones `vul-complete` and generates the TSV locally.

### CPDV

The CPDV comparison corpus is sourced from Following Imperfectly with explicit permission. It is not public domain.

**Policy**: Do not commit CPDV files. Document the source and attribution requirements. Users obtain the files from the upstream repository.

### Whitaker's Words

The `whitakers_words` package (blagae fork) is MIT-licensed. It is installed as a git dependency.

**Policy**: Not committed. Documented in `requirements.txt` and `pyproject.toml`.

## Data classification

| Classification | Description | Git action |
|----------------|-------------|------------|
| SOURCE / INPUT | Original corpus files | Not committed (user obtains) |
| DERIVED / REBUILDABLE | Preprocessed chunks, concordance, retrieval index | Not committed (rebuild from source) |
| CACHE / EPHEMERAL | Stage cache, model responses | Not committed (`.cache/`) |
| EDITORIAL / HUMAN-CREATED | Review decisions, resolutions | Committed under `projects/*/editorial/` |
| TEST FIXTURE | Challenge cases, regression data | Committed under `projects/*/challenges/` |
| THIRD-PARTY | External corpus data | Not committed (user obtains) |

## Attribution

When using CPDV, attribute:
> CPDV data sourced from Following Imperfectly (https://github.com/following-imperfectly/cpdv-json). Permission granted by the repository owner.

When using Clementine Vulgate, attribute:
> Vulgate text from the Clementine Text Project (https://bitbucket.org/clementinetextproject/), via vul-complete (https://github.com/theunpleasantowl/vul-complete). Public domain text.

When using Whitaker's Words, attribute:
> Whitaker's Words Latin dictionary (https://github.com/blagae/whitakers_words), MIT License.
