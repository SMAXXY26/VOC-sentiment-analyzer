from .normalization import normalization_stage
from .pii_redaction import pii_redaction_stage
from .semantic_enrichment import semantic_enrichment_stage
from .taxonomy import taxonomy_stage
from .sentiment_emotion import sentiment_emotion_stage
from .business_signals import business_signals_stage
from .risk_escalation import risk_escalation_stage
from .executive_intelligence import executive_intelligence_stage
from .confidence_stage import confidence_stage
from .store_result import store_result_stage

# Deduplication is handled in analyze_single (main.py) BEFORE pipeline.invoke()
# so it short-circuits before any LLM stages run. deduplication_stage was
# previously in this chain but never short-circuited — it just hit Qdrant twice.
#
# confidence_stage runs after all LLM stages, before store_result_stage,
# so pipeline_confidence is stored alongside the analysis.
pipeline = (
    normalization_stage
    | pii_redaction_stage
    | semantic_enrichment_stage
    | taxonomy_stage
    | sentiment_emotion_stage
    | business_signals_stage
    | risk_escalation_stage
    | executive_intelligence_stage
    | confidence_stage
    | store_result_stage
)
