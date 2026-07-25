"""Production stub - swap MockChannelPublisher for this once a real channel
manager (SynXis, Duetto, etc.) integration is available. Not implemented in
the POC; kept only to document the intended integration seam."""
from __future__ import annotations

import datetime as dt

from publisher.base import BasePublisher


class ChannelManagerAdapter(BasePublisher):
    def __init__(self, api_base_url: str, api_key: str) -> None:
        self.api_base_url = api_base_url
        self.api_key = api_key

    def publish(self, property_id: str, room_type: str, rate_plan: str, stay_date: dt.date, price: float) -> dict:
        raise NotImplementedError(
            "Production channel manager integration not implemented in this POC. "
            "Implement an HTTP call to the channel manager's rate-update API here."
        )
