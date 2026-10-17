from typing import Literal

from app.schemas.common import StrictModel


class HealthResponse(StrictModel):
    status: Literal["ok"]
