# Changelog

## [932] - 2026-10-06

### Firmware

* Centralizzata la versione firmware in `version.txt`.
* `FW_VERSION` viene passato automaticamente a PlatformIO durante la compilazione.
* La versione firmware viene riportata dal dispositivo al server.
* Il controllo OTA confronta la versione installata con quella disponibile sul server.
* L'aggiornamento OTA viene eseguito solo quando è disponibile una versione superiore.

### Build

* PlatformIO `espressif32@6.13.0` bloccato.
* Dipendenze delle librerie bloccate a versioni specifiche.
* Aggiunto `merge_bin.py` per generare il firmware merged.
* Il processo di build utilizza l'esptool fornito da PlatformIO.

### Deploy

* `make upload` legge la versione direttamente da `version.txt`.
* Il firmware viene salvato con il formato:

```text
sentinel_v932.bin
```

* Il firmware viene trasferito alla Raspberry Pi tramite `rsync`.

### CI

* GitHub Actions compila automaticamente il firmware.
* La CI legge la versione direttamente da `version.txt`.
* I binari `firmware.bin` e `firmware_merged.bin` vengono salvati come artifact.

---

## Versionamento

La versione corrente è contenuta esclusivamente nel file:

```text
version.txt
```

Per una nuova versione, modificare il numero nel file e ricompilare.

Esempio:

```text
932
```

→

```text
933
```

Non inserire manualmente la versione nel `Makefile`, nel workflow GitHub Actions o nel codice C++.
