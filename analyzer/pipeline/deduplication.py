import os

from dotenv import load_dotenv
from langchain_core.runnables import RunnableLambda

load_dotenv()


def _deduplicate(ctx: dict) -> dict:
    try:
        from vectordb.store import find_duplicates
        threshold = float(os.getenv("DEDUP_THRESHOLD", "0.95"))
        matches = find_duplicates(ctx["raw_text"], threshold=threshold)
        if matches:
            ctx["duplicate_of"] = matches[0]
    except Exception:
        pass  # never block pipeline if vector DB is unavailable
    return ctx


deduplication_stage = RunnableLambda(_deduplicate)
