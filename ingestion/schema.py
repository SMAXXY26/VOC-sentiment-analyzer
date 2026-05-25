from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from enum import Enum


class FeedbackSource(str, Enum):
    google_review = "google_review"
    app_store = "app_store"
    play_store = "play_store"
    trustpilot = "trustpilot"
    typeform = "typeform"
    google_forms = "google_forms"
    csv_upload = "csv_upload"
    api = "api"
    nps_survey = "nps_survey"
    csat_survey = "csat_survey"


class RawFeedback(BaseModel):
    id: str
    source: FeedbackSource
    text: str
    rating: Optional[float] = Field(None, ge=1, le=5)
    submitted_at: Optional[datetime] = None
    metadata: dict = Field(default_factory=dict)
