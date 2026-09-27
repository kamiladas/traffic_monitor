"""Tanie operacje geometryczne uzywane przez tracker i statystyki."""

from __future__ import annotations


Point = tuple[float, float]


def point_in_polygon(point: Point, polygon: list[Point]) -> bool:
    """Ray casting; wspolrzedne moga byc znormalizowane albo pikselowe."""
    x, y = point
    inside = False
    previous = polygon[-1]
    for current in polygon:
        x1, y1 = previous
        x2, y2 = current
        if (y1 > y) != (y2 > y):
            intersection = (x2 - x1) * (y - y1) / (y2 - y1) + x1
            if x < intersection:
                inside = not inside
        previous = current
    return inside


def side_of_line(point: Point, line: list[Point]) -> float:
    """Znak iloczynu wektorowego okresla strone linii."""
    (ax, ay), (bx, by) = line
    px, py = point
    return (bx - ax) * (py - ay) - (by - ay) * (px - ax)


def crossing_fraction(previous: Point, current: Point, line: list[Point]) -> float | None:
    """Przeciecie dwoch skonczonych odcinkow; bez ruchu wzdluz bramki."""
    first = side_of_line(previous, line)
    second = side_of_line(current, line)
    if first == second or first * second > 0:
        return None
    denominator = abs(first) + abs(second)
    fraction = 0.0 if denominator == 0 else abs(first) / denominator
    x = previous[0] + fraction * (current[0]-previous[0])
    y = previous[1] + fraction * (current[1]-previous[1])
    (ax, ay), (bx, by) = line
    length2 = (bx-ax)**2 + (by-ay)**2
    if length2 <= 1e-12:
        return None
    along = ((x-ax)*(bx-ax)+(y-ay)*(by-ay))/length2
    return fraction if -1e-9 <= along <= 1+1e-9 else None


def interpolated_crossing_time(
    previous_point: Point,
    current_point: Point,
    previous_time: float,
    current_time: float,
    line: list[Point],
) -> float | None:
    fraction = crossing_fraction(previous_point, current_point, line)
    if fraction is None:
        return None
    return previous_time + fraction * (current_time - previous_time)
