from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path


ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
PYTHON = VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
REQUIREMENTS = ROOT / "requirements.txt"
STAMP = VENV / ".requirements-ok"
MODEL = ROOT / "vendor/models/yolo26s.pt"
URL = "http://127.0.0.1:12000/"


def run(command: list[str], **kwargs: object) -> None:
    subprocess.run(command, check=True, **kwargs)


def setup() -> None:
    if not PYTHON.exists():
        print("Tworze izolowane srodowisko Python...")
        run([sys.executable, "-m", "venv", str(VENV)])

    if not STAMP.exists() or REQUIREMENTS.stat().st_mtime_ns > STAMP.stat().st_mtime_ns:
        print("Instaluje zaleznosci YOLO26...")
        run([
            str(PYTHON), "-m", "pip", "install", "--disable-pip-version-check",
            "-r", str(REQUIREMENTS),
        ])
        STAMP.touch()

    if not MODEL.exists():
        print("Pobieram oficjalny model yolo26s.pt...")
        run([
            str(PYTHON), "-c",
            "from ultralytics import YOLO; YOLO('yolo26s.pt')",
        ], cwd=ROOT)
        downloaded = ROOT / "yolo26s.pt"
        if not downloaded.exists():
            raise RuntimeError("Nie pobrano modelu yolo26s.pt.")
        MODEL.parent.mkdir(parents=True, exist_ok=True)
        downloaded.replace(MODEL)

    if shutil.which("nvidia-smi"):
        result = subprocess.run(
            [str(PYTHON), "-c", "import torch; print('yes' if torch.cuda.is_available() else 'no')"],
            capture_output=True, text=True,
        )
        if result.stdout.strip() != "yes":
            print("Wykryto NVIDIA. Instaluje PyTorch CUDA 13.0...")
            try:
                run([
                    str(PYTHON), "-m", "pip", "install", "--disable-pip-version-check",
                    "--upgrade", "torch", "torchvision", "--index-url",
                    "https://download.pytorch.org/whl/cu130",
                ])
            except subprocess.CalledProcessError:
                print("UWAGA: Nie udalo sie wlaczyc CUDA; aplikacja pozostanie na CPU.")


def server_is_running() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", 12000), timeout=0.5):
            return True
    except OSError:
        return False


def shutdown_server() -> None:
    request = urllib.request.Request(URL + "api/shutdown", data=b"{}", method="POST")
    request.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(request, timeout=30):
        pass


def main() -> int:
    os.chdir(ROOT)
    setup()
    if server_is_running():
        raise RuntimeError("Aplikacja juz dziala na 127.0.0.1:12000. Zamknij poprzednie okno run.py.")

    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(ROOT / "src")
    process = subprocess.Popen(
        [str(PYTHON), "-m", "traffic_monitor.server", "--no-browser"],
        cwd=ROOT, env=environment,
    )
    try:
        time.sleep(1)
        if process.poll() is not None:
            raise RuntimeError("Serwer nie wystartowal. Sprawdz komunikaty powyzej.")
        print(f"Aplikacja: {URL}")
        print("Analiza MP4 bez kamery. IP i haslo kamery podaj w Rejestratorze.")
        print("ENTER konczy zapis i zatrzymuje aplikacje.")
        webbrowser.open(URL)
        input()
    finally:
        if process.poll() is None:
            try:
                shutdown_server()
                process.wait(timeout=5)
            except Exception as error:
                print(f"UWAGA: Nie udalo sie lagodnie zatrzymac aplikacji: {error}")
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
    except Exception as error:
        print(f"BLAD: {error}", file=sys.stderr)
        raise SystemExit(1)
