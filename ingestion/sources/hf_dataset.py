"""Ingest a public CX dataset from the HuggingFace Hub into RawFeedback records.

Used to fill the Qdrant `feedback_analyses` collection (dedup / RAG / clustering /
drift) with real customer-experience text — NOT the SQLite EDBMS the chatbot/webpage
uses. Run it through the pipeline via scripts/load_cx_data.py.

Defaults to a non-gated customer-support / review dataset; override --dataset to use
any HF dataset with a free-text field.
"""

from __future__ import annotations

import uuid

from ..base import BaseIngester
from ..schema import FeedbackSource, RawFeedback


class HFDatasetIngester(BaseIngester):
    """Pull rows from a HuggingFace dataset and map them to RawFeedback.

    text_field   — column holding the feedback text
    rating_field — optional column with a 1–5 star rating
    limit        — cap rows (keep GPU time sane); None = all
    """

    def __init__(
        self,
        dataset: str = "argilla/customer_assistant",
        split: str = "train",
        text_field: str = "text",
        rating_field: str | None = None,
        limit: int | None = 200,
    ):
        self.dataset = dataset
        self.split = split
        self.text_field = text_field
        self.rating_field = rating_field
        self.limit = limit

    def ingest(self, **kwargs) -> list[RawFeedback]:
        from datasets import load_dataset

        # streaming=True avoids downloading the whole dataset when we only want N rows.
        ds = load_dataset(self.dataset, split=self.split, streaming=True)

        records: list[RawFeedback] = []
        for row in ds:
            text = (row.get(self.text_field) or "").strip()
            if not text:
                continue

            rating = None
            if self.rating_field and row.get(self.rating_field) is not None:
                try:
                    r = float(row[self.rating_field])
                    rating = min(5.0, max(1.0, r))  # clamp into the 1–5 schema range
                except (TypeError, ValueError):
                    rating = None

            records.append(
                RawFeedback(
                    id=str(uuid.uuid4()),
                    source=FeedbackSource.api,
                    text=text[:2000],
                    rating=rating,
                    metadata={"hf_dataset": self.dataset, "hf_split": self.split},
                )
            )
            if self.limit is not None and len(records) >= self.limit:
                break

        return records
