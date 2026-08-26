# Audit schema and later reviewer UI contract

`export-audit` writes one JSON object per processing chunk. Processing chunks
are convenient batches; durable editorial anchoring belongs to
`source.source_unit_ids`, `source.canonical_source_unit_ids`, and
`source_spans`.

## Top-level audit fields

- `schema_version`, `pipeline_version`, `execution_profile`, `chunk_id`
- `source`, including book/work/corpus, pages, stable unit IDs, and fingerprints
- exact `page_markers` with the original raw Corpus marker
- `target_latin`, `context_before`, `context_after` as separate fields
- `source_spans`, each explicitly tagged target/context
- linked `annotations` with raw marker, reference, source unit, and offsets
- `stages`, containing the latest independently cached record for every stage
- `stage_history`, containing all cache identities and archived forced attempts,
  including failed/invalid earlier prompt versions and bounded research rounds
- `final_draft`, `final_status`, `human_review_requests`, `unresolved_issues`

Each stage record includes:

- content-addressed `cache_key` and input/dependency material;
- complete/failed/unavailable/incomplete status;
- timestamps, prompt/pipeline/schema versions;
- configured or actually used provider/model/options;
- provider attempts and fallback trail;
- for new witness calls, the exact request prompt and constrained response
  schema, their digests, the separated target/context inputs, and the
  deterministic output-budget preflight receipt;
- parsed output plus raw model response where configured;
- typed error rather than an invented result;
- source/tool provenance.

`execution_profile` keeps lightweight smoke attempts out of the default
production audit. Smoke output remains inspectable in the stage cache but is
not an eligible replacement for a production translation or adjudication.

The original deterministic morphology and original blind structural output are
never overwritten by prosecutor or adjudicator conclusions.

Exact adjudicator edits are attempted in model order. If that order fails only
because a shorter replacement overlaps a longer exact replacement, the
validator deterministically tries longer substrings first and records
`coverage.edit_application_mode: specificity_fallback`. It never chooses
between duplicate occurrences; remaining non-uniqueness fails closed. A
complete failed raw response may be revalidated under this deterministic rule
without another provider call, while the original failed cache record is
archived unchanged. High-severity corrections without either a
source-verifiable Grade-A basis or a directly cited, successful supporting
receipt are forced to `human_review` during finalization. The finalization
policy treats all adjudicator output as a proposal, not authority. It records
`final_checks.policy_version` and `decision.evidence_validation`, sends
paragraph-scale edits and long copied target-Latin spans to human review,
verifies positive evidence citations against actual successful receipts, and
prevents accepted/corrected states from coexisting with unresolved or
human-review items. These derived checks do not overwrite the raw response or
the adjudicator-stage record.

Active audits anchor on the newest dependency-bearing `witness_gate`, then
select the furthest downstream record descended from that gate and walk its
recorded dependency cache keys and output hashes recursively. A newer witness
branch is therefore current even when it stops before `finalize`; an older
completed final remains history. The top-level `stages` object contains one
coherent lineage, not an independent "latest record" from each stage.
Interrupted, superseded, or forced attempts remain visible in `stage_history`
and are counted by `audit_lineage.nonselected_history_count`. If an exact
dependency record is missing, the audit is incomplete rather than silently
combining incompatible attempts.

The current independently cached stage order is:

1. `morphology`
2. `structural_parse`
3. `witness_a`, then `witness_b` (independent prompt inputs)
4. `witness_a_validation`, then `witness_b_validation` (provider-free)
5. `witness_gate` (persists `both_valid`, `single_valid_a`,
   `single_valid_b`, or blocked `both_invalid`)
6. `deterministic_checks`
7. `prosecutor_initial`
8. `research_prosecutor`
9. `prosecutor_grounded`
10. `adjudicator_initial`
11. `research_adjudicator`
12. `adjudicator`
13. `finalize`

Witness records preserve the complete raw provider response. Validation is a
separate derived record containing exact-input, raw-integrity, stop/token,
contract, preamble/fence, source-copy, context-leakage, global length, and
whole-target curated-name multiplicity
receipts. An invalid witness is never an eligible adjudicator base. Exactly one
valid witness produces a persisted degraded quorum: the invalid output remains
visible as a non-authoritative clue, cannot corroborate or raise evidence grade,
and automatic acceptance is false. Two invalid witnesses fail closed before
prosecution. Historical JSON contracts retain their mapping receipts for
audit. Current v4 plain-text records mark source-unit mappings unavailable and
non-blocking rather than claiming model-generated coverage. Historical
adjudications may be locally re-finalized as `human_review` when their coherent
dependency lineage contains a degraded or incomplete gate; the immutable old
model proposal remains inspectable but cannot be approved automatically.

Downstream cache materials include the exact gate key and quorum. Adjudicator
schemas contain only the permitted base IDs. Finalization stores the quorum,
degraded reason, permitted bases, automatic-acceptance flag, any rejected base
or invalid-witness citation, and `publication_eligible` independently of model
status.

Both research stages store the request list and evidence receipts separately
from the model conclusion. A configured round count of zero is recorded as a
disabled round; only zero or one is accepted, preventing a silently unbounded
agent loop. `inspect-evidence` exposes both exchanges.

## Recommended later UI

The review screen should be source-unit anchored and show:

1. Exact target Latin with page/unit breadcrumbs; context visually separate and
   impossible to mistake for target.
2. Final draft and one of the four explicit states, without a synthetic
   confidence gauge.
3. Precise human action cards first: exact Latin locator, competing readings,
   why unresolved, missing receipt, and concrete source to inspect.
4. Witnesses side by side but visually marked as proposals; agreement should
   never receive a “verified” badge.
5. Immutable blind structural parse and deterministic morphology candidates,
   including backend gaps/unverified proposals.
6. Compact lexical flags and deterministic checks with pass/warning/failure/
   unavailable distinctions.
7. Prosecutor initial allegation beside grounded disposition, followed by the
   adjudicator's initial and final decisions, so withdrawn or unsupported
   allegations and second-round requests remain auditable.
8. Evidence receipts grouped by grade and source, always showing actual Latin
   snippets and provenance. Show `source_annotation_verified` separately from
   `textual_match_verified`; label CPDV `comparison_aid` and web/forum material
   `research_lead`.
9. A stage health/provenance drawer showing model/provider/prompt version,
   cached/forced attempts, raw response, and exact failure category.
10. Append-only human notes/resolutions attached to stable source-unit IDs, with
    editorial conventions in a separate project-memory view.

Useful filters are `human_review`, `unresolved`, grounded high-severity
challenge, unavailable evidence subsystem, invalid model response, witness
disagreement, lexical ambiguity, Scripture unverified, and note/page integrity
failure. The UI should not collapse these into one risk number.
