"""Analiza live w pamieci: detekcja, tracking, A/B, predkosc i GAP."""

from __future__ import annotations

import json
import os
import re
import threading
import time
from copy import copy
from collections import deque
from dataclasses import asdict
from pathlib import Path

os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp")

import cv2

from .analytics import EventEngine, TrackSample, vehicle_group
from .detector import Yolo26Tracker, Track
from .capture import LatestCapture


class LiveAnalyzer:
    def __init__(self, stream_url: str, config_path: Path, model_path: Path, analysis_fps: float = 6.0, preview_fps: float = 12.0) -> None:
        self.stream_url = stream_url
        self.config_path = config_path
        self.analysis_interval = 1.0 / analysis_fps
        self.preview_interval = 1.0 / (3.0 if Path(stream_url).is_file() else preview_fps)
        self.detector = Yolo26Tracker(model_path, confidence=0.20)
        self.model_path = model_path
        self.engine: EventEngine | None = None
        self.config: dict = {}
        self.config_mtime = -1.0
        self.events: deque[dict] = deque(maxlen=100)
        self.track_results: dict[int, dict] = {}
        self.confirmed_track_ids: set[int] = set()
        self.rejected_tracks: dict[int, str] = {}
        self.rejected_events: dict[int, dict] = {}
        self.track_snapshots: dict[int, dict] = {}
        self.snapshot_updated: dict[int, float] = {}
        self.snapshot_finalized: set[int] = set()
        source_name = Path(stream_url).stem if Path(stream_url).is_file() else "live"
        source_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", source_name)[:80] or "source"
        self.evidence_directory = config_path.parents[1] / "evidence" / f"{time.strftime('%Y%m%d_%H%M%S')}_{source_name}"
        self.evidence_files: dict[int, str] = {}
        self.lock = threading.RLock()
        self.condition = threading.Condition(self.lock)
        self.latest_jpeg: bytes | None = None
        self.frame_number = 0
        self.preview_clients = 0
        self.preview_pending: tuple | None = None
        self.preview_generation = 0
        self.last_preview_submit = 0.0
        self.running = False
        self.connected = False
        self.error = ""
        self.inference_ms: float | None = None
        self.detected = 0
        self.active_tracks = 0
        self.display_tracks: list[Track] = []
        self.timing_source = "waiting_for_pts"
        self.thread: threading.Thread | None = None
        self.preview_thread: threading.Thread | None = None
        self.receiver = LatestCapture(stream_url)
        self.file_mode = Path(stream_url).is_file()
        self.paused = False
        self.file_state = 'ready' if self.file_mode else None
        self.file_position_s = 0.0
        self.file_duration_s = None
        self.file_frames_processed = 0
        self.file_frames_total = None
        self.file_fps_nominal = None
        self.file_started_at = None
        self.analysis_times = deque(maxlen=60)
        self.frame_age_ms = None
        self.result_age_ms = None
        self.pts_interval_ms = None
        self.skipped_frames = 0
        self.continuity_resets = 0

    def start(self) -> None:
        self.running = True
        if not self.file_mode:
            self.receiver.start()
        self.preview_thread = threading.Thread(target=self._preview_worker, name="traffic-preview", daemon=True)
        self.preview_thread.start()
        self.thread = threading.Thread(target=self._run, name="traffic-analyzer", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.running = False
        if not self.file_mode:
            self.receiver.stop()
        with self.condition:
            self.condition.notify_all()
        if self.thread:
            self.thread.join(timeout=3)
        if self.preview_thread:
            self.preview_thread.join(timeout=2)

    def status(self) -> dict:
        with self.lock:
            actual_fps = round((len(self.analysis_times)-1) / (self.analysis_times[-1]-self.analysis_times[0]), 1) if len(self.analysis_times)>1 and time.monotonic()-self.analysis_times[-1]<1 else 0
            measuring = 0
            crossed_a = 0
            crossed_b = 0
            if self.engine:
                measuring = sum(not state.emitted for state in self.engine.tracks.values())
                crossed_a = sum(state.time_a is not None for state in self.engine.tracks.values())
                crossed_b = sum(state.time_b is not None for state in self.engine.tracks.values())
            return {
                "running": self.running,
                "source_kind": 'file' if self.file_mode else 'camera',
                "file_name": Path(self.stream_url).name if self.file_mode else None,
                "file_state": self.file_state,
                "paused": self.paused,
                "position_s": round(self.file_position_s, 2),
                "duration_s": self.file_duration_s,
                "frames_processed": self.file_frames_processed,
                "frames_total": self.file_frames_total,
                "file_fps_nominal": self.file_fps_nominal,
                "file_speed_factor": round(actual_fps/self.file_fps_nominal, 2) if actual_fps and self.file_fps_nominal else None,
                "remaining_wall_s": round((self.file_frames_total-self.file_frames_processed)/actual_fps) if actual_fps and self.file_frames_total and self.file_state == 'analyzing' else None,
                "connected": self.connected,
                "error": self.error,
                "inference_ms": round(self.inference_ms, 1) if self.inference_ms is not None else None,
                "detections": self.detected,
                "active_tracks": self.active_tracks,
                "confirmed_tracks": len(self.confirmed_track_ids),
                "analysis_fps_target": round(1 / self.analysis_interval, 1),
                "detection_confidence": self.detector.confidence,
                "track_high_thresh": self.detector.track_high_thresh,
                "track_low_thresh": self.detector.track_low_thresh,
                "new_track_thresh": self.detector.new_track_thresh,
                "tracking_grace_s": self.engine.max_track_gap_s if self.engine else float(self.config.get('tracking_grace_s', .5)),
                "inference_backend": getattr(self.detector, 'backend_active', 'ultralytics_cpu'),
                "inference_backend_requested": getattr(self.detector, 'backend_requested', 'ultralytics_auto'),
                "inference_backend_error": getattr(self.detector, 'backend_error', ''),
                "lane_distances_m": {lane['id']: lane['distance_m'] for lane in self.config.get('lanes', [])},
                "preview_fps_target": round(1 / self.preview_interval, 1),
                "preview_clients": self.preview_clients,
                "profile_ready": bool(self.config.get("lanes") and self.config.get("line_a") and self.config.get("line_b")),
                "timing_source": self.timing_source,
                "measurement_tracks": measuring,
                "crossed_a": crossed_a,
                "crossed_b": crossed_b,
                "rejected_measurements": {
                    **{str(key): reason for key, reason in self.rejected_tracks.items()},
                    **({str(key): state.invalid_reason for key, state in self.engine.tracks.items() if state.invalid_reason} if self.engine else {}),
                },
                "frame_age_ms": self.frame_age_ms,
                "result_age_ms": self.result_age_ms,
                "pts_interval_ms": self.pts_interval_ms,
                "skipped_frames": self.skipped_frames,
                "continuity_resets": self.continuity_resets,
                "analysis_fps_actual": actual_fps,
            }

    def stats(self) -> dict:
        with self.lock:
            lanes = self.engine.summary() if self.engine else {}
            total = sum(item["count"] for item in lanes.values())
            return {
                "lanes": lanes,
                "total": total,
                "detected_total": len(self.confirmed_track_ids),
                "unmeasured_total": max(0, len(self.confirmed_track_ids) - total),
            }

    def recent_events(self) -> list[dict]:
        with self.lock:
            return list(self.events)

    def measurement_rows(self) -> list[dict]:
        """Rows for the UI/CSV: valid, rejected and currently measured tracks."""
        with self.lock:
            rows = [dict(item) for item in self.events]
            rows.extend(dict(item) for item in self.rejected_events.values())
            if self.engine:
                known = {int(item["track_id"]) for item in rows}
                for track_id, state in self.engine.tracks.items():
                    if track_id in known or track_id not in self.confirmed_track_ids or state.emitted:
                        continue
                    previous = state.previous
                    rows.append({
                        "track_id": track_id,
                        "lane": state.lane,
                        "class_name": previous.class_name if previous else "unknown",
                        "vehicle_group": vehicle_group(previous.class_name) if previous else "unknown",
                        "time_a": state.time_a,
                        "time_b": state.time_b,
                        "duration_s": None,
                        "distance_m": next((float(l["distance_m"]) for l in self.config.get("lanes", []) if l["id"] == state.lane), None),
                        "speed_kmh": None,
                        "gap_s": None,
                        "confidence": (state.confidence_sum / state.confidence_count) if state.confidence_count else None,
                        "status": "invalid" if state.invalid_reason else "measuring",
                        "reason": state.invalid_reason or "",
                        "event_time_s": state.time_a if state.time_a is not None else (state.time_b if state.time_b is not None else (previous.timestamp if previous else None)),
                    })
            for item in rows:
                item["has_snapshot"] = int(item["track_id"]) in self.track_snapshots
                item["evidence_file"] = self.evidence_files.get(int(item["track_id"]))
            return sorted(rows, key=lambda item: item.get("event_time_s") or item.get("time_b") or item.get("time_a") or -1, reverse=True)

    def measurement_snapshot(self, track_id: int, thumbnail: bool = False) -> tuple[bytes, float] | None:
        with self.lock:
            item = self.track_snapshots.get(track_id)
            if not item:
                return None
            return item["thumbnail" if thumbnail else "full"], float(item["timestamp"])

    def wait_jpeg(self, after: int, timeout: float = 2.0) -> tuple[int, bytes | None]:
        with self.condition:
            self.condition.wait_for(lambda: self.frame_number > after or not self.running, timeout)
            return self.frame_number, self.latest_jpeg

    def add_preview_client(self) -> None:
        with self.condition:
            self.preview_clients += 1

    def remove_preview_client(self) -> None:
        with self.condition:
            self.preview_clients = max(0, self.preview_clients - 1)
            if self.preview_clients == 0:
                # Nie trzymaj niepotrzebnie obrazu podgladu w pamieci.
                self.latest_jpeg = None
                self.preview_pending = None

    def _load_config(self) -> None:
        if not self.config_path.exists():
            return
        mtime = self.config_path.stat().st_mtime
        if mtime == self.config_mtime:
            return
        config = json.loads(self.config_path.read_text(encoding="utf-8"))
        with self.lock:
            geometry_changed = any(config.get(key) != self.config.get(key) for key in ('lanes', 'line_a', 'line_b', 'roi', 'max_speed_kmh', 'tracking_grace_s'))
            backend_changed = self.detector.configure_backend(config.get('inference_backend', 'ultralytics_auto'))
            self.config = config
            self.analysis_interval = 1.0 / float(config.get('analysis_fps', 6))
            self.preview_interval = 1.0 / float(config.get('preview_fps', 3 if self.file_mode else 12))
            self.detector.confidence = float(config.get('detection_confidence', .20))
            self.detector.configure_thresholds(
                config.get('track_high_thresh', .25),
                config.get('track_low_thresh', .10),
                config.get('new_track_thresh', .25),
            )
            if geometry_changed or backend_changed or self.engine is None:
                grace = float(config.get('tracking_grace_s', .5))
                self.engine = EventEngine(config, max_track_gap_s=grace, max_crossing_gap_s=min(.5, grace))
                self.events.clear()
                self.track_results.clear()
                self.confirmed_track_ids.clear()
                self.rejected_tracks.clear()
                self.rejected_events.clear()
                self.track_snapshots.clear()
                self.snapshot_updated.clear()
                self.snapshot_finalized.clear()
                self.evidence_files.clear()
                self.detector.reset()
        self.config_mtime = mtime

    def _disconnect(self, message: str) -> None:
        self.detector.reset()
        with self.lock:
            if self.engine:
                self.engine.reset_session()
            self.track_results.clear()
            self.confirmed_track_ids.clear()
            self.rejected_tracks.clear()
            self.rejected_events.clear()
            self.track_snapshots.clear()
            self.snapshot_updated.clear()
            self.snapshot_finalized.clear()
            self.evidence_files.clear()
            self.connected = False
            self.error = message

    def _run(self) -> None:
        cv2.setNumThreads(2)
        if self.file_mode:
            self._run_file()
            return
        sequence = 0
        session = None
        last_pts = None
        next_analysis = 0.0
        while self.running:
            packet, connected, error = self.receiver.snapshot()
            now = time.monotonic()
            if packet is None or now - packet.received > 0.5:
                if session is not None:
                    self._disconnect(error or "Przerwa w odbiorze")
                    self.continuity_resets += 1
                    session = None
                    last_pts = None
                with self.lock:
                    self.connected = connected
                    self.error = error or "Przerwa w odbiorze"
                    self.timing_source = "waiting_for_pts"
                time.sleep(0.02)
                continue
            if packet.sequence == sequence or now < next_analysis:
                time.sleep(0.005)
                continue
            if packet.session != session or (last_pts is not None and not 0 < packet.pts-last_pts <= 0.5):
                self._disconnect("")
                self.continuity_resets += 1
                last_pts = None
                session = packet.session
            with self.lock:
                self.connected = connected
                self.timing_source = "stream_pts"
                self.frame_age_ms = round((now-packet.received)*1000, 1)
                self.pts_interval_ms = round((packet.pts-last_pts)*1000, 1) if last_pts is not None else None
                self.skipped_frames += max(0, packet.sequence-sequence-1) if sequence else 0
            sequence = packet.sequence
            last_pts = packet.pts
            next_analysis = now + self.analysis_interval
            try:
                self._load_config()
                self._process(packet.frame, packet.pts)
                with self.lock:
                    self.analysis_times.append(time.monotonic())
                    self.result_age_ms = round((time.monotonic()-packet.received)*1000, 1)
            except Exception as exc:
                self._disconnect(f"Analiza: {exc}")
                session = None

    def _run_file(self) -> None:
        capture = cv2.VideoCapture(self.stream_url, cv2.CAP_FFMPEG)
        try:
            if not capture.isOpened():
                raise ValueError('Nie można otworzyć MP4.')
            fps = capture.get(cv2.CAP_PROP_FPS)
            self.file_fps_nominal = fps if fps > 0 else None
            self.file_frames_total = int(capture.get(cv2.CAP_PROP_FRAME_COUNT)) or None
            self.file_duration_s = self.file_frames_total/fps if fps>0 and self.file_frames_total else None
            self.file_started_at = time.monotonic()
            self.connected = True
            self.file_state = 'analyzing'
            previous = None
            while self.running:
                if self.paused:
                    time.sleep(.05)
                    continue
                ok, frame = capture.read()
                if not ok:
                    self.file_state = 'finished'
                    break
                pts = float(capture.get(cv2.CAP_PROP_POS_MSEC))/1000
                if not __import__('math').isfinite(pts) or pts<0 or (previous is not None and pts<=previous):
                    raise ValueError('Nieprawidłowe lub niemonotoniczne znaczniki czasu MP4.')
                if previous is not None and pts-previous>.5:
                    self._disconnect('')
                    self.continuity_resets += 1
                previous = pts
                self.file_position_s = pts
                self._load_config()
                self.timing_source = 'file_pts'
                self.connected = True
                self._process(frame, pts)
                with self.lock:
                    self.file_frames_processed += 1
                    self.analysis_times.append(time.monotonic())
            if self.file_state != 'finished': self.file_state = 'stopped'
        except Exception as exc:
            self.error = str(exc)
            self.file_state = 'error'
        finally:
            capture.release()
            self.connected = False
            # Keep worker alive at EOF to serve last preview and final results.
            while self.running:
                time.sleep(.1)

    def _process(self, frame, timestamp: float) -> None:
        config = self.config
        started = time.perf_counter()
        tracks = self.detector.process(
            frame,
            float(timestamp),
            config.get("lanes", []),
            config.get("line_a", []),
            config.get("line_b", []),
            config.get("roi", []),
        )
        inference_ms = (time.perf_counter() - started) * 1000
        current = tracks
        self.display_tracks = current
        active_ids = {track.track_id for track in tracks}
        with self.lock:
            self.confirmed_track_ids.update(
                track.track_id for track in current
                if track.hits >= 4 and track.last_seen - track.first_seen >= 0.7
            )
            self.track_results = {
                track_id: result
                for track_id, result in self.track_results.items()
                if track_id in active_ids
            }
        height, width = frame.shape[:2]
        engine = self.engine
        finalize_snapshots: set[int] = set()
        if engine:
            with self.lock:
                for track in current:
                    event = engine.update(TrackSample(
                        track.track_id,
                        float(timestamp),
                        (float(track.anchor[0] / width), float(track.anchor[1] / height)),
                        track.class_name,
                        float(track.confidence),
                    ))
                    if event:
                        item = asdict(event)
                        item["speed_kmh"] = round(float(event.speed_kmh), 1)
                        item["gap_s"] = round(float(event.gap_s), 2) if event.gap_s is not None else None
                        item["detected_at"] = time.strftime("%H:%M:%S")
                        item["event_time_s"] = float(event.time_b)
                        item["reason"] = ""
                        self.events.appendleft(item)
                        self.track_results[event.track_id] = item
                        finalize_snapshots.add(event.track_id)
                for key, state in engine.tracks.items():
                    if (key not in active_ids and not state.emitted and state.previous
                            and float(timestamp) - state.previous.timestamp > engine.max_track_gap_s):
                        state.invalid_reason = 'tracking_lost'
                        if key in self.confirmed_track_ids:
                            self.rejected_tracks.setdefault(
                                key,
                                'tracking_lost_after_gate' if state.time_a is not None or state.time_b is not None
                                else 'occluded_before_complete_measurement',
                            )
                        if state.lane:
                            engine.last_entry_time.pop(state.lane, None)
                    if key in self.confirmed_track_ids and state.invalid_reason and not state.emitted:
                        reason = self.rejected_tracks.get(key, state.invalid_reason)
                        self.rejected_tracks.setdefault(key, reason)
                        previous = state.previous
                        self.rejected_events.setdefault(key, {
                            "track_id": key,
                            "lane": state.lane,
                            "class_name": previous.class_name if previous else "unknown",
                            "vehicle_group": vehicle_group(previous.class_name) if previous else "unknown",
                            "time_a": state.time_a,
                            "time_b": state.time_b,
                            "duration_s": None,
                            "distance_m": next((float(l["distance_m"]) for l in config.get("lanes", []) if l["id"] == state.lane), None),
                            "speed_kmh": None,
                            "gap_s": None,
                            "confidence": (state.confidence_sum / state.confidence_count) if state.confidence_count else None,
                            "status": "invalid",
                            "reason": reason,
                            "detected_at": time.strftime("%H:%M:%S"),
                            "event_time_s": state.time_a if state.time_a is not None else (state.time_b if state.time_b is not None else (previous.timestamp if previous else None)),
                        })
                        finalize_snapshots.add(key)
                engine.prune(float(timestamp))
        self._capture_track_snapshots(frame, current, config, float(timestamp), finalize_snapshots)
        self.snapshot_finalized.update(finalize_snapshots)
        self._persist_finalized_snapshots(finalize_snapshots)
        self._publish(frame, current, config, inference_ms, len(current))

    def _persist_finalized_snapshots(self, track_ids: set[int]) -> None:
        """Persist one annotated frame and crop for every finalized measurement."""
        pending = [track_id for track_id in track_ids if track_id not in self.evidence_files and track_id in self.track_snapshots]
        if not pending:
            return
        self.evidence_directory.mkdir(parents=True, exist_ok=True)
        for track_id in pending:
            item = self.track_snapshots[track_id]
            pts_ms = round(float(item["timestamp"]) * 1000)
            base = f"track_{track_id}_pts_{pts_ms}ms_{time.time_ns() % 1_000_000_000:09d}"
            full_path = self.evidence_directory / f"{base}_full.jpg"
            thumb_path = self.evidence_directory / f"{base}_vehicle.jpg"
            for path, content in ((full_path, item["full"]), (thumb_path, item["thumbnail"])):
                temporary = path.with_suffix(path.suffix + ".tmp")
                temporary.write_bytes(content)
                temporary.replace(path)
            self.evidence_files[track_id] = str(full_path.resolve())

    def _capture_track_snapshots(self, frame, tracks: list[Track], config: dict, timestamp: float, force_ids: set[int]) -> None:
        """Keep sparse annotated evidence in RAM; never write analysis frames to disk."""
        candidates = [
            track for track in tracks
            if track.track_id in self.confirmed_track_ids
            and track.track_id not in self.snapshot_finalized
            and (track.track_id in force_ids or timestamp - self.snapshot_updated.get(track.track_id, -10.0) >= 0.20)
        ]
        if not candidates:
            return
        preview = self._overlay(frame, tracks, config)
        ok, encoded = cv2.imencode(".jpg", preview, [cv2.IMWRITE_JPEG_QUALITY, 76])
        if not ok:
            return
        full = encoded.tobytes()
        source_h, source_w = frame.shape[:2]
        out_h, out_w = preview.shape[:2]
        sx, sy = out_w / source_w, out_h / source_h
        updates = {}
        for track in candidates:
            x1, y1, x2, y2 = track.bbox
            bw, bh = max(1.0, x2 - x1), max(1.0, y2 - y1)
            left = max(0, round((x1 - bw * .45) * sx))
            top = max(0, round((y1 - bh * .35) * sy))
            right = min(out_w, round((x2 + bw * .45) * sx))
            bottom = min(out_h, round((y2 + bh * .30) * sy))
            crop = preview[top:bottom, left:right]
            crop_ok, crop_encoded = cv2.imencode(".jpg", crop, [cv2.IMWRITE_JPEG_QUALITY, 82]) if crop.size else (False, None)
            updates[track.track_id] = {
                "full": full,
                "thumbnail": crop_encoded.tobytes() if crop_ok else full,
                "timestamp": timestamp,
            }
        with self.lock:
            self.track_snapshots.update(updates)
            for track_id in updates:
                self.snapshot_updated[track_id] = timestamp
            while len(self.track_snapshots) > 100:
                oldest = next(iter(self.track_snapshots))
                self.track_snapshots.pop(oldest, None)
                self.snapshot_updated.pop(oldest, None)

    def _publish(
        self,
        frame,
        tracks: list[Track],
        config: dict,
        inference_ms: float | None = None,
        detection_count: int | None = None,
    ) -> None:
        with self.condition:
            if inference_ms is not None:
                self.inference_ms = inference_ms
            if detection_count is not None:
                self.detected = detection_count
            self.active_tracks = len(tracks)
            self.error = ""
            now = time.monotonic()
            if self.preview_clients > 0 and now-self.last_preview_submit >= self.preview_interval:
                # Jednoelementowa kolejka: nowsza klatka zastepuje starsza.
                self.preview_pending = (frame, [copy(track) for track in tracks], config)
                self.preview_generation += 1
                self.last_preview_submit = now
                self.condition.notify_all()

    def _preview_worker(self) -> None:
        processed = 0
        while self.running:
            with self.condition:
                ready = self.condition.wait_for(
                    lambda: not self.running or (
                        self.preview_clients > 0
                        and self.preview_pending is not None
                        and self.preview_generation > processed
                    ),
                    timeout=1.0,
                )
                if not self.running:
                    return
                if not ready:
                    continue
                pending = self.preview_pending
                processed = self.preview_generation
            if pending is None:
                continue
            frame, tracks, config = pending
            preview = self._overlay(frame, tracks, config)
            ok, encoded = cv2.imencode(".jpg", preview, [cv2.IMWRITE_JPEG_QUALITY, 78])
            if ok:
                with self.condition:
                    if self.preview_clients:
                        self.latest_jpeg = encoded.tobytes()
                        self.frame_number += 1
                        self.condition.notify_all()

    def _overlay(self, frame, tracks: list[Track], config: dict):
        height, width = frame.shape[:2]
        scale = min(1.0, 1280 / width)
        if scale < 1:
            frame = cv2.resize(frame, (round(width * scale), round(height * scale)), interpolation=cv2.INTER_AREA)
        else:
            frame = frame.copy()
        out_h, out_w = frame.shape[:2]
        def point(p): return round(p[0] * out_w), round(p[1] * out_h)
        for lane in config.get("lanes", []):
            polygon = [point(p) for p in lane.get("polygon", [])]
            if len(polygon) > 2:
                cv2.polylines(frame, [__import__("numpy").array(polygon)], True, (80, 210, 150), 2)
                cv2.putText(frame, lane["id"], polygon[0], cv2.FONT_HERSHEY_SIMPLEX, .65, (80, 210, 150), 2)
        for key, color, label in (("line_a", (255, 165, 50), "A"), ("line_b", (80, 80, 255), "B")):
            line = config.get(key, [])
            if len(line) == 2:
                p1, p2 = point(line[0]), point(line[1])
                cv2.line(frame, p1, p2, color, 3)
                cv2.putText(frame, label, p1, cv2.FONT_HERSHEY_SIMPLEX, .8, color, 2)
        engine = self.engine
        for track in tracks:
            x1, y1, x2, y2 = (round(v * scale) for v in track.bbox)
            group = vehicle_group(track.class_name)
            color = (70, 220, 255) if group == "light" else (70, 140, 255)
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
            lane = engine.lane_for((track.anchor[0] / width, track.anchor[1] / height)) if engine else None
            text = f"#{track.track_id} {track.class_name} {lane['id'] if lane else '-'}"
            result = self.track_results.get(track.track_id)
            if result:
                text += f"  {result['speed_kmh']:.1f} km/h"
            elif engine and track.track_id in engine.tracks:
                state = engine.tracks[track.track_id]
                if state.time_a is not None or state.time_b is not None:
                    text += "  POMIAR..."
                if state.invalid_reason:
                    text = f"#{track.track_id} BRAK POMIARU"
            cv2.putText(frame, text, (x1, max(20, y1 - 7)), cv2.FONT_HERSHEY_SIMPLEX, .55, color, 2)
            cv2.circle(frame, (round(track.anchor[0] * scale), round(track.anchor[1] * scale)), 4, color, -1)
        return frame
