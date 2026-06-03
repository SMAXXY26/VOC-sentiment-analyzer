import csv
import uuid
from datetime import datetime
from pathlib import Path

from ..base import BaseIngester
from ..schema import FeedbackSource, RawFeedback


class CSVIngester(BaseIngester):
    """
    Ingests feedback from a CSV file.

    Expected columns (flexible mapping via constructor):
        text_col    — column containing the feedback text (default: "text")
        rating_col  — optional star rating column (default: "rating")
        date_col    — optional submission date column (default: "submitted_at")
    """

    def __init__(
        self,
        text_col: str = "text",
        rating_col: str = "rating",
        date_col: str = "submitted_at",
    ):
        self.text_col = text_col
        self.rating_col = rating_col
        self.date_col = date_col

    def ingest(self, file_path: str | Path, **kwargs) -> list[RawFeedback]:
        records: list[RawFeedback] = []
        with open(file_path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                text = row.get(self.text_col, "").strip()
                if not text:
                    continue

                rating = None
                if self.rating_col in row and row[self.rating_col].strip():
                    try:
                        rating = float(row[self.rating_col])
                    except ValueError:
                        pass

                submitted_at = None
                if self.date_col in row and row[self.date_col].strip():
                    try:
                        submitted_at = datetime.fromisoformat(row[self.date_col])
                    except ValueError:
                        pass

                extra = {k: v for k, v in row.items() if k not in {self.text_col, self.rating_col, self.date_col}}

                records.append(
                    RawFeedback(
                        id=str(uuid.uuid4()),
                        source=FeedbackSource.csv_upload,
                        text=text,
                        rating=rating,
                        submitted_at=submitted_at,
                        metadata=extra,
                    )
                )
        return records
