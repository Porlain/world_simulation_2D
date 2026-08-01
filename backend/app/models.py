from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, model_validator

Identifier = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_-]{1,63}$")]
Sha256Hex = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Coordinate = tuple[FiniteFloat, FiniteFloat]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DemandRange(StrictModel):
    min: int = Field(ge=0)
    max: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_order(self) -> "DemandRange":
        if self.max < self.min:
            raise ValueError("max must be greater than or equal to min")
        return self


class FlowTypeConfig(StrictModel):
    id: Identifier
    unit: str = Field(min_length=1, max_length=32)
    label: str = Field(min_length=1, max_length=32)


class LocationConfig(StrictModel):
    id: Identifier
    name: str = Field(min_length=1, max_length=64)
    position: Coordinate
    initial_counts: dict[str, int]


class ConnectionConfig(StrictModel):
    id: Identifier
    from_location_id: Identifier
    to_location_id: Identifier
    path: list[Coordinate] = Field(min_length=2)
    travel_time_ticks: int = Field(ge=1, le=3600)
    capacity_per_tick: dict[str, int]
    demand_per_tick: dict[str, DemandRange]


class ScenarioConfig(StrictModel):
    schema_version: Literal[1]
    scenario_id: Identifier
    name: str = Field(min_length=1, max_length=64)
    scale: Literal["city"]
    tick_seconds: Literal[1]
    coordinate_system: Literal["local_xy"]
    axis_orientation: Literal["x_right_y_up"]
    coordinate_unit: Literal["scene_unit"]
    flow_types: list[FlowTypeConfig] = Field(min_length=1)
    locations: list[LocationConfig] = Field(min_length=2)
    connections: list[ConnectionConfig] = Field(min_length=1)


class ScenarioBundle(StrictModel):
    config: ScenarioConfig
    checksum: Sha256Hex


class RunCreateRequest(StrictModel):
    scenario_id: Identifier
    seed: int | None = Field(default=None, ge=0, le=2**53 - 1)


class RunCommandRequest(StrictModel):
    action: Literal["pause", "resume", "end", "set_rate"]
    rate: Literal[0.5, 1.0, 2.0, 4.0] | None = None

    @model_validator(mode="after")
    def validate_rate(self) -> "RunCommandRequest":
        if self.action == "set_rate" and self.rate is None:
            raise ValueError("set_rate requires rate")
        if self.action != "set_rate" and self.rate is not None:
            raise ValueError("rate is only allowed for set_rate")
        return self


class ConnectionActivity(StrictModel):
    departed: int = Field(ge=0)
    arrived: int = Field(ge=0)


class SnapshotState(StrictModel):
    schema_version: Literal[1] = 1
    tick: int = Field(ge=0)
    location_counts: dict[str, dict[str, int]]
    transit_buckets: dict[str, dict[str, list[int]]]
    connection_activity: dict[str, dict[str, ConnectionActivity]]
    totals: dict[str, int]
