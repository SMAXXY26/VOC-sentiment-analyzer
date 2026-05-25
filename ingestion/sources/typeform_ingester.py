import uuid
import httpx
from datetime import datetime
from ..base import BaseIngester
from ..schema import RawFeedback, FeedbackSource


class TypeformIngester(BaseIngester):
    """
    Pulls responses from a Typeform form via the Typeform Responses API.
    Requires TYPEFORM_API_TOKEN env var or passing token directly.

    Each response's text fields are joined into one feedback body.
    """

    API_BASE = "https://api.typeform.com"

    def __init__(self, api_token: str, text_field_ids: list[str] | None = None):
        self.token = api_token
        self.text_field_ids = text_field_ids  # None = include all text-type answers

    def ingest(self, form_id: str, page_size: int = 200, **kwargs) -> list[RawFeedback]:
        records: list[RawFeedback] = []
        before = None

        while True:
            params: dict = {"page_size": page_size}
            if before:
                params["before"] = before

            resp = httpx.get(
                f"{self.API_BASE}/forms/{form_id}/responses",
                headers={"Authorization": f"Bearer {self.token}"},
                params=params,
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            items = data.get("items", [])
            if not items:
                break

            for item in items:
                text_parts = self._extract_text(item.get("answers", []))
                if not text_parts:
                    continue

                submitted_at = None
                if raw_date := item.get("submitted_at"):
                    try:
                        submitted_at = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
                    except ValueError:
                        pass

                records.append(RawFeedback(
                    id=item.get("response_id", str(uuid.uuid4())),
                    source=FeedbackSource.typeform,
                    text="\n".join(text_parts),
                    submitted_at=submitted_at,
                    metadata={"form_id": form_id},
                ))

            if len(items) < page_size:
                break
            before = items[-1]["token"]

        return records

    def _extract_text(self, answers: list[dict]) -> list[str]:
        parts = []
        for ans in answers:
            field_id = ans.get("field", {}).get("id", "")
            if self.text_field_ids and field_id not in self.text_field_ids:
                continue
            ans_type = ans.get("type")
            if ans_type == "text":
                parts.append(ans["text"])
            elif ans_type == "choice":
                parts.append(ans["choice"]["label"])
            elif ans_type == "choices":
                parts.extend(c["label"] for c in ans["choices"]["labels"])
            elif ans_type == "number":
                parts.append(str(ans["number"]))
        return parts
