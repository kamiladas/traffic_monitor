"""Frame-by-frame reference measurements; no image files are written."""
import base64
import math
import threading
import cv2


class VideoReview:
    def __init__(self):
        self.lock = threading.RLock()
        self.capture = None
        self.path = None
        self.index = -1
        self.pts = None
        self.frame = None
        self.marks = {}
        self.count = 0
        self.fps = 0

    def close(self):
        with self.lock:
            if self.capture: self.capture.release()
            self.capture = None

    def clear_marks(self):
        with self.lock:
            self.marks = {}

    def open(self, path):
        with self.lock:
            self.close()
            self.capture = cv2.VideoCapture(str(path), cv2.CAP_FFMPEG)
            if not self.capture.isOpened():
                raise ValueError('Nie można otworzyć MP4.')
            self.path = str(path)
            self.count = int(self.capture.get(cv2.CAP_PROP_FRAME_COUNT))
            self.fps = self.capture.get(cv2.CAP_PROP_FPS)
            self.index = -1
            self.marks = {}
            return self.read(0)

    def read(self, index):
        with self.lock:
            if not self.capture: raise ValueError('Najpierw wybierz MP4.')
            index = max(0, int(index))
            if self.count > 0: index = min(index, self.count-1)
            if index != self.index:
                if index != self.index+1:
                    if not self.capture.set(cv2.CAP_PROP_POS_FRAMES, index):
                        raise ValueError('Dekoder nie obsługuje przejścia do tej klatki.')
                ok, frame = self.capture.read()
                if not ok: raise ValueError('Koniec pliku lub błąd odczytu klatki.')
                pts = self.capture.get(cv2.CAP_PROP_POS_MSEC)/1000
                if not math.isfinite(pts) or pts<0: raise ValueError('Nieprawidłowy czas klatki.')
                self.index = int(round(self.capture.get(cv2.CAP_PROP_POS_FRAMES)))-1
                self.pts = pts
                self.frame = frame
            h,w = self.frame.shape[:2]
            display = cv2.resize(self.frame, (min(w,1280), round(h*min(w,1280)/w)))
            ok, jpg = cv2.imencode('.jpg', display)
            if not ok: raise ValueError('Błąd podglądu.')
            return dict(index=self.index, pts_s=self.pts, frames=self.count, fps_nominal=self.fps,
                        image='data:image/jpeg;base64,'+base64.b64encode(jpg).decode('ascii'),
                        marks=self.marks)

    def mark(self, gate, lane):
        with self.lock:
            if gate not in ('a','b') or self.frame is None: raise ValueError('Wybierz klatkę i bramkę.')
            self.marks[gate] = dict(index=self.index, pts_s=self.pts, lane=lane['id'])
            result = dict(marks=dict(self.marks), speed_kmh=None)
            if 'a' in self.marks and 'b' in self.marks:
                a,b = self.marks['a'],self.marks['b']
                if a['lane'] != b['lane']: raise ValueError('Oba oznaczenia muszą dotyczyć jednego pasa.')
                dt = b['pts_s']-a['pts_s'] if lane['direction']=='a_to_b' else a['pts_s']-b['pts_s']
                if dt<=0: raise ValueError('Nieprawidłowa kolejność czasów A/B.')
                result.update(duration_s=dt, distance_m=lane['distance_m'], speed_kmh=3.6*lane['distance_m']/dt)
            return result
