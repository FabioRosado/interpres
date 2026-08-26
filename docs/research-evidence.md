# Research and evidence contracts

The “research agent” is a bounded evidence exchange, not an LLM whose memory
is treated as authority. `prosecutor_initial` and `adjudicator_initial` may
propose typed requests. The separately cached `research_prosecutor` and
`research_adjudicator` stages execute those requests and return inspectable
receipts. Models only interpret the receipts in the following grounded stage.

`evidence.prosecutor_research_rounds` and
`evidence.adjudicator_research_rounds` accept `0` or `1`. Requests per round,
results per request, and prompt-facing snippet length are independently capped.
Unsupported kinds, missing subsystems, a configured index with no match, and a
provider error have distinct statuses. Expected absence (`unavailable`) and a
successful lookup with no match (`no_evidence_found`) remain receipts that a
grounded model can reason about. A genuine execution exception produces an
`error` receipt, fails the independently cached research stage, and leaves the
pipeline incomplete; the failed receipt is retained for inspection and retry.

The initial prosecutor is constrained to at most twelve consolidated
challenges and `evidence.max_requests_per_round` prioritized requests. Its
persisted structural, lexical, deterministic-check, and annotation inputs are
serialized losslessly without display whitespace. This keeps large chunks
inside the configured provider context without omitting evidence. Production
allows 4,200 prosecutor output tokens so a compliant report has room to close
its JSON; the lightweight smoke profile remains at 3,200.

## Jerome concordance and local RAG

`build-concordance` writes stable source-unit records containing exact Latin,
normalized Latin, deterministic lemmas, fingerprints, page, book, and source
provenance. Exact or lemma lookup is preferred for a specific form/phrase.
Each exact/lemma hit also returns the immediately preceding and following
source units from the same book, with separate provenance. Prompt-facing hit
and context text are independently bounded; context never crosses a book
boundary.

`build-retrieval-index` builds a deterministic normalized-Latin unigram/bigram
TF-IDF index plus truncated SVD/LSA components. The JSON artifact persists the
vocabulary, weights, components, vectors, source digest, actual Latin, and
provenance. Search uses a lexical/LSA hybrid score and deterministic tie order.
Receipts contain retrieved Latin, never only a model-generated summary.

## Scripture and English comparisons

The local Clementine Vulgate is textual evidence. CPDV and ODR are comparison
aids only. ODR is optional JSONL at `paths.odr`; each line uses:

```json
{"book_order":21,"chapter":38,"verse":4,"text":"My heart became hot within me."}
```

`order` may replace `book_order`. Lookup receipts retain separate
`source_annotation_verified` and `textual_match_verified` flags. CPDV/ODR
presence never upgrades an unverified Latin match.
Near-phrase matching scores query-sized windows inside each Vulgate verse, so
a short quotation is not penalized merely because the verse contains more
text. Near candidates remain unverified until interpretation confirms them.

## Project-local authorities

Chronology, proper-name, and source-edition lookups use optional JSONL files at
the corresponding `paths.*_authority` entries. Records remain visible in the
receipt. The supported minimum contract is:

```json
{"entry_id":"chron-001","label":"Nebuchadnezzar chronology","aliases":["Nabuchodonosor"],"text":"Inspectable authority statement for 597 BCE.","citation":"Exact source locator"}
```

`entry_id`, `label`, `aliases`, `text`, and `citation` are recommended.
Matching is deterministic token overlap over labels/text/aliases and preserves
numeric chronology tokens. A missing file yields `unavailable`; an available
file with no match yields `no_evidence_found`.

## Optional external research

External search is disabled by default and requires a project-injected backend
implementing `backend_name` and `search(query, limit=...)`. Every returned item
is forced to `result_class: research_lead` and
`verified_evidence: false`. A lead must be followed to a primary or scholarly
source before it can support a decision; arbitrary web content is never
silently promoted to verified evidence.
