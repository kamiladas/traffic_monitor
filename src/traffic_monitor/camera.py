"""On-demand local MediaMTX. Camera credentials exist only in process memory."""
import ipaddress
import os
import socket
import subprocess
import time
from urllib.parse import quote


class CameraConnection:
    def __init__(self, root):
        self.root = root
        self.process = None
        self.ip = None

    def status(self):
        connected = self.process is not None and self.process.poll() is None
        return {'connected': connected, 'ip': self.ip if connected else None}

    def connect(self, data):
        address = ipaddress.ip_address(data.get('ip', '').strip())
        channel = str(data.get('channel', '101'))
        if not channel.isdigit() or len(channel)>6:
            raise ValueError('Niepoprawny kanał kamery.')
        user = data.get('user', 'admin')
        password = data.get('password', '')
        if not isinstance(user, str) or not isinstance(password, str) or not user or not password:
            raise ValueError('Podaj użytkownika i hasło kamery.')
        self.stop()
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.settimeout(.25)
            if probe.connect_ex(('127.0.0.1', 8554)) == 0:
                raise ValueError('Port RTSP 127.0.0.1:8554 jest zajęty przez inny proces MediaMTX.')
        host = f'[{address}]' if address.version == 6 else str(address)
        env = os.environ.copy()
        env['MTX_PATHS_CAMERA_SOURCE'] = f'rtsp://{quote(user, safe="")}:{quote(password, safe="")}@{host}:554/Streaming/Channels/{channel}'
        media = self.root/'vendor'/'mediamtx'
        self.process = subprocess.Popen([str(media/'mediamtx.exe'), str(media/'mediamtx-camera.yml')],
            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        self.ip = str(address)
        time.sleep(.5)
        if self.process.poll() is not None:
            self.stop()
            raise ValueError('MediaMTX nie wystartował. Sprawdź, czy poprzednia aplikacja jest zamknięta.')

    def stop(self):
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try: self.process.wait(timeout=4)
            except subprocess.TimeoutExpired: self.process.kill(); self.process.wait()
        self.process = None
        self.ip = None
