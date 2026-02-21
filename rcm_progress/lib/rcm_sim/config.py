from __future__ import annotations

from pathlib import Path
from typing import List, Sequence, Optional, Union

from pydantic import BaseModel, Field
from shapely.geometry import Polygon, Point


class ProjectMetadata(BaseModel):
    """High-level information about the seismic project."""

    name: str
    location: str
    timezone: str = "UTC"
    operator: Optional[str] = None
    description: Optional[str] = None


class ProjectBoundary(BaseModel):
    """Boundary polygon for the survey area."""

    name: str = "Project Area"
    coordinates: Sequence[Sequence[float]]
    crs: str = "EPSG:4326"

    def to_polygon(self) -> Polygon:
        poly = Polygon(self.coordinates)
        if not poly.is_valid:
            poly = poly.buffer(0)
        return poly


class SourcePoint(BaseModel):
    source_id: str
    name: str
    longitude: float = Field(..., ge=-180, le=180)
    latitude: float = Field(..., ge=-90, le=90)
    nominal_shots_per_day: int = 50

    def to_point(self) -> Point:
        return Point(self.longitude, self.latitude)


class ReceiverPoint(BaseModel):
    receiver_id: str
    line_id: Optional[str] = None
    longitude: float = Field(..., ge=-180, le=180)
    latitude: float = Field(..., ge=-90, le=90)
    elevation_m: Optional[float] = None

    def to_point(self) -> Point:
        return Point(self.longitude, self.latitude)


class SimulationParameters(BaseModel):
    daily_shot_target: int = 1200
    daily_receiver_target: int = 900
    crew_count: int = 3
    hours_per_day: float = 12.0
    shots_per_crew_hour: float = 40.0
    receiver_capacity_per_crew: int = 300
    weather_downtime_probability: float = Field(0.15, ge=0, le=1)
    max_weather_delay_hours: float = 4.0
    equipment_failure_rate: float = Field(0.05, ge=0, le=0.5)
    ambient_noise_factor: float = Field(0.05, ge=0, le=1)


class SimulationConfig(BaseModel):
    project: ProjectMetadata
    boundary: ProjectBoundary
    sources: List[SourcePoint]
    receivers: List[ReceiverPoint]
    parameters: SimulationParameters

    @classmethod
    def from_file(cls, path: Union[str, Path]) -> "SimulationConfig":
        path = Path(path)
        data = path.read_text()
        return cls.model_validate_json(data)

    def source_points(self) -> List[Point]:
        return [source.to_point() for source in self.sources]

    def receiver_points(self) -> List[Point]:
        return [receiver.to_point() for receiver in self.receivers]
