"""Abstract publisher interface - the boundary between "the bandit decided
a price" and "a distribution channel actually shows that price to a
shopper". A real implementation would call a channel-manager API (see
channel_manager_adapter.py for the production stub); the POC uses a mock."""
from __future__ import annotations

from abc import ABC, abstractmethod


class BasePublisher(ABC):
    @abstractmethod
    def publish(self, property_id: str, room_type: str, rate_plan: str, stay_date, price: float) -> dict:
        """Publish a price to distribution channel(s). Returns a dict with at
        least {"published": bool, "channel_refs": [...]}."""
        raise NotImplementedError
