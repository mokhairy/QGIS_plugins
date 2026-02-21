from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
import random
from typing import List, Optional

from shapely.geometry import Point

from .config import SimulationConfig, SourcePoint


@dataclass
class SimulationEvent:
    event_time: datetime
    event_type: str
    longitude: float
    latitude: float
    source_id: Optional[str] = None
    receiver_id: Optional[str] = None
    status: Optional[str] = None
    attributes: dict = field(default_factory=dict)

    def to_feature(self) -> dict:
        return {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [self.longitude, self.latitude]},
            "properties": {
                "event_type": self.event_type,
                "event_time": self.event_time.isoformat(),
                "source_id": self.source_id,
                "receiver_id": self.receiver_id,
                "status": self.status,
                **self.attributes,
            },
        }


@dataclass
class DailySimulationResult:
    date: date
    planned_shots: int
    executed_shots: int
    planned_receivers: int
    active_receivers: int
    uptime_ratio: float
    weather_state: str
    events: List[SimulationEvent] = field(default_factory=list)

    def kpis(self) -> dict:
        return {
            "date": self.date.isoformat(),
            "executed_shots": self.executed_shots,
            "active_receivers": self.active_receivers,
            "uptime_ratio": round(self.uptime_ratio, 3),
            "weather_state": self.weather_state,
        }

    def to_daily_record(self, project_id: int) -> dict:
        return {
            "project_id": project_id,
            "production_date": self.date.isoformat(),
            "planned_shots": self.planned_shots,
            "executed_shots": self.executed_shots,
            "planned_receivers": self.planned_receivers,
            "active_receivers": self.active_receivers,
            "uptime_ratio": self.uptime_ratio,
            "weather_code": self.weather_state,
        }

    def to_feature_collection(self) -> dict:
        return {
            "type": "FeatureCollection",
            "features": [event.to_feature() for event in self.events],
        }


class SimulationEngine:
    def __init__(self, config: SimulationConfig, seed: Optional[int] = None):
        self.config = config
        self.seed = seed or random.randint(0, 1_000_000)
        self._polygon = self.config.boundary.to_polygon()

    def simulate_range(self, start_date: date, days: int) -> List[DailySimulationResult]:
        results: List[DailySimulationResult] = []
        for offset in range(days):
            day = start_date + timedelta(days=offset)
            results.append(self.simulate_day(day))
        return results

    def simulate_day(self, day: date) -> DailySimulationResult:
        rng = random.Random(self.seed + day.toordinal())
        params = self.config.parameters

        downtime_hours = 0.0
        weather_state = "clear"
        if rng.random() < params.weather_downtime_probability:
            downtime_hours = rng.uniform(0.5, params.max_weather_delay_hours)
            weather_state = "weather-delay"

        uptime_ratio = max(0.0, (params.hours_per_day - downtime_hours) / params.hours_per_day)
        uptime_ratio *= 1 - (params.ambient_noise_factor * rng.random())
        equipment_factor = 1 - (params.equipment_failure_rate * rng.random())

        crew_capacity = params.crew_count * params.shots_per_crew_hour * params.hours_per_day
        executed_shots = round(min(params.daily_shot_target, crew_capacity) * uptime_ratio * equipment_factor)
        planned_receivers = params.daily_receiver_target
        receiver_capacity = params.crew_count * params.receiver_capacity_per_crew
        active_receivers = round(min(planned_receivers, receiver_capacity) * uptime_ratio)

        events: List[SimulationEvent] = []
        if executed_shots > 0:
            events.extend(self._generate_shot_events(day, executed_shots, rng))

        return DailySimulationResult(
            date=day,
            planned_shots=params.daily_shot_target,
            executed_shots=executed_shots,
            planned_receivers=planned_receivers,
            active_receivers=active_receivers,
            uptime_ratio=uptime_ratio,
            weather_state=weather_state,
            events=events,
        )

    def _generate_shot_events(self, day: date, shot_count: int, rng: random.Random) -> List[SimulationEvent]:
        base_time = datetime.combine(day, time(hour=6))
        minutes_available = self.config.parameters.hours_per_day * 60
        interval = minutes_available / max(shot_count, 1)
        events: List[SimulationEvent] = []
        sources = self.config.sources

        for idx in range(shot_count):
            minute_offset = (idx * interval) + rng.uniform(0, interval)
            event_time = base_time + timedelta(minutes=minute_offset)
            source = sources[idx % len(sources)] if sources else None
            point = self._jitter_point(source, rng)
            status = "executed" if rng.random() > 0.02 else "repeated"
            events.append(
                SimulationEvent(
                    event_time=event_time,
                    event_type="shot",
                    longitude=point.x,
                    latitude=point.y,
                    source_id=source.source_id if source else None,
                    status=status,
                    attributes={
                        "sequence": idx + 1,
                        "crew": (idx % self.config.parameters.crew_count) + 1,
                    },
                )
            )
        return events

    def _jitter_point(self, source: Optional[SourcePoint], rng: random.Random) -> Point:
        if source:
            point = source.to_point()
            dx = rng.uniform(-0.0005, 0.0005)
            dy = rng.uniform(-0.0005, 0.0005)
            return Point(point.x + dx, point.y + dy)

        minx, miny, maxx, maxy = self._polygon.bounds
        for _ in range(10):
            candidate = Point(rng.uniform(minx, maxx), rng.uniform(miny, maxy))
            if self._polygon.contains(candidate):
                return candidate
        return Point(minx, miny)
