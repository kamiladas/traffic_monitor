# TODO

## Priorytet: jakosc pomiaru

- [x] Uodpornic wykrywanie zmiany pasa na pojedyncze skoki bbox przy granicy pasa.
- [x] Uniewazniac pomiar dopiero po potwierdzonej serii obserwacji innego pasa.
- [x] Dodac testy powrotu na pierwotny pas oraz rzeczywistej zmiany pasa.
- [ ] Zweryfikowac prog `lane_change_confirmations` na kilku nagraniach dzien/noc/deszcz.
- [ ] Dodac jawne oznaczenie zmiany pasa do overlayu i raportu CSV.

## Testy wizualne

- [x] Dodac generator planszy z syntetycznymi trajektoriami zmiany pasa.
- [ ] Porownac wizualnie co najmniej trzy rzeczywiste przejazdy przy granicy pasow.
- [ ] Sprawdzic przypadek zasloniecia pojazdu w trakcie zmiany pasa.
- [ ] Sprawdzic przejazd motocykla pomiedzy pasami.

## Wydajnosc

- [ ] Dodac osobne czasy dekodowania, inferencji, analityki, overlayu i JPEG.
- [ ] Ograniczyc liczbe inferencji MP4 wedlug PTS bez zgadywania czasu.
- [ ] Wspoldzielic overlay podgladu i dowodu, gdy dotycza tej samej klatki.
- [ ] Polaczyc transfer wynikow bbox/ID/klasa/confidence z GPU do CPU.
- [ ] Porownac `imgsz` 512, 576 i 640 na tym samym materiale testowym.

## Bezpieczenstwo publikacji

- [x] Usunac profile zawierajace identyfikator prywatnego adresu kamery.
- [x] Ignorowac lokalne profile `data/configs/*.json` poza neutralnym przykladem.
- [x] Potwierdzic, ze hasla kamery nie sa zapisywane w plikach projektu.
- [ ] Powtarzac skan sekretow przed kazdym publicznym wydaniem.
