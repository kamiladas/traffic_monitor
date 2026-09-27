"""Continuous decoding with a single latest frame, source PTS and session ID."""
import math
import threading
import time
from dataclasses import dataclass

import cv2


@dataclass(frozen=True)
class FramePacket:
    frame: object
    pts: float
    received: float
    sequence: int
    session: int


class LatestCapture:
    def __init__(self, url):
        self.url = url
        self.condition = threading.Condition()
        self.stopped = threading.Event()
        self.latest = None
        self.sequence = 0
        self.session = 0
        self.connected = False
        self.error = "Laczenie ze strumieniem"
        self.thread = threading.Thread(target=self._run, daemon=True, name="rtsp-receiver")

    def start(self):
        self.thread.start()

    def stop(self):
        self.stopped.set()
        with self.condition:
            self.condition.notify_all()
        self.thread.join(timeout=4)

    def snapshot(self):
        with self.condition:
            return self.latest, self.connected, self.error

    def _run(self):
        while not self.stopped.is_set():
            cap = cv2.VideoCapture(self.url, cv2.CAP_FFMPEG, [
                cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 3000,
                cv2.CAP_PROP_READ_TIMEOUT_MSEC, 3000,
            ])
            previous = None
            previous_received = None
            with self.condition:
                self.session += 1
                self.latest = None
                self.connected = cap.isOpened()
            try:
                while cap.isOpened() and not self.stopped.is_set():
                    ok, frame = cap.read()
                    if not ok:
                        break
                    received = time.monotonic()
                    pts = float(cap.get(cv2.CAP_PROP_POS_MSEC)) / 1000.0
                    valid = math.isfinite(pts) and pts >= 0
                    continuous = (previous is not None and valid and
                                  0 < pts - previous <= 0.5 and
                                  received - previous_received <= 0.5)
                    with self.condition:
                        if not continuous:
                            self.session += 1
                            self.latest = None
                            self.error = "Oczekiwanie na ciagly PTS"
                        else:
                            self.sequence += 1
                            self.latest = FramePacket(frame, pts, received, self.sequence, self.session)
                            self.error = ""
                            self.condition.notify_all()
                    previous = pts if valid else None
                    previous_received = received
            finally:
                cap.release()
                with self.condition:
                    self.connected = False
                    self.latest = None
                    self.session += 1
                    self.error = "Brak strumienia; ponawiam polaczenie"
                self.stopped.wait(0.5)
