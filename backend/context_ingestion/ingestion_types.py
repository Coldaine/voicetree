"""Context ingestion types for always-on ingestion pipeline (Issue #7)."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class IngestionEvent:
    """Normalized ingestion event with source attribution."""
    content: str
    source_type: str  # e.g., 'screenpipe', 'browser', 'editor'
    source_ref: str   # e.g., app name, URL, file path
    timestamp: datetime
    confidence: float = 1.0
    active_context_score: Optional[float] = None


class IngestionAdapter(ABC):
    """Abstract base class for external context providers."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique name of this adapter."""
        ...

    @abstractmethod
    def poll(self) -> list[IngestionEvent]:
        """Poll for new context events.

        Returns:
            List of normalized ingestion events.
        """
        ...
