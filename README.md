
# Sentinel Node V3.8

**Il Notaio Digitale per Industrial-IoT**

Centralina polivalente ad alta affidabilità per il monitoraggio e la notarizzazione dati in ambienti industriali rigidi (HACCP, caseifici, officine, impianti B2B). Progettata per garantire **determinismo operativo**, **zero perdite di log** e **architettura local-first** indipendente dalla stabilità della rete.

---

## Architettura del Sistema

Il repository è strutturato come monorepo e contiene due componenti software distinti e complementari:

* **`firmware/` (C++ / ESP32)**: Il codice sorgente dell'unità di campo basato su PlatformIO. Gestisce l'acquisizione dei sensori, la scrittura deterministica su memoria FRAM via $I^2C$ e l'invio sicuro dei dati tramite REST API.
* **`server/` (Python / Flask)**: Il backend centrale eseguito su nodo locale (es. Raspberry Pi). Riceve la telemetria, gestisce l'ingestione su database SQLite, espone la dashboard UI e fornisce l'endpoint per gli aggiornamenti firmware OTA.

```text
               +-----------------------------------+
               |         SENTINEL NODE V3.8        |
               |   Firmware C++ (ESP32 + FRAM)     |
               +-----------------------------------+
                                 |
                                 | mTLS / REST API (JSON + SHA-256)
                                 v
               +-----------------------------------+
               |          SENTINEL SERVER          |
               |    Backend Python (Flask + DB)    |
               +-----------------------------------+
                                 |
                        Dashboard UI / CSV

```

---

## Architettura Hardware

* **Target CPU**: ESP32-WROVER-E (Dual-Core Xtensa LX6, Wi-Fi / Bluetooth LE)
* **Storage Principale**: Memoria FRAM MB85RC256V da 256 Kb via I2C (Scritture praticamente infinite, latenza zero, **ZERO SD-Card**)
* **RTC Dedicato**: DS3231 per timestamping accurato e certificato del log
* **Power Management**: Alimentazione nominale a 12V DC con Step-Down MP1584EN ad alta efficienza termica
* **Protezione e Disaccoppiamento**:
* Ingressi analogici/gas isolati via ADC esteso ADS1115 (bus $I^2C$) per non caricare l'ADC interno dell'ESP32
* Protezione transitori fino a 14.89V PASS
* Attuatori locali disaccoppiati tramite optoisolatori e MOSFET per carichi pesanti (ventole, allerte, elettrovalvole)



---

## Funzionalità Chiave & Logica Local-First

1. **Abolizione delle SD-Card**: Le SD sono fragili e si corrompono nei blackout. Il Sentinel usa la FRAM per la scrittura istantanea dei pacchetti di telemetry.
2. **Buffer Distribuito e Handshake ACK**: I dati rimangono notarizzati nella FRAM locale finché il backend remoto non invia un codice `201 Created` con conferma di ricezione. In assenza di rete, nessun dato va perso.
3. **Integrità SHA-256**: Ogni payload estratto dalla FRAM viene firmato con un digest SHA-256 integrando un Unique Device ID prima di essere inviato via mTLS REST API.
4. **Effetto Stufa Interno & Sensoristica**:
* **DHT22**: Montato esternamente al box per la misura dell'umidità relativa (RH) ambientale reale.
* **Telemetry Interna**: Monitorata via chip ESP32 e RTC DS3231 per diagnostica termica dello chassis.
* **Bus Gas/Ambiente**: Array MQ-2, MQ-135, sensori di fiamma e NDIR CO2.



---

## Struttura del Monorepo

```text
sentinel/
├── firmware/              # [C++] Codice sorgente ESP32 (PlatformIO)
│   ├── include/           # Header e definizioni dell'hardware
│   ├── src/               # Main loop e logica di acquisizione (main.ino)
│   ├── generate_secrets.py# Iniezione credenziali cifrate
│   ├── env_example        # Template variabili d'ambiente (.env)
│   ├── platformio.ini     # Configurazione PlatformIO
│   └── Makefile           # Automazione build, flash e deploy locale
│
├── server/                # [Python] Backend Server (Flask)
│   ├── app.py             # Logica REST API, Ingest, OTA e Dashboard UI
│   ├── requirements.txt   # Dipendenze Python
│   └── firmware_builds/   # Directory binari per OTA (ignorata da Git)
│
└── README.md              # Documentazione principale del progetto

```

---

## Configurazione & Avvio Rapido

### 1. Firmware ESP32 (C++)

Entra nella cartella del firmware per compilare e flashare la scheda:

```bash
cd firmware

# Copia il file delle variabili d'ambiente e imposta i parametri
cp env_example .env

# Genera i secret e compila il firmware
make

# Flash del firmware sulla scheda ESP32 via USB
make flash

# Upload del file system / partizioni
make uploadfs

```

### 2. Server Backend (Python)

Entra nella cartella del server per avviare il backend Flask:

```bash
cd server

# Installa le dipendenze Python necessarie
pip install -r requirements.txt

# Avvia il server
python3 app.py

```

La dashboard sarà disponibile all'indirizzo `http://localhost:5040`.

---

## Pipeline di Release (`make deploy`)

Dalla directory `firmware/`, lanciando il comando `make deploy` si attiva lo script di sincronizzazione atomica:

1. **Sviluppo Privato (`master`)**: Salva lo storico dei commit e mantiene il file `.env` al sicuro nel repository privato.
2. **Release Pubblica Monorepo (`master` pubblico)**: Assembla in maniera automatica le due componenti (`firmware` e `server`), rimuove i file `.env` e gli script locali di gestione, e aggiorna la radice del repository pubblico unificato.

