# Sentinel Node V3.8

Firmware ESP32 per una centralina di acquisizione e telemetria locale.

Il progetto è basato su **ESP32 + Arduino + PlatformIO** e gestisce acquisizione sensori, memoria FRAM, RTC, comunicazione con il server locale e aggiornamento firmware OTA.

L'architettura privilegia semplicità, funzionamento locale e recupero dei dati in caso di assenza temporanea della rete.

---

## Hardware

Il firmware è configurato per la scheda PlatformIO:

```text
board = esp32dev
```

Componenti gestiti dal firmware includono:

* ESP32
* FRAM I2C
* RTC DS3231
* ADS1115
* MAX31865 / PT1000
* DHT
* sensori OneWire
* display LCD I2C
* Wi-Fi

Le librerie utilizzate sono bloccate a versioni precise in `platformio.ini` per evitare modifiche imprevedibili dell'ambiente di compilazione.

---

## Requisiti

Ambiente di sviluppo:

* Linux
* Python 3
* PlatformIO
* ESP32
* connessione USB per il primo flash

La piattaforma ESP32 utilizzata dal progetto è:

```text
espressif32@6.13.0
```

Framework:

```text
Arduino
```

Monitor seriale:

```text
115200 baud
```

---

## Configurazione

Il progetto utilizza variabili d'ambiente per i parametri che non devono essere inseriti direttamente nel codice.

Il file locale è:

```text
.env
```

Il file `.env` non deve essere pubblicato nel repository.

Prima della compilazione viene eseguito:

```bash
python3 generate_secrets.py
```

Il Makefile esegue automaticamente questo passaggio durante le operazioni di build e flash.

---

## Versione firmware

La versione del firmware è definita in un unico file:

```text
version.txt
```

Attualmente:

```text
932
```

Il file viene utilizzato come sorgente unica della versione.

Durante una build locale il `Makefile` esegue:

```makefile
VERSION := $(shell cat version.txt)
export FW_VERSION := $(VERSION)
```

PlatformIO passa quindi la versione al compilatore:

```text
FW_VERSION
```

Il firmware può utilizzare questo valore per:

* identificare la versione in esecuzione;
* confrontare la versione locale con quella disponibile sul server;
* comunicare la propria versione al backend;
* gestire gli aggiornamenti OTA.

Per cambiare versione è sufficiente modificare:

```text
version.txt
```

---

# Compilazione

La compilazione standard è:

```bash
make
```

Il comando:

1. genera i parametri necessari;
2. carica `.env`;
3. passa `FW_VERSION`;
4. esegue la compilazione PlatformIO;
5. genera il firmware ESP32.

Il firmware principale viene generato in:

```text
.pio/build/esp32dev/firmware.bin
```

Durante la build viene inoltre generato il firmware merged tramite `merge_bin.py`.

---

# Flash iniziale

Per programmare fisicamente l'ESP32 tramite USB:

```bash
make flash
```

Il comando esegue una build e successivamente il target PlatformIO `upload`.

Il monitor seriale utilizza:

```text
115200
```

---

# Aggiornamento OTA

Sentinel supporta l'aggiornamento firmware OTA.

Il dispositivo controlla il server configurato tramite:

```text
UPDATE_URL
```

Il server restituisce la versione disponibile e l'URL del firmware.

Il dispositivo confronta la versione remota con:

```text
FW_VERSION
```

e avvia l'aggiornamento soltanto quando:

```text
versione remota > versione installata
```

L'aggiornamento viene eseguito utilizzando `HTTPUpdate`.

Il sistema attuale utilizza HTTP nella rete locale.

HTTPS non è attualmente utilizzato e potrà essere introdotto in seguito senza modificare il meccanismo generale di versionamento e release.

---

# Deploy del firmware

Per preparare e trasferire il firmware al server locale:

```bash
make upload
```

Il comando:

1. genera i secrets;
2. compila il firmware;
3. legge la versione da `version.txt`;
4. crea il file:

```text
sentinel_v932.bin
```

5. lo copia nella directory locale dei firmware;
6. trasferisce il file sulla Raspberry Pi tramite `rsync`.

La destinazione configurata nel Makefile è:

```text
~/sentinel_flask/firmware_builds
```

Il nome del firmware contiene sempre la versione:

```text
sentinel_v<versione>.bin
```

Per esempio:

```text
sentinel_v932.bin
```

---

# GitHub Actions

Il repository dispone di una pipeline GitHub Actions per verificare automaticamente la compilazione.

La CI:

1. esegue il checkout del repository;
2. installa Python;
3. legge `version.txt`;
4. imposta `FW_VERSION`;
5. installa PlatformIO;
6. compila il firmware;
7. salva i binari come artifact.

La versione utilizzata dalla CI è quindi sempre quella contenuta in:

```text
version.txt
```

Non deve essere inserita manualmente nel workflow.

---

# Firmware merged

Il progetto utilizza:

```text
merge_bin.py
```

per creare un'immagine firmware merged contenente:

```text
bootloader
+
partitions
+
application
```

Il merge viene eseguito automaticamente dopo la compilazione.

Lo script utilizza l'esptool fornito dall'ambiente PlatformIO, evitando dipendenze esterne dall'ambiente Python del sistema.

---

# Makefile

I principali comandi disponibili sono:

| Comando         | Funzione                                        |
| --------------- | ----------------------------------------------- |
| `make`          | Compila il firmware                             |
| `make flash`    | Compila e programma l'ESP32 via USB             |
| `make upload`   | Compila e trasferisce il firmware al server OTA |
| `make uploadfs` | Aggiorna il filesystem                          |
| `make clean`    | Pulisce la build PlatformIO                     |
| `make update`   | Aggiorna le dipendenze PlatformIO               |
| `make feed`     | Esegue lo script di generazione del contenuto   |
| `make deploy`   | Esegue lo script di deploy del repository       |

---

# Struttura del progetto

La struttura attuale del firmware è:

```text
sentinel_esp32/
├── .github/
│   └── workflows/
│       └── esp32-ci.yml
│
├── src/
│   └── main.ino
│
├── platformio.ini
├── Makefile
├── version.txt
├── generate_secrets.py
├── merge_bin.py
├── .env
└── .gitignore
```

La directory `.pio/` viene generata automaticamente da PlatformIO e non fa parte del codice sorgente.

---

# Release

Il flusso previsto è:

```text
version.txt
     │
     ▼
Git commit
     │
     ▼
GitHub Actions
     │
     ▼
Build firmware
     │
     ▼
firmware.bin
     │
     ▼
make upload
     │
     ▼
Raspberry Pi
     │
     ▼
OTA
     │
     ▼
ESP32
```

La versione del firmware è quindi tracciabile dall'origine del codice fino al dispositivo installato.

---

# Sicurezza

Il progetto mantiene separati codice e configurazione locale.

I parametri sensibili vengono forniti tramite:

```text
.env
```

e gestiti durante la fase di build.

Il firmware OTA attuale opera sulla rete locale tramite HTTP.

HTTPS, firma digitale del firmware e meccanismi di verifica aggiuntivi potranno essere introdotti quando emergerà una necessità concreta.

---

# Documentazione

La documentazione del progetto è volutamente essenziale.

I riferimenti principali sono:

```text
README.md
CHANGELOG.md
```

Il README descrive il funzionamento operativo del progetto.

Il CHANGELOG registra le modifiche firmware significative tra una versione e l'altra.
