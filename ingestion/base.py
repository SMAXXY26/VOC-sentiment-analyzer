from abc import ABC, abstractmethod
from .schema import RawFeedback


class BaseIngester(ABC):
    """All ingesters return a flat list of RawFeedback records."""

    @abstractmethod
    def ingest(self, **kwargs) -> list[RawFeedback]:
        ...
