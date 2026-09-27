"""Lekki silnik zdarzen: pasy, linie A/B, predkosc, GAP i statystyki."""

from __future__ import annotations

import csv
import math
import statistics
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .geometry import interpolated_crossing_time, point_in_polygon, side_of_line


LIGHT_CLASSES = {"car", "motorcycle"}
HEAVY_CLASSES = {"bus", "truck"}


def vehicle_group(class_name: str) -> str:
    if class_name in LIGHT_CLASSES:
        return "light"
    if class_name in HEAVY_CLASSES:
        return "heavy"
    return "unknown"


@dataclass(slots=True)
class TrackSample:
    track_id: int
    timestamp: float
    anchor: tuple[float, float]
    class_name: str
    confidence: float


@dataclass(slots=True)
class VehicleEvent:
    track_id: int
    lane: str
    class_name: str
    vehicle_group: str
    time_a: float
    time_b: float
    speed_kmh: float
    gap_s: float | None
    confidence: float
    status: str = "valid"
    headway_s: float | None = None
    observations: int = 0
    crossing_interval_s: float = 0.0
    duration_s: float = 0.0
    distance_m: float = 0.0


@dataclass
class TrackState:
    previous: TrackSample | None = None
    lane: str | None = None
    time_a: float | None = None
    time_b: float | None = None
    confidence_sum: float = 0.0
    confidence_count: int = 0
    emitted: bool = False
    invalid_reason: str | None = None
    crossing_interval_s: float = 0.0
    headway_s: float | None = None
    lane_candidate: str | None = None
    lane_candidate_count: int = 0
    lane_unstable: bool = False


@dataclass
class LaneStats:
    light: int = 0
    heavy: int = 0
    unknown: int = 0
    speeds: list[float] = field(default_factory=list)
    gaps: list[float] = field(default_factory=list)

    def add(self, event: VehicleEvent) -> None:
        setattr(self, event.vehicle_group, getattr(self, event.vehicle_group) + 1)
        self.speeds.append(event.speed_kmh)
        if event.headway_s is not None:
            self.gaps.append(event.headway_s)

    def summary(self) -> dict:
        ordered = sorted(self.speeds)
        p85_index = max(0, math.ceil(len(ordered) * 0.85) - 1) if ordered else 0
        return {
            "count": self.light + self.heavy + self.unknown,
            "light": self.light,
            "heavy": self.heavy,
            "unknown": self.unknown,
            "speed_avg_kmh": round(statistics.fmean(ordered), 2) if ordered else None,
            "speed_median_kmh": round(statistics.median(ordered), 2) if ordered else None,
            "speed_p85_kmh": round(ordered[p85_index], 2) if ordered else None,
            "headway_avg_s": round(statistics.fmean(self.gaps), 3) if self.gaps else None,
            "headway_min_s": round(min(self.gaps), 3) if self.gaps else None,
            "gap_avg_s": None,
            "gap_min_s": None,
        }


class EventEngine:
    """Przyjmuje wyniki trackera; nie dekoduje ani nie kopiuje obrazu."""

    def __init__(self, config: dict, max_track_gap_s: float = 2.0, max_crossing_gap_s: float | None = None) -> None:
        self.config = config
        self.max_track_gap_s = max_track_gap_s
        self.max_crossing_gap_s = max_track_gap_s if max_crossing_gap_s is None else max_crossing_gap_s
        self.tracks: dict[int, TrackState] = {}
        self.last_entry_time: dict[str, float] = {}
        self.stats: dict[str, LaneStats] = defaultdict(LaneStats)

    def lane_for(self, anchor: tuple[float, float]) -> dict | None:
        matches = []
        for lane in self.config.get("lanes", []):
            polygon = [tuple(point) for point in lane["polygon"]]
            if point_in_polygon(anchor, polygon):
                matches.append(lane)
        return matches[0] if len(matches) == 1 else None

    def update(self, sample: TrackSample) -> VehicleEvent | None:
        state = self.tracks.setdefault(sample.track_id, TrackState())
        if not all(math.isfinite(v) for v in (sample.timestamp, *sample.anchor, sample.confidence)):
            state.invalid_reason = 'invalid_sample'
            return None
        if state.previous and not 0 < sample.timestamp - state.previous.timestamp <= self.max_track_gap_s:
            state.invalid_reason = 'time_discontinuity'
            self.last_entry_time.clear()

        lane = self.lane_for(sample.anchor)
        if state.lane is None and lane is not None:
            state.lane = lane["id"]
        elif state.lane is not None and (lane is None or state.lane != lane["id"]):
            # Granice pasow i bbox potrafia drgac pomiedzy kolejnymi klatkami.
            # Dopiero kilka zgodnych obserwacji potwierdza rzeczywista zmiane.
            candidate = lane["id"] if lane is not None else "__outside__"
            if state.lane_candidate == candidate:
                state.lane_candidate_count += 1
            else:
                state.lane_candidate = candidate
                state.lane_candidate_count = 1
            state.lane_unstable = True
            confirmations = max(2, int(self.config.get("lane_change_confirmations", 3)))
            if state.lane_candidate_count >= confirmations:
                state.time_a = None
                state.time_b = None
                if lane is None:
                    state.invalid_reason = "lane_ambiguous_or_lost"
                else:
                    state.lane = lane["id"]
                    state.invalid_reason = "lane_change"
            state.previous = sample
            return None
        elif state.lane_unstable:
            # Powrot do pierwotnego pasa oznacza pojedynczy szum detekcji.
            # Nie interpoluj przeciecia linii przez niestabilny fragment.
            state.lane_candidate = None
            state.lane_candidate_count = 0
            state.lane_unstable = False
            state.previous = sample
            return None

        state.lane_candidate = None
        state.lane_candidate_count = 0
        state.lane_unstable = False
        if state.invalid_reason or state.emitted:
            state.previous = sample
            return None

        # Keep an A/B measurement alive through a configured occlusion, but do
        # not invent a line crossing by interpolating across a long blind gap.
        if state.previous and sample.timestamp - state.previous.timestamp > self.max_crossing_gap_s:
            state.previous = sample
            return None

        state.confidence_sum += sample.confidence
        state.confidence_count += 1
        if state.previous is None or state.lane is None or lane is None:
            state.previous = sample
            return None

        line_a = [tuple(point) for point in self.config.get("line_a", [])]
        line_b = [tuple(point) for point in self.config.get("line_b", [])]
        if len(line_a) != 2 or len(line_b) != 2:
            state.previous = sample
            return None

        crossing_a = interpolated_crossing_time(
            state.previous.anchor,
            sample.anchor,
            state.previous.timestamp,
            sample.timestamp,
            line_a,
        )
        crossing_b = interpolated_crossing_time(
            state.previous.anchor,
            sample.anchor,
            state.previous.timestamp,
            sample.timestamp,
            line_b,
        )
        direction = lane["direction"]
        entry_line, exit_line = (line_a, line_b) if direction == 'a_to_b' else (line_b, line_a)
        entry_cross, exit_cross = (crossing_a, crossing_b) if direction == 'a_to_b' else (crossing_b, crossing_a)
        entry_before = state.time_a if direction == 'a_to_b' else state.time_b
        exit_mid = tuple((exit_line[0][i]+exit_line[1][i])/2 for i in range(2))
        entry_mid = tuple((entry_line[0][i]+entry_line[1][i])/2 for i in range(2))
        wrong = (entry_cross is not None and side_of_line(sample.anchor, entry_line)*side_of_line(exit_mid, entry_line) <= 0)
        wrong |= (exit_cross is not None and side_of_line(sample.anchor, exit_line)*side_of_line(entry_mid, exit_line) >= 0)
        if wrong or (entry_cross is not None and exit_cross is not None) or (exit_cross is not None and entry_before is None):
            state.invalid_reason = 'wrong_order_direction_or_jump'
            state.previous = sample
            return None
        if entry_cross is not None:
            if entry_before is not None:
                state.invalid_reason = 'repeated_entry'
                state.previous = sample
                return None
            previous_entry = self.last_entry_time.get(state.lane)
            state.headway_s = entry_cross-previous_entry if previous_entry is not None and entry_cross>previous_entry else None
            self.last_entry_time[state.lane] = max(entry_cross, previous_entry or entry_cross)
        if entry_cross is not None or exit_cross is not None:
            state.crossing_interval_s = max(state.crossing_interval_s, sample.timestamp-state.previous.timestamp)
        if crossing_a is not None and state.time_a is None:
            state.time_a = crossing_a
        if crossing_b is not None and state.time_b is None:
            state.time_b = crossing_b

        entry_time = state.time_a if direction == "a_to_b" else state.time_b
        exit_time = state.time_b if direction == "a_to_b" else state.time_a
        if state.emitted or entry_time is None or exit_time is None or exit_time <= entry_time:
            state.previous = sample
            return None

        duration = exit_time - entry_time
        speed = 3.6 * float(lane["distance_m"]) / duration
        if state.confidence_count < 4 or duration + 1e-9 < 2*state.crossing_interval_s or not math.isfinite(speed) or not 0 < speed <= float(self.config.get('max_speed_kmh', 250)):
            state.invalid_reason = 'insufficient_observations_or_implausible_speed'
            state.previous = sample
            return None
        event = VehicleEvent(
            track_id=sample.track_id,
            lane=state.lane,
            class_name=sample.class_name,
            vehicle_group=vehicle_group(sample.class_name),
            time_a=float(state.time_a),
            time_b=float(state.time_b),
            speed_kmh=float(speed),
            gap_s=None,
            confidence=float(state.confidence_sum / state.confidence_count),
            headway_s=state.headway_s,
            observations=state.confidence_count,
            crossing_interval_s=state.crossing_interval_s,
            duration_s=duration,
            distance_m=float(lane['distance_m']),
        )
        state.emitted = True
        self.stats[state.lane].add(event)
        state.previous = sample
        return event

    def prune(self, current_time: float) -> None:
        stale = [
            track_id
            for track_id, state in self.tracks.items()
            if state.previous and current_time - state.previous.timestamp > self.max_track_gap_s * 3
        ]
        for track_id in stale:
            del self.tracks[track_id]

    def reset_session(self) -> None:
        """Zerwij pomiary i GAP po utracie/ponownym polaczeniu strumienia."""
        self.tracks.clear()
        self.last_entry_time.clear()

    def summary(self) -> dict[str, dict]:
        return {lane: stats.summary() for lane, stats in self.stats.items()}


class CsvEventSink:
    FIELDS = [
        "track_id",
        "lane",
        "class_name",
        "vehicle_group",
        "time_a",
        "time_b",
        "speed_kmh",
        "gap_s",
        "confidence",
        "status",
    ]

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def write(self, event: VehicleEvent) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        new_file = not self.path.exists()
        with self.path.open("a", newline="", encoding="utf-8") as output:
            writer = csv.DictWriter(output, fieldnames=self.FIELDS, extrasaction='ignore')
            if new_file:
                writer.writeheader()
            row = asdict(event)
            row["time_a"] = round(event.time_a, 6)
            row["time_b"] = round(event.time_b, 6)
            row["speed_kmh"] = round(event.speed_kmh, 2)
            row["gap_s"] = round(event.gap_s, 3) if event.gap_s is not None else ""
            row["confidence"] = round(event.confidence, 4)
            writer.writerow(row)
