from typing import Literal

from pydantic import BaseModel

ServiceState = Literal["healthy", "unreachable"]


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    db: ServiceState
    redis: ServiceState
