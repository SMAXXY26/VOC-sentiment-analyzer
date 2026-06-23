import os
from functools import reduce

from ..metrics import timed_stage
from .business_signals import business_signals_stage
from .combined_classification import combined_classification_stage
from .confidence_stage import confidence_stage
from .executive_intelligence import executive_intelligence_stage
from .experience_scoring import experience_scoring_stage
from .normalization import normalization_stage
from .pii_redaction import pii_redaction_stage
from .risk_escalation import risk_escalation_stage
from .semantic_enrichment import semantic_enrichment_stage
from .sentiment_emotion import sentiment_emotion_stage
from .store_result import store_result_stage
from .taxonomy import taxonomy_stage

# Deduplication is handled in analyze_single (main.py) BEFORE pipeline.invoke()
# so it short-circuits before any LLM stages run. deduplication_stage was
# previously in this chain but never short-circuited — it just hit Qdrant twice.
#
# confidence_stage runs after all LLM stages, before store_result_stage,
# so pipeline_confidence is stored alongside the analysis.
#
# Each stage is wrapped with timed_stage() so its wall time lands in the
# pipeline_stage_duration_seconds{stage="..."} histogram (scraped by Prometheus).
# MERGE_CLASSIFICATION=true collapses taxonomy + sentiment_emotion + business_signals into a
# single LLM call (combined_classification_stage), which re-splits its result back into the same
# ctx keys — so downstream stages are unchanged. Default is the proven 3-call path; flip the env
# var to A/B the merge against the gold set (eval/) before committing to it.
_merge = os.getenv("MERGE_CLASSIFICATION", "false").lower() in ("1", "true", "yes")

_classification_stages = (
    [timed_stage("classification", combined_classification_stage)]
    if _merge
    else [
        timed_stage("taxonomy", taxonomy_stage),
        timed_stage("sentiment_emotion", sentiment_emotion_stage),
        timed_stage("business_signals", business_signals_stage),
    ]
)

_stages = [
    timed_stage("normalization", normalization_stage),
    timed_stage("pii_redaction", pii_redaction_stage),
    timed_stage("semantic_enrichment", semantic_enrichment_stage),
    *_classification_stages,
    timed_stage("risk_escalation", risk_escalation_stage),
    timed_stage("executive_intelligence", executive_intelligence_stage),
    timed_stage("experience_scoring", experience_scoring_stage),
    timed_stage("confidence", confidence_stage),
    timed_stage("store_result", store_result_stage),
]

pipeline = reduce(lambda a, b: a | b, _stages)
