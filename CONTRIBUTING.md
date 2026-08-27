# Contributing to Interpres

Thank you for your interest in improving Interpres. This guide explains how to contribute effectively.

## Types of contribution

### Latin translation review

- Review machine-generated drafts in the Reviewer UI
- Record editorial decisions via `interpres record-editorial`
- Only approved, resolved, explicitly reusable wording enters editorial precedent

### Lexical / philological evidence

- Extend `KNOWN_TRAPS` in the project glossary when new mistranslations are observed
- Add proper nouns to `KNOWN_PROPER_NOUNS` when classical lexicon gaps are confirmed
- Do not fabricate morphology for unresolved forms

### Corpus / provenance improvements

- Ensure source citations and page markers are accurate
- Document corpus origin and digital edition provenance
- Respect corpus licensing (see `docs/data-and-licensing.md`)

### Deterministic checks

- Add regression cases from observed failures
- Tests must remain provider-free
- Preserve trust-boundary behavior (fail closed, no silent approval)

### Pipeline engineering

- Preserve immutable audit trails and content-addressed caches
- Do not change prompt semantics, witness contracts, or finalization policy without explicit review
- All model-facing inputs/outputs remain auditable

### Reviewer UI

- The machine artifact layer is read-only
- Human edits go through append-only revision files
- Do not add multi-user locking or deployment features without discussion

### Documentation

- Update `docs/command-reference.md` when CLI commands change
- Update `docs/architecture.md` for generic engine changes
- Update `docs/jerome-implementation.md` for Jerome-specific changes

## Running tests

```powershell
python -m unittest discover -s tests -v
```

All tests are provider-free. Do not add tests that call live models.

## Corpus copyright

- Do not commit redistributable corpus files without verified license
- Do not commit copyrighted digital editions
- Document provenance for every data source

## Questions

Open an issue for design discussions before implementing large changes.
