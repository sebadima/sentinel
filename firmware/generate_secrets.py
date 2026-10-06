#!/usr/bin/env python3
import os

env_file = ".env"
header_file = "src/secrets.h"

print("🔐 Generando secrets.h da .env...")

with open(env_file, "r", encoding="utf-8") as f:
    env = {}
    for line in f:
        line = line.strip()
        if line and not line.startswith("#"):
            key, value = line.split("=", 1)
            env[key.strip()] = value.strip()

with open(header_file, "w", encoding="utf-8") as f:
    f.write("// === AUTO-GENERATED FROM .env - NON MODIFICARE MANUALMENTE ===\n")
    f.write("#pragma once\n\n")
    
    for key, value in env.items():
        # Se è un numero lo lasciamo senza virgolette, altrimenti lo mettiamo come stringa
        if value.replace(".", "").replace("-", "").isdigit() or value.startswith("http"):
            f.write(f'#define {key} "{value}"\n')
        else:
            f.write(f'#define {key} "{value}"\n')

print(f"✅ {header_file} generato con successo!")
