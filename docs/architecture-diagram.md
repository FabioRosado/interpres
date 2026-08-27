# Architecture Diagrams

Visual explanations of how Interpres works. These diagrams use [Mermaid](https://mermaid.js.org/) syntax, which renders in GitHub, GitLab, and most markdown viewers.

## Table of contents

- [High-level pipeline](#high-level-pipeline)
- [Stage detail: Witness and validation](#stage-detail-witness-and-validation)
- [Stage detail: Prosecutor and evidence](#stage-detail-prosecutor-and-evidence)
- [Stage detail: Adjudication and finalization](#stage-detail-adjudication-and-finalization)
- [Cache and provenance flow](#cache-and-provenance-flow)
- [Reviewer UI data flow](#reviewer-ui-data-flow)
- [Project structure](#project-structure)

## High-level pipeline

```mermaid
flowchart TD
    A["📜 Latin Source<br/>(Corpus Corporum)"] --> B["Preprocessor<br/>(parse + chunk)"]
    B --> C["Processing Chunks<br/>(target + context)"]
    
    C --> D["🔍 Deterministic Checks<br/>(morphology + glossary)"]
    C --> E["🧠 Structural Parser<br/>(blind parse)"]
    
    E --> F["👁️ Witness A<br/>(independent translation)"]
    E --> G["👁️ Witness B<br/>(independent translation)"]
    
    F --> H["✅ Witness Validation<br/>(integrity checks)"]
    G --> I["✅ Witness Validation<br/>(integrity checks)"]
    
    H --> J["🚦 Quorum Gate<br/>(both/single/both-invalid)"]
    I --> J
    
    J -->|both_valid| K["🔎 Prosecutor<br/>(challenges + evidence)"]
    J -->|single_valid| L["⚠️ Human Review<br/>(mandatory)"]
    J -->|both_invalid| M["🛑 Stop<br/>(cannot proceed)"]
    
    K --> N["📚 Evidence Retrieval<br/>(concordance + Vulgate + CPDV)"]
    N --> K
    
    K --> O["⚖️ Adjudicator<br/>(selects edits)"]
    O --> P["🏁 Finalizer<br/>(policy enforcement)"]
    
    P -->|accepted/corrected| Q["📊 Human Review<br/>(read-only UI)"]
    P -->|human_review| Q
    P -->|unresolved| Q
    
    Q --> R["✅ Editorial Precedent<br/>(append-only)"]
    R --> S["🔒 Immutable Audit<br/>(JSONL trail)"]
    
    style L fill:#ffeb3b
    style M fill:#f44336
    style Q fill:#e3f2fd
    style R fill:#c8e6c9
    style S fill:#e8eaf6
```

## Stage detail: Witness and validation

```mermaid
flowchart LR
    A["Target Latin<br/>(closed element)"] --> B["👁️ Witness A"]
    A --> C["👁️ Witness B"]
    
    B --> D["Raw Response<br/>(immutable)"]
    C --> E["Raw Response<br/>(immutable)"]
    
    D --> F["Validation Checks"]
    E --> G["Validation Checks"]
    
    subgraph F [Witness A Validation]
        F1["Exact target identity"]
        F2["Provider stop/token receipt"]
        F3["Commentary/fence detection"]
        F4["Source-copying signals"]
        F5["Proper-name multiplicity"]
        F6["Coverage-length signals"]
    end
    
    subgraph G [Witness B Validation]
        G1["Exact target identity"]
        G2["Provider stop/token receipt"]
        G3["Commentary/fence detection"]
        G4["Source-copying signals"]
        G5["Proper-name multiplicity"]
        G6["Coverage-length signals"]
    end
    
    F --> H["Quorum Gate"]
    G --> H
    
    H -->|both_valid| I["Normal path"]
    H -->|single_valid| J["Degraded path<br/>(human review required)"]
    H -->|both_invalid| K["Stop"]
    
    style I fill:#c8e6c9
    style J fill:#ffeb3b
    style K fill:#f44336
```

### Key principle: Witness independence

Witnesses receive **only** the target Latin. They do not receive:
- Morphology or glossary
- Structural parse output
- The other witness's translation
- Prosecutor or adjudicator output
- External English translations

This ensures independence. Agreement is interesting but not proof.

## Stage detail: Prosecutor and evidence

```mermaid
flowchart TD
    A["Prosecutor Initial"] --> B{"Challenges<br/>detected?"}
    
    B -->|No| C["No evidence needed"]
    B -->|Yes| D{"Evidence<br/>requested?"}
    
    D -->|No| E["Prosecutor Grounded<br/>(challenges only)"]
    D -->|Yes| F["Evidence Retrieval"]
    
    subgraph F [Evidence Sources]
        F1["📚 Concordance<br/>(exact/normalized/lemma)"]
        F2["🔍 TF-IDF/LSA Index<br/>(semantic search)"]
        F3["📖 Vulgate<br/>(Clementine)"]
        F4["🌐 CPDV<br/>(English comparison)"]
        F5["📝 Whitaker<br/>(morphology)"]
        F6["🏛️ Authorities<br/>(proper names, dates)"]
        F7["🌍 Web Research<br/>(optional, unverified)"]
    end
    
    F --> G["Research Receipts<br/>(immutable)"]
    G --> E
    
    E --> H["Prosecutor Grounded<br/>(challenges + evidence)"]
    
    style F fill:#e3f2fd
    style G fill:#c8e6c9
```

### Evidence contracts

Evidence retrieval is a **bounded exchange**, not a knowledge base:

1. Prosecutor proposes typed requests (exact, normalized, lemma, scripture, etc.)
2. Retrieval executes and returns receipts (hit/miss/no-match/error)
3. Prosecutor interprets receipts in the grounded stage
4. Receipts are persisted and verified — never summarized by a model

## Stage detail: Adjudication and finalization

```mermaid
flowchart TD
    A["Adjudicator Initial"] --> B{"Edits<br/>needed?"}
    
    B -->|No| C["Accept witness base"]
    B -->|Yes| D{"Evidence<br/>requested?"}
    
    D -->|No| E["Adjudicator<br/>(edits only)"]
    D -->|Yes| F["Targeted Evidence"]
    F --> E
    
    E --> G["Finalizer"]
    
    subgraph G [Finalizer Checks]
        G1["Quorum enforcement"]
        G2["Evidence citation verification"]
        G3["Grade-A/B requirement"]
        G4["Edit size limits"]
        G5["High-severity support check"]
        G6["Unresolved normalization"]
    end
    
    G -->|Pass| H["✅ Accepted / Corrected"]
    G -->|Large edits| I["⚠️ Human Review"]
    G -->|Insufficient evidence| J["⚠️ Human Review"]
    G -->|Unresolved| K["📋 Unresolved"]
    
    style H fill:#c8e6c9
    style I fill:#ffeb3b
    style J fill:#ffeb3b
    style K fill:#fff3e0
```

### Finalizer policy

The finalizer applies deterministic rules:

| Rule | Threshold |
|------|-----------|
| Large edit → human review | >48 words per edit |
| Cumulative edits → human review | >96 words total |
| Replacement ratio → human review | >25% of target |
| Grade-A/B required | For positive claims |
| High-severity finding support | Each needs deterministic support or receipt |
| Degraded quorum | Blocks automatic acceptance |

## Cache and provenance flow

```mermaid
flowchart LR
    A["Input<br/>(chunk + config)"] --> B["Content Hash<br/>(SHA-256)"]
    B --> C{"Cache<br/>hit?"}
    
    C -->|Yes| D["Return cached<br/>(immutable)"]
    C -->|No| E["Execute stage"]
    
    E --> F["Compute output"]
    F --> G["Hash output"]
    G --> H["Store in cache<br/>(content-addressed)"]
    H --> I["Return output"]
    
    D --> J["Downstream stage"]
    I --> J
    
    J --> K["Dependency lineage<br/>(recorded)"]
    
    style H fill:#c8e6c9
    style K fill:#e8eaf6
```

### Provenance chain

Each stage record contains:
- Stage name and chunk ID
- Input hash (dependency lineage)
- Output hash
- Model/provider identity (if applicable)
- Prompt digest
- Timestamp
- Raw response (immutable)

If any input changes, the cache key changes, and the stage recomputes.

## Reviewer UI data flow

```mermaid
flowchart TD
    A["Audit JSONL"] --> B["Review Server"]
    B --> C["Browser UI"]
    
    C --> D["Read-only<br/>Machine Final"]
    C --> E["Editable<br/>Human Translation"]
    C --> F["Issue<br/>Ledger"]
    
    E -->|Save| G["Append-only<br/>Revision JSON"]
    F -->|Save| G
    
    G --> H["Editorial<br/>Precedent Index"]
    
    H --> I["Next chunk<br/>deterministic checks"]
    
    style D fill:#f5f5f5
    style G fill:#c8e6c9
    style H fill:#e8eaf6
```

### Reviewer API

The reviewer server exposes a minimal API:

| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `/api/health` | Health check |
| GET | `/api/chunks` | List available chunks |
| GET | `/api/chunks/{id}` | Get chunk data |
| POST | `/api/chunks/{id}/editorial/revisions` | Save revision |

All other methods return 405. The server never invokes models, changes config, or mutates machine artifacts.

## Project structure

```mermaid
flowchart TD
    A["interpres/"] --> B["interpres/<br/>(Python package)"]
    A --> C["projects/<br/>(project configs)"]
    A --> D["tests/<br/>(regression tests)"]
    A --> E["docs/<br/>(documentation)"]
    A --> F["scripts/<br/>(utilities)"]
    
    B --> B1["cli.py<br/>(commands)"]
    B --> B2["pipeline.py<br/>(orchestration)"]
    B --> B3["evidence.py<br/>(retrieval)"]
    B --> B4["witnesses.py<br/>(validation)"]
    B --> B5["source.py<br/>(parsing)"]
    B --> B6["cache.py<br/>(provenance)"]
    B --> B7["review.py<br/>(UI backend)"]
    
    C --> C1["jerome-ezekiel/<br/>(Jerome project)"]
    C1 --> C1a["project.yaml"]
    C1 --> C1b["pipeline.yaml"]
    C1 --> C1c["book1.txt"]
    C1 --> C1d["challenges/"]
    C1 --> C1e["editorial/"]
    
    D --> D1["test_*.py<br/>(158 provider-free tests)"]
    
    E --> E1["architecture.md"]
    E --> E2["getting-started.md"]
    E --> E3["usage.md"]
    E --> E4["command-reference.md"]
    E --> E5["reviewer-ui.md"]
    E --> E6["data-and-licensing.md"]
    
    style B fill:#e3f2fd
    style C fill:#fff3e0
    style D fill:#f3e5f5
    style E fill:#e8f5e9
```

## Data flow summary

```mermaid
flowchart LR
    A["Source Text"] --> B["Parse"]
    B --> C["Chunk"]
    C --> D["Deterministic<br/>Checks"]
    C --> E["Structural<br/>Parse"]
    
    E --> F["Witness A"]
    E --> G["Witness B"]
    
    F --> H["Validate"]
    G --> I["Validate"]
    
    H --> J["Quorum"]
    I --> J
    
    J --> K["Prosecute"]
    K --> L["Evidence"]
    L --> K
    
    K --> M["Adjudicate"]
    M --> N["Finalize"]
    
    N --> O["Human<br/>Review"]
    O --> P["Editorial<br/>Precedent"]
    
    D --> N
    E --> N
    F --> N
    G --> N
    H --> N
    I --> N
    J --> N
    K --> N
    L --> N
    M --> N
    
    style D fill:#ffeb3b
    style H fill:#ffeb3b
    style I fill:#ffeb3b
    style J fill:#ff9800
    style O fill:#e3f2fd
    style P fill:#c8e6c9
```

## Trust boundaries

```mermaid
flowchart TD
    A["Untrusted<br/>(Models, Providers)"] -->|Immutable record| B["Trust Boundary"]
    
    B --> C["Deterministic<br/>Validation"]
    B --> D["Content-Addressed<br/>Cache"]
    B --> E["Evidence<br/>Receipts"]
    B --> F["Human<br/>Review"]
    
    C --> G["Trusted Output<br/>(accepted/corrected)"]
    D --> G
    E --> G
    F --> G
    
    style A fill:#f44336
    style B fill:#ff9800
    style G fill:#c8e6c9
```

### Trust principles

1. **Models are untrusted**: Their output is recorded but not trusted
2. **Deterministic checks are trusted**: Rules are explicit and reproducible
3. **Evidence receipts are trusted**: They are persisted and verified, not summarized
4. **Human review is trusted**: Only explicit human approval creates precedent
5. **Cache integrity is trusted**: Content-addressed hashes detect tampering
