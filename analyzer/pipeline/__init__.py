from ..metrics import timed_stage
from .business_signals import business_signals_stage
from .confidence_stage import confidence_stage
from .executive_intelligence import executive_intelligence_stage
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
pipeline = (
    timed_stage("normalization", normalization_stage)
    | timed_stage("pii_redaction", pii_redaction_stage)
    | timed_stage("semantic_enrichment", semantic_enrichment_stage)
    | timed_stage("taxonomy", taxonomy_stage)
    | timed_stage("sentiment_emotion", sentiment_emotion_stage)
    | timed_stage("business_signals", business_signals_stage)
    | timed_stage("risk_escalation", risk_escalation_stage)
    | timed_stage("executive_intelligence", executive_intelligence_stage)
    | timed_stage("confidence", confidence_stage)
    | timed_stage("store_result", store_result_stage)
)
