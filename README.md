# Traffic Monitor YOLO26

Nowa implementacja lokalnej analizy ruchu. Zachowuje kalibracje ROI/pasow i
bramek A/B, ale detekcje i tracking realizuje YOLO26s z FastTrackerem.

Uruchom `python run.py`. Pierwszy start tworzy `.venv`, instaluje zaleznosci i pobiera
oficjalny model `yolo26s.pt`. Aplikacja dziala na http://127.0.0.1:12000/.
W ustawieniach mozna wybrac Automatycznie, NVIDIA/CUDA, Intel Iris Xe/OpenVINO
albo CPU. Gdy wybrany akcelerator jest niedostepny, aplikacja bezpiecznie wraca
do CPU i pokazuje powod w interfejsie.

## Instalacja i zaleznosci

Wymagania podstawowe:

- Windows 10/11 x64,
- Python x64 dostepny jako polecenie `python`,
- polaczenie z Internetem podczas pierwszej instalacji,
- aktualny sterownik wybranego GPU,
- kilka GB wolnego miejsca na `.venv` (PyTorch CUDA jest najwieksza czescia).

Jedynym punktem startowym aplikacji jest:

```powershell
python .\run.py
```

Pierwsze uruchomienie automatycznie:

1. tworzy lokalne srodowisko `.venv`,
2. instaluje pakiety z `requirements.txt`,
3. pobiera `vendor/models/yolo26s.pt`,
4. instaluje wariant PyTorch CUDA, jesli komputer ma NVIDIA,
5. uruchamia lokalny serwer na `http://127.0.0.1:12000/`.

Glowne zaleznosci Python:

- `ultralytics[export-openvino]` - YOLO26, FastTracker i eksport OpenVINO,
- `torch`, `torchvision` - backend CPU/NVIDIA CUDA i eksport modelu,
- `openvino`, `nncf` - Intel CPU/GPU oraz konwersja modelu,
- `opencv-python` - dekodowanie i obsluga obrazu,
- `lap` - przypisywanie detekcji w trackerze,
- `imageio-ffmpeg` - binaria FFmpeg,
- `requests` - lokalna komunikacja pomocnicza,
- `pytest` - testy projektu.

MediaMTX jest dostarczony w `vendor/mediamtx`; nie wymaga osobnej instalacji.
Aktualizacja zaleznosci odbywa sie przez zmianę `requirements.txt` i ponowne
uruchomienie `python run.py`. Instalator wykrywa nowszy plik i aktualizuje `.venv`.

Kontrola instalacji:

```powershell
.\.venv\Scripts\python.exe -c "import torch, openvino as ov; print('CUDA:', torch.cuda.is_available()); print('OpenVINO:', ov.Core().available_devices)"
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -m pytest -q
```

## GPU i uruchamianie na innym komputerze

### NVIDIA (CUDA)

1. Zainstaluj aktualny sterownik NVIDIA i sprawdz, czy polecenie `nvidia-smi`
   widzi karte.
2. Uruchom `python run.py`. Instalator zachowuje wariant PyTorch z CUDA, gdy wykryje
   NVIDIA.
3. W `Ustawienia sesji -> Urzadzenie` wybierz `NVIDIA / CUDA` albo
   `Automatycznie (NVIDIA/CPU)`.
4. Pasek stanu musi pokazac `NVIDIA / CUDA`. W przeciwnym razie aplikacja poda
   powod przejscia na CPU.

### Intel Iris Xe (OpenVINO)

1. Zainstaluj aktualny sterownik Intel Graphics dla danego laptopa. OpenVINO
   korzysta z obslugi OpenCL dostarczanej przez ten sterownik.
2. Uruchom `python run.py`, aby zainstalowac zaleznosci OpenVINO.
3. W ustawieniach wybierz `Intel Iris Xe / OpenVINO` i zapisz ustawienia.
4. Przy pierwszym uruchomieniu aplikacja jednorazowo eksportuje
   `vendor/models/yolo26s.pt` do katalogu
   `vendor/models/yolo26s_openvino_model`. Moze to potrwac kilka minut.
5. Pasek stanu musi pokazac `Intel Iris Xe / OpenVINO`. Jesli OpenVINO nie widzi
   GPU, aplikacja przejdzie na CPU i wyswietli liste wykrytych urzadzen.

Dostepne urzadzenia OpenVINO mozna sprawdzic poleceniem:

```powershell
.\.venv\Scripts\python.exe -c "import openvino as ov; print(ov.Core().available_devices)"
```

Oczekiwany wynik dla Iris Xe zawiera `GPU` albo `GPU.0`. Intel GPU nie korzysta
z CUDA. Karty AMD nie maja obecnie osobnego backendu w aplikacji i dzialaja
przez CPU; dodanie DirectML lub ROCm wymaga osobnej implementacji i testow dla
konkretnego systemu.

Dokumentacja producentow:

- https://docs.ultralytics.com/integrations/openvino
- https://docs.openvino.ai/2025/openvino-workflow/running-inference/inference-devices-and-modes/gpu-device.html

Predkosc nie korzysta z demonstracyjnego `meter_per_pixel`: czas pochodzi z PTS,
a droga z odleglosci A-B zapisanej osobno dla kazdego pasa. Pojazd zasloniety
przed ukonczeniem A-B pozostaje wykryty, ale nie otrzymuje zgadywanej predkosci.

Analiza nie zapisuje klatek posrednich. Dla kazdego zakonczonego rekordu
(poprawnego lub odrzuconego) zapisuje jedna pelna klatke z overlayem i jeden
crop pojazdu do `data/evidence/<sesja>/`.

Kod Ultralytics i oficjalne modele podlegaja AGPL-3.0 lub licencji Enterprise.
