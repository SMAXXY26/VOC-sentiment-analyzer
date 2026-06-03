import csv
import uuid
from datetime import datetime

from ..base import BaseIngester
from ..schema import FeedbackSource, RawFeedback


class NPSIngester(BaseIngester):
    """
    Ingests NPS survey exports (CSV).

    Standard NPS CSV columns:
        score_col      — NPS score 0-10 (default: "score")
        comment_col    — open-ended comment (default: "comment")
        date_col       — submission date (default: "created_at")

    Scores 0-6 → detractors, 7-8 → passives, 9-10 → promoters.
    Score is normalised to a 1-5 rating for pipeline compatibility.
    """

    def __init__(
        self,
        score_col: str = "score",
        comment_col: str = "comment",
        date_col: str = "created_at",
    ):
        self.score_col = score_col
        self.comment_col = comment_col
        self.date_col = date_col

    def ingest(self, file_path: str, **kwargs) -> list[RawFeedback]:
        records: list[RawFeedback] = []
        with open(file_path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                comment = row.get(self.comment_col, "").strip()
                if not comment:
                    continue

                score = None
                rating = None
                if self.score_col in row and row[self.score_col].strip():
                    try:
                        score = int(row[self.score_col])
                        # normalise NPS 0-10 → 1-5
                        rating = round(1 + (score / 10) * 4, 1)
                    except ValueError:
                        pass

                submitted_at = None
                if self.date_col in row and row[self.date_col].strip():
                    try:
                        submitted_at = datetime.fromisoformat(row[self.date_col])
                    except ValueError:
                        pass

                segment = self._segment(score)
                extra = {k: v for k, v in row.items()
                         if k not in {self.score_col, self.comment_col, self.date_col}}

                records.append(RawFeedback(
                    id=str(uuid.uuid4()),
                    source=FeedbackSource.nps_survey,
                    text=comment,
                    rating=rating,
                    submitted_at=submitted_at,
                    metadata={"nps_score": score, "nps_segment": segment, **extra},
                ))
        return records

    @staticmethod
    def _segment(score: int | None) -> str:
        if score is None:
            return "unknown"
        if score <= 6:
            return "detractor"
        if score <= 8:
            return "passive"
        return "promoter"
