# Chrysostom Homilies Modernization

This project is Interpres' first non-Latin transformation target. It uses the
same evidence-first, human-in-the-loop pipeline to test conservative
historical-English to modern-English modernization.

The source is the locally extracted public-domain NPNF text under
`../../chrysostom_output`. Cleaned homily bodies are read from `clean/`; extracted
editorial notes/apparatus are preserved separately from witness input in
`notes/`.

## Commands

```bash
python -m interpres.cli --config projects/chrysostom-homilies/pipeline.yaml doctor
python -m interpres.cli --config projects/chrysostom-homilies/pipeline.yaml preprocess --book 1
python -m interpres.cli --config projects/chrysostom-homilies/pipeline.yaml build-concordance --book 1 --no-lemmas
python -m interpres.cli --config projects/chrysostom-homilies/pipeline.yaml build-retrieval-index
python -m interpres.cli --config projects/chrysostom-homilies/pipeline.yaml run --book 1 --chunk 1
python -m interpres.cli --config projects/chrysostom-homilies/pipeline.yaml review --book 1
```

The project intentionally disables Latin morphology and Latin structural
parsing. Those stages still write explicit skipped records when the pipeline
runs, preserving dependency lineage without pretending Latin evidence applies.
