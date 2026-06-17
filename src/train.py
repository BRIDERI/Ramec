"""
Paso 2 - Entrenamiento de los dos modelos YOLO (Opción A, nc=23).

  - planos:     imgsz alto (1536; subir a 2048 si el recall del codigo flojea).
  - documentos: imgsz normal (1280); las clases ocupan fracciones grandes de la página.

Detalle clave de augmentation para detección de LAYOUT:
  - SIN flips (fliplr/flipud=0): voltear espejaría el texto y rompería la
    semántica de posición (el codigo va abajo-derecha del rótulo, las clases de
    carátula arriba, etc.).
  - SIN rotación/shear/perspective: los escaneos están alineados a ejes.
  - PLANOS sin mosaic: mosaic mete 4 imágenes en una y reduce a la mitad el
    tamaño de los objetos -> empeora justo el codigo, que ya es chico. En planos
    lo desactivamos y dejamos solo scale/translate/hsv suaves.
  - DOCUMENTOS sí usa mosaic: ahí los objetos son grandes y ayuda con el dataset chico.

Modelo: por defecto yolo11m.pt (estable). Para planos vale la pena probar
yolo26m.pt (--model yolo26m.pt): trae Small-Target-Aware Label Assignment,
pensado para objetos pequeños como el codigo.

Guarda best.pt en models/<task>/ y sincroniza a Drive al terminar.

Uso:
    python src/train.py --task planos
    python src/train.py --task documentos
    python src/train.py --task both --model yolo26m.pt --epochs 200
"""
import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Config por task. Los augment overrides son los explicados arriba.
TASK_CFG = {
    "planos": {
        "data": str(ROOT / "configs" / "planos.yaml"),
        "imgsz": 1536,      # subir a 2048 si el codigo se queda corto
        "batch": 8,
        "aug": dict(
            mosaic=0.0,     # clave: no encoger el codigo
            fliplr=0.0, flipud=0.0,
            degrees=0.0, shear=0.0, perspective=0.0,
            scale=0.2, translate=0.1,
            hsv_h=0.015, hsv_s=0.4, hsv_v=0.4,
        ),
    },
    "documentos": {
        "data": str(ROOT / "configs" / "documentos.yaml"),
        "imgsz": 1280,
        "batch": 16,
        "aug": dict(
            mosaic=1.0, close_mosaic=10,
            fliplr=0.0, flipud=0.0,
            degrees=0.0, shear=0.0, perspective=0.0,
            scale=0.3, translate=0.1,
            hsv_h=0.015, hsv_s=0.4, hsv_v=0.4,
        ),
    },
}


def train_one(task, args):
    from ultralytics import YOLO

    cfg = TASK_CFG[task]
    imgsz = args.imgsz or cfg["imgsz"]
    batch = args.batch if args.batch is not None else cfg["batch"]

    print(f"\n===== Entrenando {task} | modelo={args.model} imgsz={imgsz} batch={batch} =====")
    model = YOLO(args.model)
    results = model.train(
        data=cfg["data"],
        imgsz=imgsz,
        epochs=args.epochs,
        batch=batch,
        patience=args.patience,
        device=args.device,
        project=str(ROOT / "runs"),
        name=task,
        exist_ok=True,
        pretrained=True,
        seed=args.seed,
        **cfg["aug"],
    )

    # localizar best.pt y copiarlo a models/<task>/
    best = Path(results.save_dir) / "weights" / "best.pt"
    dst_dir = ROOT / "models" / task
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / "best.pt"
    if best.exists():
        shutil.copy2(best, dst)
        print(f"  best.pt -> {dst}")
    else:
        print(f"  ATENCIÓN: no se encontró {best}")
    return dst


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", choices=["planos", "documentos", "both"], default="both")
    ap.add_argument("--model", default="yolo11m.pt",
                    help="yolo11m.pt (estable) | yolo26m.pt (small-target, recomendado probar en planos)")
    ap.add_argument("--epochs", type=int, default=150)
    ap.add_argument("--imgsz", type=int, default=None, help="override del imgsz por task")
    ap.add_argument("--batch", type=int, default=None, help="override; -1 = auto-batch")
    ap.add_argument("--patience", type=int, default=40)
    ap.add_argument("--device", default=0)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--no-sync", action="store_true", help="no sincronizar a Drive al terminar")
    args = ap.parse_args()

    tasks = ["planos", "documentos"] if args.task == "both" else [args.task]
    for t in tasks:
        train_one(t, args)

    if not args.no_sync:
        sync = ROOT / "scripts" / "sync.py"
        if sync.exists():
            print("\nSincronizando modelos a Drive...")
            subprocess.run([sys.executable, str(sync), "push-models"], check=False)


if __name__ == "__main__":
    main()
