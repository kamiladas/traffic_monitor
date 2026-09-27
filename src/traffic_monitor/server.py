"""Lokalny serwer edytora geometrii ruchu drogowego."""

from __future__ import annotations

import argparse
import json
import math
import os
import threading
import time
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, unquote
import shutil
import uuid

os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp")

import cv2

from .analyzer import LiveAnalyzer
from .recorder import AnalysisControl, Recorder
from .camera import CameraConnection
from .review import VideoReview


ROOT = Path(__file__).resolve().parent
WEB_ROOT = ROOT / "web"
PROJECT_ROOT = ROOT.parents[1]
CONFIG_ROOT = PROJECT_ROOT / "data" / "configs"
MAX_BODY = 1024 * 1024


def default_config(camera_id: str, stream_url: str) -> dict:
    return {
        "version": 1,
        "camera_id": camera_id,
        "stream_url": stream_url,
        "roi": [],
        "lanes": [],
        "line_a": [],
        "line_b": [],
        "updated_at": None,
        "analysis_fps": 10,
        "detection_confidence": 0.20,
        "track_high_thresh": 0.25,
        "track_low_thresh": 0.10,
        "new_track_thresh": 0.25,
        "tracking_grace_s": 0.5,
        "inference_backend": "ultralytics_auto",
        "preview_fps": 5,
    }


def valid_point(point: object) -> bool:
    return (
        isinstance(point, list)
        and len(point) == 2
        and all(isinstance(value, (int, float)) for value in point)
        and all(0 <= float(value) <= 1 for value in point)
    )


def validate_config(data: object) -> dict:
    if not isinstance(data, dict):
        raise ValueError("Konfiguracja musi byc obiektem JSON.")
    for key, default, minimum, maximum in (("analysis_fps", 6, 2, 25), ("detection_confidence", .20, .001, .99), ("track_high_thresh", .25, .001, .99), ("track_low_thresh", .10, .001, .99), ("new_track_thresh", .25, .001, .99), ("tracking_grace_s", .5, .1, 5), ("preview_fps", 3, 1, 120)):
        value = data.get(key, default)
        if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or not minimum <= value <= maximum:
            raise ValueError(f"{key}: wymagany zakres {minimum}–{maximum}.")
    if float(data.get("track_low_thresh", .10)) > float(data.get("track_high_thresh", .25)):
        raise ValueError("track_low_thresh must not exceed track_high_thresh.")
    camera_id = data.get("camera_id")
    if data.get("inference_backend", "ultralytics_auto") not in {
        "ultralytics_auto", "ultralytics_cuda", "openvino_intel_gpu", "ultralytics_cpu"
    }:
        raise ValueError("Niepoprawne urządzenie AI.")
    if not isinstance(camera_id, str) or not camera_id.strip():
        raise ValueError("Brak camera_id.")

    roi = data.get("roi", [])
    if roi and (not isinstance(roi, list) or len(roi) < 3 or not all(map(valid_point, roi))):
        raise ValueError("ROI musi miec co najmniej 3 poprawne punkty.")

    for key in ("line_a", "line_b"):
        line = data.get(key, [])
        if line and (not isinstance(line, list) or len(line) != 2 or not all(map(valid_point, line))):
            raise ValueError(f"{key} musi miec dokladnie 2 punkty.")

    lanes = data.get("lanes", [])
    if not isinstance(lanes, list):
        raise ValueError("lanes musi byc lista.")
    seen: set[str] = set()
    for lane in lanes:
        if not isinstance(lane, dict):
            raise ValueError("Niepoprawny pas.")
        lane_id = lane.get("id")
        if not isinstance(lane_id, str) or not lane_id or lane_id in seen:
            raise ValueError("ID pasow musza byc unikalne.")
        seen.add(lane_id)
        polygon = lane.get("polygon", [])
        if len(polygon) < 3 or not all(map(valid_point, polygon)):
            raise ValueError(f"Pas {lane_id} musi miec co najmniej 3 punkty.")
        distance = lane.get("distance_m")
        if not isinstance(distance, (int, float)) or float(distance) <= 0:
            raise ValueError(f"Pas {lane_id}: odleglosc A-B musi byc dodatnia.")
        if lane.get("direction") not in ("a_to_b", "b_to_a"):
            raise ValueError(f"Pas {lane_id}: niepoprawny kierunek.")

    result = dict(data)
    result["version"] = 1
    result["camera_id"] = camera_id.strip()
    result["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    return result


class FrameSource:
    def __init__(self, stream_url: str) -> None:
        self.stream_url = stream_url
        self.lock = threading.Lock()
        self.last_jpeg: bytes | None = None
        self.last_capture = 0.0
        self.last_error = ""

    def jpeg(self, max_width: int = 1600) -> bytes:
        with self.lock:
            if self.last_jpeg is not None and time.monotonic() - self.last_capture < 1:
                return self.last_jpeg
            capture = cv2.VideoCapture(self.stream_url, cv2.CAP_FFMPEG)
            capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            ok, frame = capture.read()
            capture.release()
            if not ok:
                self.last_error = "Nie mozna pobrac klatki z MediaMTX."
                if self.last_jpeg is not None:
                    return self.last_jpeg
                raise RuntimeError(self.last_error)
            height, width = frame.shape[:2]
            if width > max_width:
                frame = cv2.resize(
                    frame,
                    (max_width, round(height * max_width / width)),
                    interpolation=cv2.INTER_AREA,
                )
            ok, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 88])
            if not ok:
                raise RuntimeError("Nie mozna zakodowac klatki JPEG.")
            self.last_jpeg = encoded.tobytes()
            self.last_capture = time.monotonic()
            self.last_error = ""
            return self.last_jpeg


def make_handler(camera_id: str, stream_url: str, frame_source: FrameSource, analyzer, recorder, camera=None, review=None):
    config_path = CONFIG_ROOT / f"{camera_id}.json"
    control_lock = threading.Lock()
    camera = camera or CameraConnection(PROJECT_ROOT)
    review = review or VideoReview()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: object) -> None:
            print(f"[HTTP] {self.address_string()} - {fmt % args}")

        def do_GET(self) -> None:  # noqa: N802
            path = urlsplit(self.path).path
            if path == "/api/config":
                self._get_config()
            elif path == '/api/camera/status':
                self._json(HTTPStatus.OK, camera.status())
            elif path == '/api/recorder/status':
                self._json(HTTPStatus.OK, recorder.status())
            elif path.startswith('/recordings/'):
                name = unquote(path[len('/recordings/'):])
                target = (recorder.directory / name).resolve()
                if target.parent != recorder.directory.resolve() or target.suffix != '.mp4' or not target.is_file():
                    self.send_error(HTTPStatus.NOT_FOUND)
                    return
                if recorder.status()['active'] and target == recorder.path.resolve():
                    self.send_error(HTTPStatus.CONFLICT, 'Stop recording before download')
                    return
                self.send_response(HTTPStatus.OK)
                self.send_header('Content-Type', 'video/mp4')
                self.send_header('Content-Disposition', 'attachment')
                self.send_header('Content-Length', str(target.stat().st_size))
                self.end_headers()
                with target.open('rb') as source:
                    shutil.copyfileobj(source, self.wfile, 1024*1024)
            elif path == "/api/frame.jpg":
                self._get_frame()
            elif path == "/api/live.mjpg":
                self._get_live()
            elif path == "/api/analyzer/status":
                self._json(HTTPStatus.OK, analyzer.status())
            elif path == "/api/stats":
                self._json(HTTPStatus.OK, analyzer.stats())
            elif path == "/api/events":
                self._json(HTTPStatus.OK, analyzer.recent_events())
            elif path == "/api/measurements":
                self._json(HTTPStatus.OK, analyzer.measurement_rows())
            elif path.startswith("/api/measurements/") and path.endswith("/frame.jpg"):
                try:
                    track_id = int(path.split("/")[3])
                except (ValueError, IndexError):
                    self.send_error(HTTPStatus.BAD_REQUEST)
                    return
                snapshot = analyzer.measurement_snapshot(track_id, "thumb=1" in urlsplit(self.path).query)
                if snapshot is None:
                    self.send_error(HTTPStatus.NOT_FOUND)
                    return
                body, timestamp = snapshot
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Source-PTS", f"{timestamp:.6f}")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif path == "/api/status":
                self._json(
                    HTTPStatus.OK,
                    {
                        "camera_id": camera_id,
                        "stream_url": stream_url,
                        "frame_error": frame_source.last_error,
                    },
                )
            else:
                self._static(path)

        def do_POST(self) -> None:  # noqa: N802
            path = urlsplit(self.path).path
            if path == '/api/file/upload':
                temporary = None
                try:
                    length = int(self.headers.get('Content-Length', '0'))
                    if self.headers.get('Content-Type') != 'video/mp4' or not 0 < length <= 4 * 1024**3:
                        raise ValueError('Wybierz MP4 o rozmiarze do 4 GB.')
                    directory = PROJECT_ROOT / 'data' / 'imports'
                    directory.mkdir(parents=True, exist_ok=True)
                    if shutil.disk_usage(directory).free < length + 128*1024**2:
                        raise ValueError('Za mało wolnego miejsca na kopię MP4.')
                    temporary = directory / (uuid.uuid4().hex + '.mp4')
                    with temporary.open('xb') as target:
                        remaining = length
                        while remaining:
                            chunk = self.rfile.read(min(1024*1024, remaining))
                            if not chunk: raise OSError('Przerwano przesyłanie MP4.')
                            target.write(chunk)
                            remaining -= len(chunk)
                    with control_lock:
                        analyzer.select_file(temporary)
                        result = review.open(temporary)
                        result['file_name'] = 'Wybrany MP4'
                        frame_source.stream_url = str(temporary)
                        frame_source.last_jpeg = None
                    self._json(HTTPStatus.OK, result)
                except (ValueError, OSError, RuntimeError) as exc:
                    if temporary and temporary.exists(): temporary.unlink()
                    self._json(HTTPStatus.BAD_REQUEST, {'error': str(exc)})
                return
            if path in ('/api/camera/connect', '/api/camera/disconnect', '/api/file/select', '/api/file/frame', '/api/file/mark', '/api/file/pause'):
                try:
                    if self.headers.get('Content-Type') != 'application/json': raise ValueError('Wymagany JSON.')
                    length = int(self.headers.get('Content-Length', '0'))
                    if not 0 < length <= MAX_BODY: raise ValueError('Niepoprawny rozmiar.')
                    payload = json.loads(self.rfile.read(length))
                    if not isinstance(payload, dict): raise ValueError('Niepoprawne dane.')
                    with control_lock:
                        if path.startswith('/api/camera/'):
                            if recorder.status()['active']: raise ValueError('Najpierw zakończ nagranie.')
                            if path.endswith('/connect'): camera.connect(payload)
                            else: camera.stop()
                            result = camera.status()
                        elif path == '/api/file/select':
                            selected = payload.get('path', '')
                            if not selected: raise ValueError('Wybierz MP4 przyciskiem albo wpisz pełną ścieżkę.')
                            selected = Path(selected).resolve()
                            if recorder.status()['active'] and selected == recorder.path.resolve(): raise ValueError('Najpierw zakończ zapis tego nagrania.')
                            analyzer.select_file(selected)
                            result = review.open(selected)
                            result['file_name'] = selected.name
                            frame_source.stream_url = str(selected)
                            frame_source.last_jpeg = None
                        elif path == '/api/file/frame': result = review.read(payload.get('index', 0))
                        elif path == '/api/file/mark':
                            config = json.loads(config_path.read_text(encoding='utf-8'))
                            lane = next((l for l in config.get('lanes',[]) if l['id']==payload.get('lane')), None)
                            if lane is None: raise ValueError('Wybierz zapisany pas.')
                            result = review.mark(payload.get('gate'), lane)
                        else:
                            if not analyzer.running: raise ValueError('Analiza nie jest uruchomiona.')
                            if not analyzer.instance.file_mode: raise ValueError('Pauza dotyczy tylko analizy MP4.')
                            analyzer.instance.paused = bool(payload.get('paused'))
                            result = {'paused': analyzer.instance.paused}
                    self._json(HTTPStatus.OK, result)
                except (ValueError, OSError, RuntimeError) as exc:
                    self._json(HTTPStatus.BAD_REQUEST, {'error': str(exc)})
                return
            if path in ('/api/recorder/start', '/api/recorder/stop', '/api/analyzer/start', '/api/analyzer/stop', '/api/shutdown'):
                if self.headers.get('Content-Type') != 'application/json':
                    self.send_error(HTTPStatus.UNSUPPORTED_MEDIA_TYPE)
                    return
                try:
                    length = int(self.headers.get('Content-Length', '0'))
                    if length < 0 or length > MAX_BODY: raise ValueError('Niepoprawny rozmiar zadania.')
                    payload = json.loads(self.rfile.read(length)) if length else {}
                    if not isinstance(payload, dict): raise ValueError('Wymagany obiekt JSON.')
                    with control_lock:
                        if path == '/api/recorder/start':
                            if not camera.status()['connected']: raise ValueError('Najpierw połącz kamerę w Rejestratorze.')
                            analyzer.stop()
                            recorder.start()
                        elif path == '/api/recorder/stop': recorder.stop()
                        elif path == '/api/analyzer/start':
                            if recorder.status()['active']:
                                raise ValueError('Najpierw zatrzymaj nagranie, aby uruchomić AI.')
                            source = payload.get('source', 'file')
                            if source not in ('file', 'live'): raise ValueError('Wybierz źródło MP4 albo Live RTSP.')
                            if source == 'live' and not camera.status()['connected']:
                                raise ValueError('Najpierw połącz kamerę w Rejestratorze.')
                            analyzer.start(source)
                        elif path == '/api/analyzer/stop': analyzer.stop()
                        else:
                            recorder.stop()
                            analyzer.stop()
                            camera.stop()
                            review.close()
                    self._json(HTTPStatus.OK, {'ok': True})
                    if path == '/api/shutdown':
                        threading.Thread(target=self.server.shutdown, daemon=True).start()
                except (ValueError, OSError, RuntimeError) as error:
                    self._json(HTTPStatus.BAD_REQUEST, {'error': str(error)})
                return
            if path not in ("/api/config", "/api/analysis/settings"):
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > MAX_BODY:
                    raise ValueError("Niepoprawny rozmiar zadania.")
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                if path == '/api/analysis/settings':
                    if not isinstance(payload, dict):
                        raise ValueError('Niepoprawne ustawienia.')
                    current = json.loads(config_path.read_text(encoding='utf-8')) if config_path.exists() else default_config(camera_id, stream_url)
                    current.update({key: payload[key] for key in ('analysis_fps', 'detection_confidence', 'track_high_thresh', 'track_low_thresh', 'new_track_thresh', 'tracking_grace_s', 'inference_backend', 'preview_fps') if key in payload})
                    payload = current
                data = validate_config(payload)
                CONFIG_ROOT.mkdir(parents=True, exist_ok=True)
                temporary = config_path.with_suffix(".json.tmp")
                temporary.write_text(
                    json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                temporary.replace(config_path)
                if path == '/api/config':
                    review.clear_marks()
                self._json(HTTPStatus.OK, {"ok": True, "config": data})
            except (ValueError, json.JSONDecodeError) as error:
                self._json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(error)})

        def _get_config(self) -> None:
            if config_path.exists():
                try:
                    data = json.loads(config_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError) as error:
                    self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(error)})
                    return
            else:
                data = default_config(camera_id, stream_url)
            self._json(HTTPStatus.OK, data)

        def _get_frame(self) -> None:
            if analyzer.selected_file is None:
                self._json(HTTPStatus.CONFLICT, {'error': 'Wybierz MP4 do konfiguracji geometrii.'})
                return
            try:
                body = frame_source.jpeg()
            except RuntimeError as error:
                self._json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": str(error)})
                return
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _get_live(self) -> None:
            active = analyzer.instance
            if active is None or not active.running:
                self.send_error(HTTPStatus.CONFLICT, 'AI is disabled')
                return
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            active.add_preview_client()
            sequence = -1
            try:
                while active.running:
                    sequence, jpeg = active.wait_jpeg(sequence)
                    if jpeg is None:
                        continue
                    self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\n")
                    self.wfile.write(f"Content-Length: {len(jpeg)}\r\n\r\n".encode())
                    self.wfile.write(jpeg)
                    self.wfile.write(b"\r\n")
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass
            finally:
                active.remove_preview_client()

        def _static(self, path: str) -> None:
            relative = "index.html" if path in ("", "/") else path.lstrip("/")
            target = (WEB_ROOT / relative).resolve()
            if WEB_ROOT.resolve() not in target.parents and target != WEB_ROOT.resolve():
                self.send_error(HTTPStatus.FORBIDDEN)
                return
            if not target.is_file():
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            content_types = {
                ".html": "text/html; charset=utf-8",
                ".css": "text/css; charset=utf-8",
                ".js": "text/javascript; charset=utf-8",
                ".svg": "image/svg+xml",
            }
            body = target.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_types.get(target.suffix, "application/octet-stream"))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: HTTPStatus, data: object) -> None:
            def scalar(value: object) -> object:
                if hasattr(value, "item"):
                    return value.item()
                raise TypeError(f"Nieobslugiwany typ JSON: {type(value).__name__}")

            body = json.dumps(data, ensure_ascii=False, default=scalar).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description="Edytor stref analizy ruchu.")
    parser.add_argument("--camera-id", default="camera_local")
    parser.add_argument("--stream", default="rtsp://127.0.0.1:8554/camera")
    parser.add_argument("--port", type=int, default=12000)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    source = FrameSource(args.stream)
    config_path = CONFIG_ROOT / f"{args.camera_id}.json"
    model_path = PROJECT_ROOT / "vendor" / "models" / "yolo26s.pt"
    analyzer = AnalysisControl(args.stream, config_path, model_path)
    recorder = Recorder(args.stream, PROJECT_ROOT / 'data' / 'recordings')
    camera = CameraConnection(PROJECT_ROOT)
    review = VideoReview()
    server = ThreadingHTTPServer(
        ("127.0.0.1", args.port), make_handler(args.camera_id, args.stream, source, analyzer, recorder, camera, review)
    )
    url = f"http://127.0.0.1:{args.port}/"
    print(f"Edytor: {url}")
    print("Wybierz MP4 do analizy. Kamera jest opcjonalna w Rejestratorze.")
    if not args.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever(0.25)
    except KeyboardInterrupt:
        print("\nZatrzymywanie edytora...")
    finally:
        recorder.stop()
        analyzer.stop()
        camera.stop()
        review.close()
        server.server_close()


if __name__ == "__main__":
    main()
