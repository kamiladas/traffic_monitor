import math

from traffic_monitor.analytics import EventEngine, TrackSample, vehicle_group
from traffic_monitor.geometry import crossing_fraction, point_in_polygon


CONFIG = {
    "roi": [[0, 0], [1, 0], [1, 1], [0, 1]],
    "line_a": [[0, 0.3], [1, 0.3]],
    "line_b": [[0, 0.7], [1, 0.7]],
    "lanes": [{
        "id": "L1", "polygon": [[0, 0], [1, 0], [1, 1], [0, 1]],
        "distance_m": 20, "direction": "a_to_b",
    }],
}


def test_geometry_and_measurement() -> None:
    assert point_in_polygon((0.5, 0.5), [tuple(p) for p in CONFIG["roi"]])
    assert math.isclose(crossing_fraction((0.5, 0.2), (0.5, 0.4), [(0, 0.3), (1, 0.3)]), 0.5)
    assert vehicle_group("truck") == "heavy"
    engine = EventEngine(CONFIG)
    events = []
    for track_id, offset, class_name in [(1, 0.0, "car"), (2, 2.0, "truck")]:
        for timestamp, y in [(offset, 0.2), (1 + offset, 0.4), (2 + offset, 0.6), (3 + offset, 0.8)]:
            event = engine.update(TrackSample(track_id, timestamp, (0.5, y), class_name, 0.9))
            if event:
                events.append(event)
    assert len(events) == 2
    assert round(events[0].speed_kmh, 1) == 36.0
    assert events[1].headway_s == 2.0
    assert engine.summary()["L1"]["light"] == 1
    assert engine.summary()["L1"]["heavy"] == 1

