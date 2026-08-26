# Structural-parse failure analysis and live validation

Date: 2026-08-25  
Chunk: `book01-pl-0015A--pl-0017A-f82ad2653b`  
Scope: morphology plus `structural_parse` only

## Diagnosis from the four original failures

Every raw response ended inside an unfinished JSON field. Output size tracked
the configured generation ceiling closely:

| Model | Ceiling | Raw characters | Observed ending |
|---|---:|---:|---|
| `qwen3.8:27b` | 3,600 | 11,700 | morphology reserialization, cut mid-gloss |
| `qwen3.8:27b` | 3,600 | 11,921 | structural object, cut mid-verb |
| `qwen3.8:27b` | 3,000 | 9,880 | structural object, cut mid-lemma |
| `qwen3.5:9b` smoke | 5,200 | 17,449 | structural object, cut before closing arrays |

This establishes output-token exhaustion as the direct cause. The original
model-facing schema amplified it by requiring exact Latin and repeated prose
`basis` fields. Prompt-only compactness instructions were insufficient.
Provider transport did not cause the cutoff, but the provider discarded
Ollama's terminal metadata and therefore recorded a token-limit stop as a
generic completed transport followed by invalid JSON.

## Minimal correction

- Keep the existing canonical audit schema.
- Ask the model for a compact sentence-ID wire representation and
  deterministically restore exact sentence Latin from the source.
- Send the wire schema through Ollama's `format` field instead of relying only
  on prose instructions.
- Preserve `done_reason`, prompt/output token counts, and evaluation durations.
- Classify invalid JSON with `done_reason=length` as `output_truncated`.
- Limit `verbs` to six finite clause heads per sentence, combine auxiliary plus
  participle, and exclude standalone infinitives/participles.
- Request minified JSON so formatting whitespace does not consume the output
  budget.

The first compact Qwen 3.8 trial still hit exactly 5,200 tokens because it
emitted 45 verb entries. It had reached all six sentence objects and stopped
inside the final alternatives array. That receipt justified the narrower
finite-clause-head cap instead of increasing the token ceiling.

## Regression coverage

`tests/fixtures/structural_qwen35_token_limit.txt` is a reduced fixture based
on the observed 5,200-token smoke failure. Tests verify:

- token-limit failures are typed as `output_truncated` and retain raw output;
- the compact response restores exact source Latin;
- missing/duplicate sentence IDs are rejected;
- more than six verb entries are rejected defensively;
- Ollama receives the JSON schema and its stop metadata is retained.

## Live validation receipts

The final configuration retained the 5,200-token ceiling. Three forced,
independent Qwen 3.8 production runs passed consecutively:

| Run | Sentences | Stop reason | Output tokens | Remaining margin | Seconds |
|---:|---:|---|---:|---:|---:|
| 1 | 6 | `stop` | 2,229 | 2,971 | 841.620 |
| 2 | 6 | `stop` | 2,974 | 2,226 | 1,028.760 |
| 3 | 6 | `stop` | 3,230 | 1,970 | 1,103.464 |

All three results:

- passed JSON and defensive schema validation;
- used each of the six sentence IDs exactly once;
- respected the six-verb cap;
- reconstructed the canonical Latin exactly from the source;
- contained no detected English-translation instruction leakage or external
  attribution language;
- stopped naturally rather than at the output limit.

Only `morphology` and `structural_parse` cache records exist for this real
chunk. Witnesses and later stages were intentionally not run.

This demonstrates schema-gate stability for Book I chunk 1. It does not by
itself establish grammatical correctness across the book; structural content
still remains model evidence for later adversarial and human review.

## Book I chunk 2 production follow-up

The five-chunk production run exposed a different size case in chunk 2
(`book01-pl-0017B--pl-0018B-941f7061ea`). Qwen 3.8 returned all 20 compact
sentence records and then reached the configured 5,200-token ceiling while
serializing the trailing intrinsic-ambiguity array. Ollama reported
`done_reason=length`, `eval_count=5200`; the persisted response was 18,655
characters and ended inside JSON. This is output-token exhaustion, not a
provider transport failure or a regression to the old verbose wire schema.

Production therefore allows 7,200 output tokens when the target has at least
12 sentences; smaller inputs retain the validated and cache-compatible 5,200-
token identity. The prompt, compact response schema, exact-Latin
reconstruction, and six-finite-head defensive gate are unchanged. The 32,768-
token context still has ample combined prompt/output headroom. The smoke
profile remains at 5,200 because it is for fast plumbing checks, not production
outcomes. Regression tests fix this distinction. Chunk 2 still requires one
targeted live rerun to validate the larger ceiling.
