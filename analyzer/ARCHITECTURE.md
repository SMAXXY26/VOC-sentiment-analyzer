# Analyzer — LLM Architecture

## How a single feedback item flows

```
raw_text
    │
    ▼
[deduplication]        → checks vector DB — if duplicate, returns cached result
    │
    ▼
[normalization]        → strips HTML, fixes whitespace, detects language
    │                    RULE-BASED — no LLM
    ▼
[pii_redaction]        → removes emails, phones, credit cards via regex + spaCy NER
    │                    RULE-BASED — no LLM
    ▼
[semantic_enrichment]  → LLM: summary, key topics, entities, context
    │                    also pulls similar past feedback from vector DB (RAG)
    ▼
[taxonomy]             → LLM: category (Billing/Product/Support/Shipping), subcategory, confidence
    │
    ▼
[sentiment_emotion]    → LLM: positive/negative/neutral, emotions list, intensity 1-10
    │
    ▼
[business_signals]     → LLM: churn risk, upsell opportunity, feature requests, bug reports, competitors
    │
    ▼
[risk_escalation]      → LLM: escalate yes/no, risk level (low/medium/high/critical), suggested action
    │
    ▼
[executive_intelligence] → LLM: executive summary, action items, recommendations, health score 1-10
    │
    ▼
[store_result]         → saves full analysis to Qdrant vector DB
    │
    ▼
FeedbackAnalysis (final output)
```

---

## How LLM stages work

Every LLM stage follows the same pattern:

```python
chain = prompt | get_llm().with_structured_output(PydanticModel)
result = chain.invoke({"text": ..., ...})
```

- `get_llm()` returns a singleton `ChatOpenAI` client pointing at vLLM (`http://vllm:8000/v1`)
- `.with_structured_output(PydanticModel)` tells the LLM to return JSON that matches the schema
- The LLM never returns free text — it always returns a typed Pydantic object
- Each stage adds its result to the context dict and passes it to the next stage

---

## RAG (Retrieval Augmented Generation)

Used in `semantic_enrichment` only. Before calling the LLM, it fetches similar past feedback from Qdrant:

```
current feedback text
        ↓
embed → search Qdrant (top 3 similar past analyses)
        ↓
inject as context into the LLM prompt
        ↓
LLM produces better summary knowing what similar feedback looked like
```

This makes the LLM more consistent over time — it learns from past analyses.

---

## Two entry points

### Single item — `analyze_single(text)`
Runs the full 10-stage pipeline on one feedback item. Used by FastAPI `/analyze`.

### Batch — `analyze_batch(texts)`
Calls `analyze_single` on each item, then runs `aggregate_trends` on all results.

---

## Trend aggregation (runs after the batch, not per-item)

```python
def aggregate_trends(analyses: list[FeedbackAnalysis]) -> TrendAggregation:
```

- **Counts computed deterministically** (no LLM): sentiment distribution, escalation count, churn risk count
- **Qualitative fields use LLM**: common themes, top issues — fed all summaries and topics at once
- LLM is given all summaries in one prompt and identifies patterns across the whole batch

---

## Key design decisions

| Decision | Reason |
|---|---|
| `get_llm()` uses `lru_cache` | One shared connection to vLLM — not recreated per request |
| Each stage is a `RunnableLambda` | Stages are chained with `\|` operator (LangChain LCEL) |
| Context passed as a `dict` | Each stage reads what it needs, adds its result, passes the whole dict forward |
| `with_structured_output` | LLM returns typed Pydantic model directly — no string parsing |
| Rule-based stages first | PII is removed before any LLM ever sees the text |
| Store result last | Only saved to vector DB if the full pipeline succeeds |

---

## Output schema (`FeedbackAnalysis`)

```
FeedbackAnalysis
  ├── normalized       (original text, cleaned text, language, word count)
  ├── redacted         (PII-free text, list of PII types found)
  ├── enrichment       (summary, key_topics, entities, context)
  ├── taxonomy         (category, subcategory, confidence)
  ├── sentiment        (sentiment, emotions, intensity)
  ├── signals          (churn_risk, upsell_opportunity, feature_requests, bug_reports, competitor_mentions)
  ├── risk             (escalate, risk_level, reason, suggested_action)
  └── executive        (executive_summary, key_action_items, priority_recommendations, health_score)
```
