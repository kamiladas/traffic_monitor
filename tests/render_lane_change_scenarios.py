"""Generuje plansze do recznej weryfikacji logiki zmiany pasa."""

from pathlib import Path

import cv2
import numpy as np


def render(output: Path) -> None:
    image = np.full((500, 900, 3), 24, dtype=np.uint8)
    scenarios = [
        ("Szum granicy - pomiar pozostaje wazny", [(120, 420), (300, 300), (470, 255), (340, 220), (260, 80)], (70, 210, 120)),
        ("Potwierdzona zmiana L1 -> L2 - pomiar odrzucony", [(120, 420), (300, 330), (520, 270), (610, 200), (700, 100)], (70, 80, 230)),
    ]
    for index, (label, points, color) in enumerate(scenarios):
        x_offset = index * 450
        cv2.rectangle(image, (x_offset + 20, 40), (x_offset + 225, 470), (65, 120, 90), 2)
        cv2.rectangle(image, (x_offset + 225, 40), (x_offset + 430, 470), (100, 100, 160), 2)
        cv2.putText(image, "L1", (x_offset + 40, 75), cv2.FONT_HERSHEY_SIMPLEX, .7, (180, 220, 190), 2)
        cv2.putText(image, "L2", (x_offset + 250, 75), cv2.FONT_HERSHEY_SIMPLEX, .7, (200, 190, 230), 2)
        shifted = np.array([(x_offset + x // 2, y) for x, y in points], dtype=np.int32)
        cv2.polylines(image, [shifted], False, color, 4)
        for point in shifted:
            cv2.circle(image, tuple(point), 7, color, -1)
        cv2.putText(image, label, (x_offset + 20, 25), cv2.FONT_HERSHEY_SIMPLEX, .45, (235, 235, 235), 1)
    if not cv2.imwrite(str(output), image):
        raise RuntimeError(f"Nie mozna zapisac {output}")


if __name__ == "__main__":
    render(Path("lane_change_visual.png"))
