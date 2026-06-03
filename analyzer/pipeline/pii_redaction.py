import re
from functools import lru_cache

from langchain_core.runnables import RunnableLambda

from ..schemas import RedactedFeedback

_PATTERNS: list[tuple[str, str]] = [
    ("EMAIL",       r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b'),
    ("PHONE",       r'\b(\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}\b'),
    ("SSN",         r'\b\d{3}-\d{2}-\d{4}\b'),
    # Require separator between every group — avoids false-positives on
    # long order/product IDs like 1234567890123456 (no spaces/dashes).
    ("CREDIT_CARD", r'\b\d{4}[\s-]\d{4}[\s-]\d{4}[\s-]\d{4}\b'),
    ("ZIP_CODE",    r'\b\d{5}(?:-\d{4})?\b'),
]


@lru_cache(maxsize=1)
def _load_nlp():
    import spacy
    return spacy.load("en_core_web_sm")


def _redact(ctx: dict) -> dict:
    text: str = ctx["normalized"].normalized
    pii_found: list[str] = []

    for label, pattern in _PATTERNS:
        if re.search(pattern, text):
            pii_found.append(label)
            text = re.sub(pattern, f"[{label}]", text)

    nlp = _load_nlp()
    doc = nlp(text)
    for ent in doc.ents:
        if ent.label_ == "PERSON" and ent.text not in ("[NAME]",):
            pii_found.append("PERSON_NAME")
            text = text.replace(ent.text, "[NAME]")

    return {
        **ctx,
        "redacted": RedactedFeedback(
            text=text,
            pii_types_found=list(set(pii_found)),
        ),
    }


pii_redaction_stage = RunnableLambda(_redact)
