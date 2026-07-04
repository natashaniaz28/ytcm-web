from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class NAMIExplorerState:
    data: list[dict[str, Any]] = field(default_factory=list)
    filtered: list[dict[str, Any]] | None = None
    source: str | None = None
    last_filter: str | None = None
    last_query: dict[str, Any] | None = None

    def active(self) -> list[dict[str, Any]]:
        """
        Return the filtered records if a filter is set, otherwise all records.
        """
        return self.filtered if self.filtered is not None else self.data

    def reset_filter(self) -> None:
        """
        Clear any active filter.
        """
        self.filtered = None
        self.last_filter = None
        self.last_query = None

    @property
    def total_count(self) -> int:
        """
        Return how many records are loaded in total.
        """
        return len(self.data)

    @property
    def active_count(self) -> int:
        """
        Return how many records are currently in view.
        """
        return len(self.active())

