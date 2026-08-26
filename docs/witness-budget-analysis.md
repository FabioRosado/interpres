# Witness/context budget analysis: Book I chunks 1-5

This report uses persisted production receipts only. No provider was called.
Token values marked `~` use the deterministic UTF-8-bytes/4 proxy. Actual
provider `prompt_eval_count`, `eval_count`, and OpenRouter usage are reported
without conversion.

## Request composition

| Chunk | Target chars / ~tokens | Context before chars / ~tokens | Context after chars / ~tokens | Qwen actual prompt tokens | Qwen ~non-source overhead | Mistral actual prompt tokens | Mistral ~non-source overhead |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 1,936 / 484 | 0 / 0 | 632 / 158 | 986 | 344 | 1,502 | 860 |
| 2 | 2,761 / 691 | 693 / 174 | 738 / 185 | 1,448 | 398 | 1,955 | 905 |
| 3 | 2,948 / 738 | 711 / 178 | 511 / 128 | 1,477 | 433 | 1,982 | 938 |
| 4 | 2,667 / 667 | 761 / 191 | 549 / 138 | 1,751 | 755 | 2,248 | 1,252 |
| 5 | 2,756 / 689 | 707 / 177 | 505 / 127 | 1,765 | 772 | 2,247 | 1,254 |

Chunks 1-3 used the old free-text witness prompt. Chunks 4-5 used the first
structured start/end-quote contract, whose instructions and schema increased
prompt overhead. Mistral and Qwen tokenize the same prompt differently, so the
overhead columns are approximate rather than cross-model tokenizer claims.

The compact v2 prompt keeps all target and context Latin. Its bytes/4 prompt
estimates are 1,222, 1,639, 1,634, 1,586, and 1,583 tokens respectively. The
roughly 580-590-token non-source portion buys explicit target-first boundaries,
the minimal schema, and failure rules; source/context was not discarded.

## Response composition

For complete structured responses, component tokens are approximated by
allocating the actual `eval_count` according to serialized UTF-8 character
share. For truncated chunk 5 JSON, the complete JSON string value of
`translation` was decoded independently and the remaining raw bytes counted as
mapping/contract output. Uncertainty metadata was empty in every inspected
response.

| Chunk | Witness | Translation chars / tokens | Mapping + JSON chars / ~tokens | Limit | Actual use | Stop | Truncated |
|---:|---|---:|---:|---:|---:|---|---|
| 1 | Qwen | 2,156 / 468 actual | 0 / 0 | 1,500 | 468 | stop | no |
| 1 | Mistral | 2,277 / 502 actual | 0 / 0 | 1,800 | 502 | stop | no |
| 2 | Qwen | 3,144 / 737 actual | 0 / 0 | 1,500 | 737 | stop | no |
| 2 | Mistral | 3,151 / 742 actual | 0 / 0 | 1,800 | 742 | stop | no |
| 3 | Qwen | 3,392 / 771 actual | 0 / 0 | 1,500 | 771 | stop | no |
| 3 | Mistral | 3,325 / 769 actual | 0 / 0 | 1,800 | 769 | stop | no |
| 4 | Qwen | 864 / ~224 | 3,538 / ~916 | 1,500 | 1,140 | stop | no, but invalid coverage/context |
| 4 | Mistral | 3,078 / ~766 | 1,737 / ~433 | 1,800 | 1,199 | stop | no |
| 5 | Qwen | 1,484 / ~408 | 3,970 / ~1,092 | 1,500 | 1,500 | length | yes |
| 5 | Mistral | 3,822 / ~889 | 3,918 / ~911 | 1,800 | 1,800 | length | yes |

The decisive comparison is chunks 2-3 versus chunk 5. Similar-sized targets
needed roughly 737-771 Qwen or 742-769 Mistral tokens as translation-only
responses. Chunk 5 exhausted 1,500/1,800 while spending about half or more of
the completion on duplicated mapping material. Source size was not the primary
failure.

## Compact v2 completion preflight (first redesign)

The provider-free estimator is calibrated from complete chunks 1-3:

- target token proxy: UTF-8 bytes / 4;
- translation reserve: 1.2 times that proxy (observed ratios were about
  0.97-1.07);
- contract reserve: exact serialization of IDs plus one capped 100-character
  end-marker per unit;
- 96 tokens for genuine omissions/uncertainties;
- at least 128 tokens and 15% safe closing margin.

| Chunk | Translation reserve | Compact contract maximum | Uncertainty reserve | Margin | Required output | Qwen limit | Mistral limit |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 581 | 138 | 96 | 128 | 943 | 1,500 | 1,800 |
| 2 | 830 | 178 | 96 | 166 | 1,270 | 1,500 | 1,800 |
| 3 | 886 | 178 | 96 | 174 | 1,334 | 1,500 | 1,800 |
| 4 | 801 | 178 | 96 | 162 | 1,237 | 1,500 | 1,800 |
| 5 | 827 | 178 | 96 | 166 | 1,267 | 1,500 | 1,800 |

All five current chunks pass with margin without raising output limits. A
future chunk that fails this estimate is stopped before the provider call with
an auditable `witness_output_budget_exceeded` receipt.

## Segment contract v3 after live validation

The v2 live run confirmed that the budget estimate was sufficient: Qwen stopped
normally at 352/1500 and Mistral at 1034/1800. Both failed for semantic coverage
or context containment, not truncation. Contract v3 removes the combined
`translation` plus marker receipt from the provider shape. The model writes each
unit's English exactly once in an ordered `segments` array; software joins it
and derives offsets and end markers.

Auxiliary before/after Latin is also withheld from the witness request after
both models repeatedly translated material labelled read-only. It remains in
the canonical chunk and audit. This reduces the estimated prompt for Chunk 5
from 1,583 to 1,218 proxy tokens and contract overhead from 178 to 66 tokens.

| Chunk | Translation reserve | Segment-wrapper maximum | Uncertainty reserve | Margin | Required output |
|---:|---:|---:|---:|---:|---:|
| 1 | 581 | 53 | 96 | 128 | 858 |
| 2 | 830 | 66 | 96 | 149 | 1,141 |
| 3 | 886 | 66 | 96 | 158 | 1,206 |
| 4 | 801 | 66 | 96 | 145 | 1,108 |
| 5 | 827 | 66 | 96 | 149 | 1,138 |

All remain below Qwen's 1,500-token and Mistral's 1,800-token limits.

## Chunking conclusion

The current 3-4 PL-unit chunks can remain for witness translation. Their target
sizes are 1,936-2,948 characters, not 4-5k in these five cases, and every
compact preflight fits both configured witnesses. Subchunking is therefore not
justified for the observed failures.

If a future chunk fails preflight, the safe fallback is deterministic:

1. greedily group complete canonical source units under the same output
   estimator;
2. assign every source unit to exactly one target subchunk;
3. persist adjacent units as separately labelled context, but keep them out of
   witness requests under the contract-v3 containment policy;
4. split an already oversized unit only at persisted structural sentence spans;
5. derive stable subchunk IDs from original chunk ID, unit IDs, and hashes;
6. validate set equality and uniqueness of source IDs before reconstructing
   translations in canonical order.

No subchunk implementation is enabled because current measurements do not
require it.

## Downstream granularity assessment

The old cached downstream receipts show a separate payload problem:

- prosecutor-initial prompts: 21,331-32,597 actual tokens;
- grounded-prosecutor prompts: 4,161-12,060 actual tokens;
- adjudicator-initial prompts: 10,812-12,708 actual tokens;
- adjudicator budget estimates before provider: roughly 12,668-14,686 tokens.

Prosecutor-initial is the clearest risk: it can approach the configured 32,768
context before reserving completion space. The recommended next architecture is
source-unit/dispute grouping after valid full-chunk witnesses:

1. use the exact witness spans derived from validated segment serialization;
2. group deterministic flags/disagreements by source unit plus one adjacent
   read-only unit where needed;
3. send the prosecutor only target Latin, both witness slices, relevant
   structural/check evidence, and compact surrounding context for that group;
4. retrieve evidence per stable dispute ID;
5. ask the adjudicator for bounded exact edits against persisted witness spans,
   while deterministic software applies those edits to the immutable full base;
6. retain a final whole-chunk coherence/status gate without resending every
   unrelated receipt for every local decision.

This follows “broad context for understanding; narrow context for decisions.”
It should be implemented and regression-tested as a separate pipeline change,
not folded into the witness-contract repair.

## Contract v4 supersession

The segment budget above remains the historical explanation for why v3 did not
truncate. It is no longer the production witness wire format. Matched-seed
Chunk 5 controls later showed that both segmented JSON and a minimal
single-string JSON schema could omit the same decisive parenthetical clause,
while the matched plain-text request retained it. Contract v4 therefore has
zero JSON-wrapper reserve and budgets one continuous plain response plus inline
uncertainty and closing headroom. See `witness-boundary-diagnosis.md` for the
control matrix and current validation policy.
