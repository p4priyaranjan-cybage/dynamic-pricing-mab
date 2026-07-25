"""POC mock channel publisher - just logs the publish call in-memory/console.
Swap for channel_manager_adapter.py in production without touching any
calling code (serving/api.py depends only on BasePublisher)."""
from __future__ import annotations

import datetime as dt

from publisher.base import BasePublisher


class MockChannelPublisher(BasePublisher):
    def __init__(self) -> None:
        self.published_log: list[dict] = []

    def publish(self, property_id: str, room_type: str, rate_plan: str, stay_date: dt.date, price: float) -> dict:
        record = {
            "property_id": property_id,
            "room_type": room_type,
            "rate_plan": rate_plan,
            "stay_date": str(stay_date),
            "price": price,
            "published_at": dt.datetime.utcnow().isoformat(),
            "channel_refs": ["direct_website", "gds_mock", "ota_mock"],
        }
        self.published_log.append(record)
        return {"published": True, **record}
