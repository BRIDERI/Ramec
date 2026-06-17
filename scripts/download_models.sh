#!/usr/bin/env bash
#
# Descarga los pesos entrenados de YOLO11-M (planos y documentos) desde el
# GitHub Release y los coloca en models/<task>/best.pt
#
# Uso:
#   REPO=tuusuario/ramec TAG=v1.0 bash scripts/download_models.sh
#
# o edita los valores por defecto de abajo y ejecuta:  bash scripts/download_models.sh
#
set -euo pipefail

REPO="${REPO:-tuusuario/ramec}"   # <-- cambia por tu usuario/repositorio
TAG="${TAG:-v1.0}"                # <-- etiqueta del Release con los pesos
BASE="https://github.com/${REPO}/releases/download/${TAG}"

command -v curl >/dev/null 2>&1 || { echo "ERROR: se necesita 'curl'."; exit 1; }

mkdir -p models/planos models/documentos

echo "Descargando pesos desde ${BASE} ..."
curl -fL --retry 3 -o models/planos/best.pt      "${BASE}/planos-best.pt"
curl -fL --retry 3 -o models/documentos/best.pt  "${BASE}/documentos-best.pt"

echo "Listo. Pesos descargados:"
ls -lh models/planos/best.pt models/documentos/best.pt
