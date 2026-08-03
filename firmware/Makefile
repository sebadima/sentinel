# =============================================
# Makefile - Sentinel Project
# =============================================

BIN_SRC = .pio/build/esp32dev/firmware.bin
BIN_DEST_DIR = $(HOME)/sentinel_flask/firmware_builds

all:
	@python3 generate_secrets.py
	@set -a; [ -f .env ] && . ./.env; pio -f -c vim run

RPI_USER := sebadima
RPI_HOST := 192.168.1.153
RPI_DIR := ~/sentinel_flask/firmware_builds

upload:
	@python3 generate_secrets.py
	@set -a; [ -f .env ] && . ./.env; pio -f -c vim run
	@VERSION=$$(grep "const int FW_VERSION =" src/main.ino | awk '{print $$NF}' | tr -d ';'); \
	DEST_FILE=$(BIN_DEST_DIR)/sentinel_v$$VERSION.bin; \
	mkdir -p $(BIN_DEST_DIR); \
	cp $(BIN_SRC) $$DEST_FILE; \
	echo "[DEPLOY] Binario copiato in: $$DEST_FILE"; \
	rsync -avz $$DEST_FILE $(RPI_USER)@$(RPI_HOST):$(RPI_DIR)/; \
	echo "[RPI] Trasferimento remoto completato"

flash:
	@python3 generate_secrets.py
	@set -a; [ -f .env ] && . ./.env; pio -f -c vim run --target upload

uploadfs:
	@python3 generate_secrets.py
	@set -a; [ -f .env ] && . ./.env; pio -f -c vim run --target uploadfs

clean:
	pio -f -c vim run --target clean

update:
	pio -f -c vim update

feed:
	@python3 generate_secrets.py
	@python3 gemini.py

deploy:
	@chmod +x deploy_monorepo.sh
	@./deploy_monorepo.sh

.PHONY: all upload flash uploadfs clean update feed deploy