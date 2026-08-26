# Reviewer / Editor UI

The local editorial workspace is designed for Book I acceptance without
opening cache JSON manually or altering any model output.

## Start it

```powershell
python translate_book_v4_1.py review --book 1
```

The default address is `http://127.0.0.1:8765/`. Use `--no-browser` to start
without opening a browser. The server binds only to localhost unless an
explicit `--host` is supplied.

## Editing layout

The default Edit view uses three panes on a wide screen:

1. authoritative Latin and stable source units;
2. a locked machine final plus the editable human translation;
3. the issue-resolution ledger.

The complete immutable decision trail follows directly below the editor in
pipeline order: witnesses, explicit disagreements, deterministic checks,
initial and grounded prosecutor reports, adjudicator basis/findings/edits,
machine final and exact diff, verification, evidence receipts, structural
analysis, morphology, and per-stage provenance. A sticky jump bar moves among
these sections without hiding any of them. Selecting a source unit focuses
linked records throughout the page.

The active view is selected from the newest dependency-coherent witness-gate
branch. If that branch stops at validation, downstream stages are shown as
incomplete and an older machine final is not presented as current. Every
nonselected attempt remains available in the immutable Decision Trail; active
selection changes presentation, never historical artifacts.

## Immutability and save contract

Machine stage-cache records, audits, witness outputs, adjudicator output, and
the reconstructed machine final are always read-only. A save creates a new
append-only JSON file under:

```text
editorial/reviews/bookNN/<chunk_id>/revision-*.json
```

No save updates or replaces an earlier revision file. Every revision contains
the human translation, issue resolutions, the exact immutable machine base and
its digest, a base revision ID, timestamps, and pipeline/source provenance.
The server rejects a save with HTTP 409 if either the machine final or latest
editorial revision changed after the screen was loaded.

The browser API is intentionally narrow:

- `GET /api/health`
- `GET /api/chunks`
- `GET /api/chunks/{chunk_id}`
- `POST /api/chunks/{chunk_id}/editorial/revisions`

All PUT, PATCH, DELETE, and unrelated POST requests return HTTP 405. The POST
endpoint only creates a new editorial revision; it cannot invoke a model,
resume a stage, change configuration, or mutate a machine artifact.

## Resolving issues and editorial precedent

The ledger exposes stable issue IDs for recorded disagreements,
deterministic warnings, the active prosecutor report, adjudicator findings,
unresolved issues, and human-review requests. An editor can mark each item:

- still open / deferred;
- resolved by the editor; or
- reviewed and accepted as-is.

An issue becomes reusable editorial precedent only when all of the following
are explicit:

- the revision is approved, not merely saved as a draft;
- the issue outcome is `resolved`;
- the editor enables reuse;
- exact Latin and approved English wording are present.

Approved precedents are indexed separately from Latin corpus, Scripture,
lexical, and CPDV retrieval. On a later matching target, they are included as
`editorial_precedents` in deterministic checks and are visible to the
prosecutor and adjudicator. They are labelled human project guidance, never
source proof. Witness A and Witness B remain blind to them. A precedent change
invalidates the deterministic-check cache and downstream stages, but not the
structural parse or blind witnesses.

The first matching policy is deliberately conservative: normalized exact
Latin phrases must occur in the new target. There is no automatic fuzzy
replacement of English text.

## Partial and failed runs

Every review section carries an explicit state. Missing or failed upstream
stages force the machine status to `incomplete`, even if stale downstream data
exists. The deliberate exception is a historical adjudication re-finalized as
`human_review` with a failed-closed witness gate: its immutable old draft stays
inspectable, while the gate receipt prevents approval. Valid upstream material
remains visible. Editing is disabled until a complete immutable machine final
exists.

## Tests

```powershell
conda run -n jerome python -m unittest discover -s tests -v
```

Regression coverage includes append-only file creation, prior-file and
machine-artifact immutability, stale-save conflicts, draft exclusion from
editorial memory, explicit approved reuse, exact Latin matching, selective
pipeline cache invalidation, API method boundaries, failed/partial artifacts,
and the existing adjudicator input-budget guard.

## Deliberately deferred

Reviewer accounts, shared multi-user locking, deployment, comments detached
from a concrete issue, automatic translation replacement, and fuzzy editorial
memory matching are not part of this local iteration.
