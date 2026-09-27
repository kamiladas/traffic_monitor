from traffic_monitor.analytics import EventEngine, TrackSample


CONFIG = {
    "line_a": [[0, 0.3], [1, 0.3]],
    "line_b": [[0, 0.7], [1, 0.7]],
    "lane_change_confirmations": 3,
    "lanes": [
        {"id": "L1", "polygon": [[0, 0], [.5, 0], [.5, 1], [0, 1]], "distance_m": 20, "direction": "a_to_b"},
        {"id": "L2", "polygon": [[.5, 0], [1, 0], [1, 1], [.5, 1]], "distance_m": 20, "direction": "a_to_b"},
    ],
}


def sample(engine: EventEngine, track_id: int, timestamp: float, x: float, y: float):
    return engine.update(TrackSample(track_id, timestamp, (x, y), "car", .9))


def test_single_boundary_jump_does_not_invalidate_measurement() -> None:
    engine = EventEngine(CONFIG)
    observations = [
        (0.0, .45, .20),
        (0.4, .45, .40),
        (0.6, .55, .45),  # pojedynczy skok bbox do L2
        (0.8, .45, .48),
        (1.2, .45, .60),
        (1.6, .45, .80),
    ]
    events = [event for args in observations if (event := sample(engine, 1, *args))]
    assert len(events) == 1
    assert engine.tracks[1].invalid_reason is None
    assert events[0].lane == "L1"


def test_confirmed_lane_change_invalidates_measurement() -> None:
    engine = EventEngine(CONFIG)
    observations = [
        (0.0, .45, .20),
        (1.0, .45, .40),
        (1.2, .55, .45),
        (1.4, .56, .48),
        (1.6, .57, .51),
    ]
    events = [event for args in observations if (event := sample(engine, 2, *args))]
    assert events == []
    assert engine.tracks[2].invalid_reason == "lane_change"
    assert engine.tracks[2].lane == "L2"


def test_confirmed_departure_from_all_lanes_is_invalid() -> None:
    engine = EventEngine(CONFIG)
    observations = [
        (0.0, .45, .20),
        (1.0, -.05, .25),
        (1.2, -.05, .30),
        (1.4, -.05, .35),
    ]
    for args in observations:
        sample(engine, 3, *args)
    assert engine.tracks[3].invalid_reason == "lane_ambiguous_or_lost"
