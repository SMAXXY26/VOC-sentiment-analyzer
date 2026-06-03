import uuid
from datetime import datetime

from ..base import BaseIngester
from ..schema import FeedbackSource, RawFeedback


class GoogleFormsIngester(BaseIngester):
    """
    Ingests Google Forms responses exported as CSV (via Google Sheets export).

    Google Forms → Link to Sheets → File > Download > CSV

    Constructor maps form question text (column headers) to roles.
    Pass a list of question strings to treat as feedback text.
    """

    def __init__(
        self,
        feedback_questions: list[str],
        rating_question: str | None = None,
        timestamp_col: str = "Timestamp",
    ):
        self.feedback_questions = feedback_questions
        self.rating_question = rating_question
        self.timestamp_col = timestamp_col

    def ingest(self, file_path: str, **kwargs) -> list[RawFeedback]:
        import csv

        records: list[RawFeedback] = []
        with open(file_path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                text_parts = [row[q].strip() for q in self.feedback_questions if q in row and row[q].strip()]
                if not text_parts:
                    continue

                rating = None
                if self.rating_question and self.rating_question in row:
                    try:
                        rating = float(row[self.rating_question])
                    except ValueError:
                        pass

                submitted_at = None
                if self.timestamp_col in row and row[self.timestamp_col].strip():
                    for fmt in ("%m/%d/%Y %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
                        try:
                            submitted_at = datetime.strptime(row[self.timestamp_col], fmt)
                            break
                        except ValueError:
                            continue

                records.append(
                    RawFeedback(
                        id=str(uuid.uuid4()),
                        source=FeedbackSource.google_forms,
                        text="\n".join(text_parts),
                        rating=rating,
                        submitted_at=submitted_at,
                        metadata={},
                    )
                )
        return records
