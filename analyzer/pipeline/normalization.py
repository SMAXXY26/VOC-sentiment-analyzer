import html
import re
import unicodedata
from langchain_core.runnables import RunnableLambda
from ..schemas import NormalizedFeedback


def _detect_language(text: str) -> str:
    try:
        from langdetect import detect
        return detect(text)
    except Exception:
        return "unknown"


def _normalize(ctx: dict) -> dict:
    raw = ctx["raw_text"]

    text = re.sub(r'<[^>]+>', '', raw)  # strip HTML tags
    text = html.unescape(text)           # decode &amp; &lt; &gt; &quot; etc.
    text = unicodedata.normalize('NFKC', text)
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = text.strip()

    return {
        **ctx,
        "normalized": NormalizedFeedback(
            original=raw,
            normalized=text,
            language=_detect_language(text),
            word_count=len(text.split()),
        ),
    }


normalization_stage = RunnableLambda(_normalize)
