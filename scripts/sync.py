"""
scripts/sync.py — Sincroniza datos y modelos entre Drive y /content.

Regla de oro de Colab: /content se borra al reiniciar el runtime. Por eso:
  - los DATOS viven en Drive y se copian a /content al iniciar (lectura rápida)
  - los MODELOS (best.pt) se copian de vuelta a Drive apenas termina cada paso

Uso:
    python scripts/sync.py pull-data     # Drive -> /content (antes de entrenar)
    python scripts/sync.py push-models   # /content -> Drive (al terminar)

Ajusta DRIVE_ROOT a tu ruta real en Drive.
"""
import shutil
import sys
from pathlib import Path

DRIVE_ROOT = Path("/content/drive/MyDrive/ramec")
LOCAL_ROOT = Path("/content/ramec")


def _copytree(src: Path, dst: Path):
    if not src.exists():
        print(f"  (omitido, no existe: {src})")
        return
    dst.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dst, dirs_exist_ok=True)
    print(f"  {src} -> {dst}")


def pull_data():
    print("Drive -> /content (datos)")
    for sub in ("data/planos", "data/documentos", "base"):
        _copytree(DRIVE_ROOT / sub, LOCAL_ROOT / sub)


def push_models():
    print("/content -> Drive (modelos)")
    for sub in ("models/planos", "models/documentos"):
        _copytree(LOCAL_ROOT / sub, DRIVE_ROOT / sub)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "pull-data":
        pull_data()
    elif cmd == "push-models":
        push_models()
    else:
        print(__doc__)
