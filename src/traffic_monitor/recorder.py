"""Explicit, low-CPU MP4 recording by copying the local RTSP stream."""
import os
import shutil
import subprocess
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

import imageio_ffmpeg


class Recorder:
    def __init__(self, stream, directory):
        self.stream = stream
        self.directory = Path(directory)
        self.lock = threading.RLock()
        self.process = None
        self.worker = None
        self.path = None
        self.started = 0
        self.elapsed = 0
        self.error = ''
        self.state = 'idle'

    def status(self):
        with self.lock:
            active = self.state in ('starting', 'recording', 'stopping')
            return dict(state=self.state, error=self.error, active=active,
                        elapsed_s=round(time.monotonic()-self.started if active else self.elapsed, 1),
                        filename=self.path.name if self.path else None,
                        size_bytes=self.path.stat().st_size if self.path and self.path.exists() else 0,
                        directory=str(self.directory.resolve()),
                        files=[dict(name=p.name, size_bytes=p.stat().st_size)
                               for p in sorted(self.directory.glob('*.mp4'), reverse=True)][:100])

    def start(self):
        with self.lock:
            if self.state in ('starting', 'recording', 'stopping'):
                raise ValueError('Nagrywanie jest już uruchomione.')
            self.directory.mkdir(parents=True, exist_ok=True)
            if shutil.disk_usage(self.directory).free < 512 * 1024**2:
                raise ValueError('Za mało wolnego miejsca (minimum 512 MB).')
            self.path = self.directory / (datetime.now().strftime('%Y-%m-%d_%H-%M-%S_') + uuid.uuid4().hex[:8] + '.mp4')
            command = [imageio_ffmpeg.get_ffmpeg_exe(), '-hide_banner', '-loglevel', 'error',
                       '-n', '-rtsp_transport', 'tcp', '-timeout', '5000000',
                       '-i', self.stream, '-map', '0:v:0', '-an', '-c:v', 'copy',
                       '-movflags', '+frag_keyframe+empty_moov+default_base_moof',
                       '-progress', 'pipe:1', '-nostats', str(self.path)]
            self.error = ''
            self.elapsed = 0
            self.started = time.monotonic()
            self.process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='replace',
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            self.state = 'starting'
            self.worker = threading.Thread(target=self._watch, args=(self.process,), daemon=True)
            self.worker.start()

    def _watch(self, process):
        errors = []
        def read_errors():
            for line in process.stderr:
                errors.append(line.strip())
                del errors[:-8]
        reader = threading.Thread(target=read_errors, daemon=True)
        reader.start()
        for line in process.stdout:
            if line.startswith('frame='):
                try:
                    if int(line.split('=', 1)[1]) > 0:
                        with self.lock:
                            if self.state == 'starting': self.state = 'recording'
                except ValueError:
                    pass
        result = process.wait()
        reader.join(timeout=1)
        with self.lock:
            self.elapsed = time.monotonic()-self.started
            self.state = 'finished' if result == 0 else 'error'
            self.error = '' if result == 0 else (' '.join(errors)[-1500:] or 'Nagrywanie przerwane.')
        for pipe in (process.stdin, process.stdout, process.stderr):
            if pipe: pipe.close()

    def stop(self):
        with self.lock:
            process = self.process
            worker = self.worker
            if not process or process.poll() is not None:
                return
            self.state = 'stopping'
            try:
                process.stdin.write('q\n')
                process.stdin.flush()
            except (OSError, ValueError):
                pass
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.terminate()
            try: process.wait(timeout=3)
            except subprocess.TimeoutExpired: process.kill(); process.wait()
        if worker: worker.join(timeout=3)


class AnalysisControl:
    """Run one analyzer from a selected MP4 or the configured local RTSP stream."""
    def __init__(self, *args):
        self.args = args
        self.live_stream = args[0]
        self.instance = None
        self.selected_file = None
        self.source_mode = 'file'

    def select_file(self, path):
        path = Path(path).resolve()
        if path.suffix.lower() != '.mp4' or not path.is_file():
            raise ValueError('Wybierz istniejący plik MP4.')
        import cv2
        cap = cv2.VideoCapture(str(path))
        ok, frame = cap.read()
        cap.release()
        if not ok: raise ValueError('Nie można odczytać obrazu z MP4.')
        self.stop()
        self.instance = None
        self.selected_file = path

    @property
    def running(self):
        return self.instance is not None and self.instance.running

    def start(self, source='file'):
        if source not in ('file', 'live'):
            raise ValueError('Wybierz źródło MP4 albo Live RTSP.')
        if source == 'file' and self.selected_file is None:
            raise ValueError('Najpierw wybierz MP4 w zakładce MP4 / Kalibracja.')
        if self.running:
            if source == self.source_mode: return
            self.stop()
        from .analyzer import LiveAnalyzer
        stream = str(self.selected_file) if source == 'file' else self.live_stream
        instance = LiveAnalyzer(stream, *self.args[1:])
        instance.start()
        self.instance = instance
        self.source_mode = source

    def stop(self):
        if self.instance:
            self.instance.stop()

    def status(self):
        if self.instance:
            result = self.instance.status()
            result['enabled'] = self.running
            if not self.running:
                result.update(connected=False, error='AI wyłączone — uruchom w Rejestratorze', active_tracks=0)
            return result
        return dict(enabled=False, running=False, connected=False, source_kind=self.source_mode, file_name=self.selected_file.name if self.selected_file and self.source_mode == 'file' else None, error='Wybierz MP4 albo połącz kamerę i uruchom analizę.', active_tracks=0,
                    inference_ms=None, profile_ready=False)

    def stats(self):
        return self.instance.stats() if self.instance else dict(lanes={}, total=0)

    def recent_events(self):
        return self.instance.recent_events() if self.instance else []

    def measurement_rows(self):
        return self.instance.measurement_rows() if self.instance else []

    def measurement_snapshot(self, track_id, thumbnail=False):
        return self.instance.measurement_snapshot(track_id, thumbnail) if self.instance else None
