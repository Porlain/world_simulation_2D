from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, field_validator, model_validator

Identifier = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_-]{1,63}$")]
Sha256Hex = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Coordinate = tuple[FiniteFloat, FiniteFloat]
Bounds = tuple[FiniteFloat, FiniteFloat, FiniteFloat, FiniteFloat]
Polygon = Annotated[list[Coordinate], Field(min_length=3)]
NonNegativeInt = Annotated[int, Field(ge=0)]
PositiveTick = Annotated[int, Field(ge=1, le=3600)]
CountMap = dict[str, NonNegativeInt]


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


class TownGenerationRequest(StrictModel):
    generation_seed: int | None = Field(default=None, ge=0, le=2**53 - 1)
    population: int = Field(ge=100, le=100_000)
    name: str | None = Field(default=None, min_length=1, max_length=64)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("name must contain visible characters")
        return normalized


class TownDistrict(StrictModel):
    id: Identifier
    kind: Literal[
        "residential",
        "market",
        "industrial",
        "storage",
        "religious",
        "civic",
        "military",
        "stable",
    ]
    polygon: Polygon


class TownBuilding(StrictModel):
    id: Identifier
    district_id: Identifier
    kind: Literal[
        "residential",
        "market",
        "workshop",
        "storage",
        "religious",
        "administrative",
        "military",
        "stable",
    ]
    polygon: Polygon
    anchor: Coordinate


class TownJunction(StrictModel):
    id: Identifier
    position: Coordinate
    kind: Literal["normal", "gate", "plaza"]


class TownStreet(StrictModel):
    id: Identifier
    from_junction_id: Identifier
    to_junction_id: Identifier
    path: list[Coordinate] = Field(min_length=2)
    width: FiniteFloat = Field(gt=0)
    kind: Literal["primary", "ring", "secondary"]


class TownLandmark(StrictModel):
    id: Identifier
    building_id: Identifier | None = None
    kind: Literal[
        "gate",
        "plaza",
        "market",
        "workshop",
        "storage",
        "religious",
        "administrative",
        "military",
        "stable",
    ]
    name: str = Field(min_length=1, max_length=64)
    position: Coordinate


class TownSkeleton(StrictModel):
    schema_version: Literal[2] = 2
    scenario_id: Identifier
    name: str = Field(min_length=1, max_length=64)
    generation_seed: int = Field(ge=0, le=2**53 - 1)
    generator_version: Literal["radial-v1"] = "radial-v1"
    requested_population: int = Field(ge=100, le=100_000)
    initial_vehicle_count: int = Field(ge=5, le=1000)
    coordinate_system: Literal["local_xy"] = "local_xy"
    coordinate_unit: Literal["meter"] = "meter"
    axis_orientation: Literal["x_right_y_up"] = "x_right_y_up"
    bounds: Bounds
    boundary: Polygon
    districts: list[TownDistrict] = Field(min_length=1)
    buildings: list[TownBuilding] = Field(min_length=1)
    junctions: list[TownJunction] = Field(min_length=1)
    streets: list[TownStreet] = Field(min_length=1)
    landmarks: list[TownLandmark] = Field(min_length=1)


class FlowLocation(StrictModel):
    id: Identifier
    name: str = Field(min_length=1, max_length=64)
    kind: Literal["gate", "plaza", "landmark", "district"]
    position: Coordinate
    initial_counts: CountMap


class FlowConnection(StrictModel):
    id: Identifier
    from_location_id: Identifier
    to_location_id: Identifier
    street_segment_ids: list[Identifier] = Field(min_length=1)
    path: list[Coordinate] = Field(min_length=2)
    travel_time_ticks: dict[str, PositiveTick]
    capacity_per_tick: CountMap
    demand_per_tick: dict[str, DemandRange]


class FlowBindings(StrictModel):
    location_feature_ids: dict[str, list[Identifier]]
    connection_street_ids: dict[str, list[Identifier]]


class SimulationPackage(StrictModel):
    schema_version: Literal[2] = 2
    tick_seconds: Literal[1] = 1
    flow_types: list[FlowTypeConfig] = Field(min_length=1)
    locations: list[FlowLocation] = Field(min_length=2)
    connections: list[FlowConnection] = Field(min_length=1)
    bindings: FlowBindings


class RunCreateRequest(StrictModel):
    scenario_id: Identifier | None = None
    draft_id: Identifier | None = None
    simulation_seed: int | None = Field(default=None, ge=0, le=2**53 - 1)
    seed: int | None = Field(default=None, ge=0, le=2**53 - 1)

    @model_validator(mode="after")
    def validate_target_and_seed(self) -> "RunCreateRequest":
        if (self.scenario_id is None) == (self.draft_id is None):
            raise ValueError("provide exactly one of scenario_id or draft_id")
        if self.seed is not None and self.simulation_seed is not None:
            raise ValueError("provide only one simulation seed")
        return self

    @property
    def resolved_seed(self) -> int | None:
        return self.simulation_seed if self.simulation_seed is not None else self.seed


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


class ConnectionSnapshot(StrictModel):
    departed: NonNegativeInt
    arrived: NonNegativeInt
    in_transit: NonNegativeInt


class FlowSnapshot(StrictModel):
    schema_version: Literal[2] = 2
    tick: int = Field(ge=0)
    location_counts: dict[str, CountMap]
    connections: dict[str, dict[str, ConnectionSnapshot]]
    totals: CountMap
