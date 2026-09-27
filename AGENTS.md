# AGENTS.md

## Cel

Lekka lokalna analiza ruchu z RTSP lub MP4: edytowane ROI, dowolna liczba pasow,
linie A/B, tracking wielu pojazdow, predkosc, GAP i statystyki light/heavy.

## Zasady stale

- Jedyny launcher: `run.py`.
- Analiza nie zapisuje klatek posrednich. Dla kazdego zakonczonego rekordu
  zapisuje jedna pelna klatke z overlayem i jeden crop pojazdu do
  `data/evidence/<sesja>/`. MP4 powstaje tylko po jawnym uruchomieniu Rejestratora.
- MediaMTX ma `record: no`, laczy kamere przez RTSP/TCP i nie transkoduje.
- Hasla kamery pozostaja w pamieci procesu. Uslugi nasluchuja na `127.0.0.1`.
- Czas pomiaru pochodzi z PTS, nie z numeru klatki ani czasu CPU.
- Zerwanie PTS lub trackera uniewaznia pomiar; nie wolno go zgadywac.
- Bez OCR tablic, segmentacji i ciezkiego ReID bez wyraznej potrzeby.

## Architektura

- `src/traffic_monitor/detector.py`: YOLO26s i persistent FastTracker przez Ultralytics.
- `src/traffic_monitor/analyzer.py`: analiza sekwencyjna, PTS i podglad w pamieci.
- `src/traffic_monitor/analytics.py`: przejscia A/B, predkosc, GAP i statystyki.
- `src/traffic_monitor/web`: edytor Canvas geometrii znormalizowanej 0..1.
- `vendor/mediamtx`: lokalny restream; `vendor/models`: lokalne wagi modelu.
- `data/configs`: trwale profile JSON; `data/recordings`: tylko nagrania na zadanie.

Pojazd przypisuj do ROI i pasa srodkiem dolnej krawedzi bbox. Klasy car i
motorcycle to light, bus i truck to heavy. Obsluga pasow nie ma stalego limitu.

## Testy

```powershell
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m py_compile src\traffic_monitor\*.py
node --check src\traffic_monitor\web\app.js
```
