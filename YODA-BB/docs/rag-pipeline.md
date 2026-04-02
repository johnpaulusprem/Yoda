# CXO AI Companion — RAG Pipeline & DSPy Framework

## 1. What Is the RAG Pipeline

The **Retrieval-Augmented Generation (RAG)** pipeline powers the "Ask AI" feature — natural language Q&A across all meetings, documents, and emails. Instead of relying solely on the LLM's training data, it:

1. **Ingests** documents (PDF, DOCX, PPTX, HTML, CSV, email) into vector embeddings
2. **Retrieves** the most relevant chunks when a user asks a question
3. **Generates** an answer grounded in those chunks, with citations

The **DSPy framework** provides structured AI extraction — typed signatures for meeting summarization, action item extraction, conflict detection, and contextual Q&A with chain-of-thought reasoning.

---

## 2. Architecture Overview

```
                         INGESTION PATH
                         ═════════════
Document Upload
      │
      ▼
┌──────────────┐    ┌─────────────────┐    ┌──────────────┐    ┌─────────────┐
│  Document     │    │   Recursive     │    │    Azure      │    │  PGVector   │
│  Loaders      │ →  │   Chunker       │ →  │   Embedder    │ →  │   Store     │
│  (6 formats)  │    │  (split text)   │    │ (1536-dim)    │    │ (pgvector)  │
└──────────────┘    └─────────────────┘    └──────────────┘    └─────────────┘
                              ↑
                    IngestionPipeline orchestrates


                         RETRIEVAL PATH
                         ══════════════
User Question
      │
      ▼
┌──────────────┐    ┌─────────────────┐    ┌──────────────┐    ┌─────────────┐
│  Similarity   │    │   Context       │    │  Chain of     │    │  Citation   │
│  Retriever    │ →  │   Builder       │ →  │  Thought      │ →  │  Tracker    │
│  (embed+search│    │ (format prompt) │    │ (DSPy module) │    │ (resolve)   │
└──────────────┘    └─────────────────┘    └──────────────┘    └─────────────┘
                              ↑
                      RAGPipeline orchestrates
```

---

## 3. Directory Structure

```
rag/
├── __init__.py
├── pipeline/
│   ├── __init__.py
│   ├── ingestion_pipeline.py     # Orchestrates: chunk → embed → store
│   └── rag_pipeline.py           # Orchestrates: retrieve → context → generate → cite
├── ingestion/
│   ├── __init__.py
│   ├── base_loader.py            # ABC + shared dataclasses
│   ├── pdf_loader.py             # PyPDF2-based PDF loader
│   ├── docx_loader.py            # python-docx Word loader
│   ├── pptx_loader.py            # python-pptx PowerPoint loader
│   ├── html_loader.py            # BeautifulSoup HTML loader
│   ├── csv_loader.py             # stdlib CSV/tabular loader
│   └── email_loader.py           # RFC-822 email loader (.eml/.msg)
├── chunking/
│   ├── __init__.py
│   ├── base_chunker.py           # ABC + Chunk/ChunkMetadata dataclasses
│   └── recursive_chunker.py      # Recursive separator-based splitting
├── embeddings/
│   ├── __init__.py
│   ├── base_embedder.py          # ABC + EmbeddingResult dataclass
│   └── azure_embedder.py         # Azure OpenAI text-embedding-3-small
├── vectorstore/
│   ├── __init__.py
│   ├── base_vectorstore.py       # ABC + VectorDocument/VectorSearchResult
│   └── pgvector_store.py         # PostgreSQL + pgvector with HNSW index
├── retrieval/
│   ├── __init__.py
│   ├── base_retriever.py         # ABC + RetrievedDocument/RetrievalResult
│   └── similarity_retriever.py   # Embed query → vector search → filter
└── context/
    ├── __init__.py
    ├── context_builder.py        # Format chunks into LLM prompt with [N] citations
    └── citation_tracker.py       # Track, deduplicate, and resolve [N] references

dspy/
├── __init__.py
├── schemas.py                    # FieldType, ModuleType, FieldSpec, SignatureSpec enums
├── adapters/
│   ├── __init__.py
│   └── llm_adapter.py           # LLMAdapter + CachedLLMAdapter (wraps AIFoundryConnector)
├── modules/
│   ├── __init__.py
│   ├── predict.py                # Predict module (validate → prompt → call → parse)
│   └── chain_of_thought.py       # ChainOfThought (adds reasoning before answer)
└── signatures/
    ├── __init__.py
    ├── base_signature.py         # Metaclass-based declarative signatures
    └── rag_signatures.py         # ContextualQA, MeetingExtraction, DocumentSummary, InsightDetection
```

**Total: 27 RAG files + 10 DSPy files = 37 files**

---

## 4. Document Ingestion

### 4.1 Document Loaders

Six format-specific loaders, all extending `DocumentLoader` (ABC):

| Loader | Formats | Library | Key Features |
|--------|---------|---------|-------------|
| `PDFLoader` | `.pdf` | PyPDF2 | Page-mode splitting, optional page range, OCR flag |
| `DOCXLoader` | `.docx` | python-docx | Table extraction, comment extraction |
| `PPTXLoader` | `.pptx` | python-pptx | Slide-mode splitting, speaker notes, tables |
| `HTMLLoader` | `.html`, `.htm` | BeautifulSoup | Removes nav/scripts/styles, extracts body text |
| `CSVLoader` | `.csv` | stdlib csv | Row-based or cell-based text conversion |
| `EmailLoader` | `.eml`, `.msg` | stdlib email | Header extraction, signature stripping, HTML fallback |

**Load Modes** (configured per loader):
- `SINGLE` — Entire document as one `LoadedDocument`
- `PAGE` — Split by pages/slides (PDF, PPTX)
- `SECTION` — Split by headings

**Output**: `list[LoadedDocument]` — each containing `content` (text), `source` (file path), `mime_type`, and `DocumentMetadata` (title, author, page count, word count, tags).

**Size Limit**: Configurable, default 50 MB per file.

### 4.2 Recursive Chunking

The `RecursiveChunker` splits text into overlapping chunks using a separator hierarchy:

```
Separator priority: "\n\n" → "\n" → ". " → " "
```

**Algorithm**:
1. Try splitting on the highest-priority separator
2. If any resulting piece exceeds `chunk_size`, recurse with next separator
3. If no separators remain, hard-split at `chunk_size`
4. Merge small splits until `chunk_size` is reached
5. Apply `chunk_overlap` characters of overlap between consecutive chunks
6. Filter out chunks below `min_chunk_size`

**Default Configuration**:
| Parameter | Default | Purpose |
|-----------|---------|---------|
| `chunk_size` | 1000 chars | Target chunk size |
| `chunk_overlap` | 200 chars | Overlap between consecutive chunks |
| `min_chunk_size` | 100 chars | Discard chunks smaller than this |
| `keep_separator` | True | Re-attach separator to chunk text |

**Output**: `list[Chunk]` — each with `content`, `ChunkMetadata` (chunk_id, document_id, chunk_index, char offsets, estimated token count).

### 4.3 Embeddings

The `AzureEmbedder` generates 1536-dimension vectors via Azure OpenAI:

| Parameter | Default | Purpose |
|-----------|---------|---------|
| `model_name` | `text-embedding-3-small` | Azure OpenAI deployment |
| `dimensions` | 1536 | Vector dimensionality |
| `batch_size` | 100 | Texts per API call |
| `max_tokens` | 8191 | Maximum input tokens |
| `timeout` | 30s | API call timeout |

**Batch Processing**: Large sets are split into sub-batches of `batch_size`, each sent as a single API call. Token counts and timing are aggregated.

**Output**: `EmbeddingResult` with `vectors` (list of float arrays), `dimensions`, `token_count`, and `execution_time_ms`.

### 4.4 Vector Storage (pgvector)

The `PGVectorStore` persists embeddings in PostgreSQL using the pgvector extension:

| Parameter | Default | Purpose |
|-----------|---------|---------|
| `table_name` | `document_chunks` | Target PostgreSQL table |
| `index_type` | `hnsw` | Approximate nearest neighbor index |
| `dimensions` | 1536 | Must match embedder |
| `distance_metric` | `COSINE` | Similarity measure |
| `ef_construction` | 64 | HNSW build-time accuracy |
| `m` | 16 | HNSW max connections per node |

**Operations**:
- `upsert()` — Insert or update via `ON CONFLICT DO UPDATE`; stores vector, content, and JSONB metadata
- `search()` — Uses pgvector `<=>` (cosine distance) operator; supports optional JSONB metadata filters
- `delete()` — Remove by UUID list
- `get()` / `count()` — Single lookup / total count

**Distance Metrics**: Cosine (default), Euclidean, Dot Product — each uses a different pgvector operator.

### 4.5 Ingestion Pipeline (Orchestrator)

`IngestionPipeline` chains the three steps:

```python
# Usage
pipeline = IngestionPipeline(chunker, embedder, vector_store)
result = await pipeline.ingest_text(document_id, text, metadata)
# or
result = await pipeline.ingest_loaded_documents(loaded_docs)
```

**Flow**:
```
text → RecursiveChunker.chunk_document() → list[Chunk]
     → AzureEmbedder.embed_batch([chunk.content...]) → EmbeddingResult
     → Build VectorDocument per chunk (id, vector, content, metadata)
     → PGVectorStore.upsert(vector_docs) → count stored
```

**Output**: `IngestionResult` with `documents_processed`, `chunks_created`, `vectors_stored`, `errors`, and `execution_time_ms`.

---

## 5. Retrieval & Answer Generation

### 5.1 Similarity Retriever

`SimilarityRetriever` embeds the user's question and searches the vector store:

```python
retriever = SimilarityRetriever(embedder, vector_store, config)
result = await retriever.retrieve("What decisions were made about Q4 budget?", k=5)
```

| Parameter | Default | Purpose |
|-----------|---------|---------|
| `top_k` | 5 | Number of results to return |
| `score_threshold` | 0.3 | Minimum similarity to include |
| `max_results` | 20 | Hard upper limit |

**Flow**:
```
question → AzureEmbedder.embed(question) → query_vector
         → PGVectorStore.search(query_vector, k) → VectorSearchResult[]
         → Filter by score_threshold
         → Map to RetrievedDocument[]
         → RetrievalResult (with timing)
```

### 5.2 Context Builder

`ContextBuilder` formats retrieved chunks into an LLM-ready prompt with numbered citations:

```python
builder = ContextBuilder(config)
context = builder.build(retrieved_documents)
# context.formatted_text → "[1]\nSource: Q3 Board Meeting\n..."
```

| Parameter | Default | Purpose |
|-----------|---------|---------|
| `max_context_tokens` | 4000 | Token budget for context |
| `citation_style` | `"numbered"` | `[1]`, `[2]`, etc. |
| `include_metadata` | True | Add source titles |
| `separator` | `"\n\n---\n\n"` | Between chunks |

**Token Budgeting**: Chunks are added in relevance order until the estimated token count exceeds `max_context_tokens`. Remaining chunks are discarded.

**Output**: `RetrievalContext` with `formatted_text`, `chunks` (list of `ContextChunk`), `total_tokens_estimate`, and `num_sources`.

### 5.3 Citation Tracker

`CitationTracker` registers sources and resolves `[N]` references in the generated answer:

```python
tracker = CitationTracker()
idx = tracker.add_source(SourceReference(source_id="abc", title="Q3 Board Meeting"))
# idx = 1

# After LLM generates answer with "[1]" references:
citations = tracker.resolve_citations("As discussed in [1], the budget was approved.")
# → [Citation(index=1, source=SourceReference(...), ...)]
```

**Features**:
- **Deduplication**: Same `source_id` returns existing index
- **Resolution**: Regex `\[(\d+)\]` finds all markers in text
- **Bibliography**: `format_bibliography()` generates `[1] Title (URL)` list

### 5.4 RAG Pipeline (Orchestrator)

`RAGPipeline` chains retrieval → context → generation → citation in a single call:

```python
rag = RAGPipeline(retriever, context_builder, citation_tracker, dspy_module, config)
result = await rag.query("What were the Q4 budget decisions?", user_id="user-123")
```

| Parameter | Default | Purpose |
|-----------|---------|---------|
| `top_k` | 5 | Retrieved documents |
| `include_citations` | True | Enable citation tracking |
| `max_context_tokens` | 4000 | Context token budget |
| `model` | `"gpt-4o"` | LLM for generation |
| `temperature` | 0.3 | LLM temperature |

**Full Flow**:
```
1. SimilarityRetriever.retrieve(question, k=top_k)
   → RetrievalResult (timed)

2. ContextBuilder.build(retrieved_documents)
   → RetrievalContext (formatted_text with [N] markers)

3. CitationTracker.add_source() for each retrieved document
   → Registers sources with indices

4. ChainOfThought.forward(contexts=formatted_text, question=question)
   → ChainOfThoughtResult (answer + rationale + reasoning_steps + confidence)

5. CitationTracker.resolve_citations(answer)
   → list[Citation] matching [N] markers in answer text

6. Return RAGResult:
   - answer: str
   - sources: list[RetrievedDocument]
   - citations: list[Citation]
   - confidence: float | None
   - rationale: str
   - reasoning_steps: list[str]
   - retrieval_time_ms, generation_time_ms, total_time_ms
```

---

## 6. DSPy Framework

### 6.1 What DSPy Does Here

DSPy provides **structured AI extraction** — instead of writing raw prompts, you declare input/output fields as typed signatures. The framework:

1. **Formats** the prompt from field descriptions and values
2. **Calls** the LLM via an adapter
3. **Parses** the response into structured key-value pairs
4. **Validates** outputs against the signature contract

This eliminates prompt engineering fragility and makes AI outputs type-safe.

### 6.2 Signatures (Declarative Contracts)

Signatures use a metaclass (`SignatureMeta`) to auto-discover `InputField` and `OutputField` declarations:

```python
class ContextualQA(Signature):
    """Answer questions using provided context passages."""

    contexts = InputField(description="Retrieved context with [n] markers")
    question = InputField(description="User's question")

    reasoning = OutputField(description="Step-by-step reasoning")
    answer    = OutputField(description="Comprehensive answer")
    confidence = OutputField(description="Score 0.0 to 1.0")
    citations = OutputField(description="Comma-separated citation numbers")
```

**Four signatures defined**:

| Signature | Purpose | Key Outputs |
|-----------|---------|-------------|
| `ContextualQA` | RAG Q&A | answer, reasoning, confidence, citations |
| `MeetingExtraction` | Post-meeting processing | summary, action_items (JSON), decisions (JSON), key_topics, unresolved_questions |
| `DocumentSummary` | Document ingestion | summary, key_points (JSON), entities (JSON) |
| `InsightDetection` | Conflict detection | conflicts (JSON), severity, recommendation |

### 6.3 Modules (Execution Engines)

**Predict** — Basic execution:
```
validate_inputs → format_prompt → [prepend demos] → call LLM → parse_output → validate_outputs
```

**ChainOfThought** — Adds reasoning before the answer:
```
validate_inputs → format_prompt → inject "Let's think step by step." →
[prepend demos] → call LLM → extract_rationale → parse_reasoning_steps →
parse_output → extract_confidence → validate_outputs
```

Both support **few-shot demos** via `set_demos()` / `add_demo()`.

### 6.4 LLM Adapters

| Adapter | Purpose |
|---------|---------|
| `LLMAdapter` | Wraps `AIFoundryConnector`, handles message formatting |
| `CachedLLMAdapter` | Adds in-memory response caching with TTL (SHA-256 key from prompt+model+temperature) |

**Configuration**:
| Parameter | Default | Purpose |
|-----------|---------|---------|
| `default_temperature` | 0.1 | Low for structured extraction |
| `max_tokens` | 4096 | Response limit |
| `default_model` | `gpt-4o-mini` | Fast model for extraction |
| `cache_enabled` | False | Enable response caching |
| `cache_ttl_seconds` | 3600 | Cache expiration (1 hour) |
| `retry_count` | 3 | Retries on failure |

---

## 7. Dependency Injection

All RAG and DSPy components are wired via `dependencies.py`:

```python
get_embedder()          → AzureEmbedder (singleton)
get_vector_store()      → PGVectorStore (singleton, uses session_factory)
get_chunker()           → RecursiveChunker (singleton)
get_retriever()         → SimilarityRetriever (singleton, uses embedder + vector_store)
get_context_builder()   → ContextBuilder (singleton)
get_citation_tracker()  → CitationTracker (per-request, stateful)
get_ingestion_pipeline()→ IngestionPipeline (singleton, uses chunker + embedder + vector_store)
get_rag_pipeline()      → RAGPipeline (singleton, uses retriever + context_builder + citation_tracker + dspy_module)
get_llm_adapter()       → CachedLLMAdapter (singleton, wraps AIFoundryConnector)
```

**Singletons** reuse connections and caches across requests. **Per-request** components (CitationTracker) maintain per-query state.

---

## 8. Data Flow Diagrams

### 8.1 Document Upload → Searchable

```
User uploads PDF
      │
      ▼
DocumentService.upload()
      │
      ▼
PDFLoader.load() → list[LoadedDocument]
      │
      ▼
IngestionPipeline.ingest_loaded_documents()
      ├── RecursiveChunker.chunk_document()
      │   └── 1000-char chunks with 200-char overlap
      ├── AzureEmbedder.embed_batch()
      │   └── 1536-dim vectors via text-embedding-3-small
      └── PGVectorStore.upsert()
          └── INSERT INTO document_chunks (id, content, embedding, metadata)

Document is now searchable via vector similarity.
```

### 8.2 User Asks a Question

```
"What decisions were made about Q4 budget?"
      │
      ▼
RAGPipeline.query()
      │
      ├─── 1. SimilarityRetriever.retrieve()
      │         ├── AzureEmbedder.embed(question) → query vector
      │         ├── PGVectorStore.search(query_vector, k=5)
      │         │   └── SELECT ... ORDER BY embedding <=> $1 LIMIT 5
      │         └── Filter results where score > 0.3
      │
      ├─── 2. ContextBuilder.build(results)
      │         └── "[1]\nSource: Q3 Board Meeting\n..."
      │             (up to 4000 tokens)
      │
      ├─── 3. CitationTracker.add_source() per result
      │
      ├─── 4. ChainOfThought.forward(contexts=..., question=...)
      │         ├── ContextualQA signature formats prompt
      │         ├── "Let's think step by step." injected
      │         ├── CachedLLMAdapter.call() → GPT-4o
      │         └── Parse: answer, reasoning, confidence, citations
      │
      └─── 5. CitationTracker.resolve_citations(answer)
                └── Match [1], [2] markers → Citation objects

Response:
{
  "answer": "The Q4 budget was approved at $2.1M [1], with...",
  "citations": [{"index": 1, "source": {"title": "Q3 Board Meeting"}}],
  "confidence": 0.87,
  "rationale": "Based on the Q3 board meeting transcript...",
  "reasoning_steps": ["Step 1: ...", "Step 2: ..."]
}
```

### 8.3 Meeting Post-Processing

```
Meeting ends → CallDisconnected callback
      │
      ▼
AIProcessor.process_meeting()
      │
      ├── ChainOfThought.forward() with MeetingExtraction signature
      │   ├── Input: transcript, subject, participants
      │   └── Output: summary, action_items, decisions, key_topics, unresolved_questions
      │
      ├── Parse JSON outputs → ActionItem[], decisions[], key_topics[]
      │
      ├── OwnerResolver: match assignee names → user IDs
      │
      ├── Store: MeetingSummary + ActionItems + MeetingInsights
      │
      └── ConflictDetectionService.detect_conflicts()
          ├── ChainOfThought.forward() with InsightDetection signature
          └── Store: MeetingInsight(insight_type="conflict_detection")
```

---

## 9. Configuration Reference

### Environment Variables

| Variable | Used By | Purpose |
|----------|---------|---------|
| `AI_FOUNDRY_ENDPOINT` | AzureEmbedder, LLMAdapter | Azure OpenAI endpoint |
| `AI_FOUNDRY_API_KEY` | AzureEmbedder, LLMAdapter | API key |
| `DATABASE_URL` | PGVectorStore | PostgreSQL connection (with pgvector) |

### Tuning Parameters

| Parameter | Location | Default | Effect |
|-----------|----------|---------|--------|
| Chunk size | RecursiveChunkerConfig | 1000 | Larger = more context per chunk, fewer chunks |
| Chunk overlap | RecursiveChunkerConfig | 200 | Larger = better continuity, more storage |
| Top-k | RAGConfig | 5 | More results = broader context, slower |
| Score threshold | SimilarityRetrieverConfig | 0.3 | Higher = stricter relevance, fewer results |
| Max context tokens | RAGConfig | 4000 | Higher = more context to LLM, more cost |
| Temperature | RAGConfig | 0.3 | Lower = more deterministic answers |
| Cache TTL | AdapterConfig | 3600s | Higher = more cache hits, staler answers |

---

## 10. Extension Points

### Adding a New Document Loader

1. Create `rag/ingestion/xlsx_loader.py`
2. Extend `DocumentLoader` ABC
3. Implement `load()` and `supports_source()`
4. Register in `IngestionPipeline` or loader registry

### Adding a New Retrieval Strategy

1. Create `rag/retrieval/hybrid_retriever.py`
2. Extend `BaseRetriever` ABC
3. Implement `retrieve()` (e.g., combine keyword + vector search)
4. Swap in `dependencies.py`

### Adding a New DSPy Signature

1. Add to `dspy/signatures/rag_signatures.py`
2. Define `InputField` and `OutputField` declarations
3. Use via `Predict.forward()` or `ChainOfThought.forward()`

### Swapping Vector Stores

1. Create `rag/vectorstore/qdrant_store.py`
2. Extend `BaseVectorStore` ABC
3. Implement `upsert()`, `search()`, `delete()`, `get()`, `count()`
4. Update `dependencies.py` to return new store

---

## 11. Design Decisions

| Decision | Rationale |
|----------|-----------|
| **pgvector over Pinecone/Weaviate** | Same database as relational data; no extra infra; HNSW index is fast enough for <1M vectors |
| **text-embedding-3-small over text-embedding-3-large** | 1536 dims is sufficient for meeting/document search; lower cost and latency |
| **Recursive chunking over fixed-size** | Respects document structure (paragraphs, sentences); produces more semantically coherent chunks |
| **200-char overlap** | Prevents information loss at chunk boundaries; ~50 tokens of context carried forward |
| **Custom DSPy over dspy library** | Full control over prompt formatting, parsing, and error handling; no external dependency |
| **Chain-of-thought for RAG** | Step-by-step reasoning improves factual accuracy; rationale is visible to users |
| **Per-request CitationTracker** | Each query has independent citation numbering; no cross-request state leakage |
| **CachedLLMAdapter** | Identical questions within TTL avoid redundant API calls; SHA-256 keying prevents collisions |
| **ABC for every component** | Enables testing with mocks; future swap (e.g., Qdrant, Cohere embeddings) requires no pipeline changes |
