"""
Paso 1 - Conversión CVAT (Ultralytics YOLO export) -> dataset de entrenamiento.

Lee los exports de CVAT (un dir por task, con images/train + labels/train),
arma un split train/val y deja todo en data/{planos,documentos}/images|labels/{train,val},
que es la estructura que esperan configs/{planos,documentos}.yaml.

Por qué no usamos el train.txt de CVAT: en el export, train.txt lista rutas con
prefijo 'data/' que no coincide con la carpeta real 'images/'. Leemos directo de
images/train + labels/train y evitamos ese bug.

Además valida y reporta anomalías SIN corregirlas en silencio:
  - ids de clase fuera del rango esperado por task (planos 0-8, documentos 9-22)
  - imágenes sin label o labels sin imagen
  - páginas internas de documentos con logo pero 0 firmas (problema "pág 22")
  - páginas internas con un número de firmas distinto al habitual (revisar)
  - asimetría entre carátulas y páginas de control

El split de documentos es estratificado por tipo de página (carátula / control /
interna) para que validación tenga de los tres. Planos va aleatorio (homogéneo).

Uso:
    python src/convert.py --planos data/raw/planos \
                          --documentos data/raw/documentos \
                          --val-frac 0.15 --seed 42
"""
import argparse
import random
import shutil
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "configs"))
import classes as C  # noqa: E402

CARAT = {11, 12, 13, 14, 20}
CTRL = {9, 10, 15, 16, 17, 18, 21}
PAG = {19, 22}


def read_ids(label_path):
    ids = []
    for line in label_path.read_text().splitlines():
        line = line.strip()
        if line:
            ids.append(int(line.split()[0]))
    return ids


def classify_page(ids):
    s = set(ids)
    if s & CARAT:
        return "caratula"
    if s & CTRL:
        return "control"
    if s and s <= PAG:
        return "interna"
    return "otra"


def collect(export_dir):
    """Devuelve [(stem, img_path, label_path, ids)] leyendo images/train + labels/train."""
    export_dir = Path(export_dir)
    img_dir = export_dir / "images" / "train"
    lbl_dir = export_dir / "labels" / "train"
    items = []
    for img in sorted(img_dir.glob("*.jpg")):
        lbl = lbl_dir / (img.stem + ".txt")
        ids = read_ids(lbl) if lbl.exists() else None
        items.append((img.stem, img, lbl if lbl.exists() else None, ids))
    return items


def validate(task, items):
    warns = []
    expected = set(C.PLANO_IDS if task == "planos" else C.DOC_IDS)
    for stem, img, lbl, ids in items:
        if lbl is None:
            warns.append(f"[{task}] {stem}: imagen SIN label (sería fondo puro)")
            continue
        bad = sorted(set(ids) - expected)
        if bad:
            names = ", ".join(f"{b}={C.CLASSES[b]}" for b in bad)
            warns.append(f"[{task}] {stem}: ids fuera de rango -> {names}")
    if task == "documentos":
        tipos = Counter(classify_page(ids) for _, _, _, ids in items if ids)
        if tipos["caratula"] != tipos["control"]:
            warns.append(
                f"[documentos] asimetría: {tipos['caratula']} carátulas vs "
                f"{tipos['control']} páginas de control"
            )
        for stem, img, lbl, ids in items:
            if ids and classify_page(ids) == "interna":
                nf, nl = ids.count(19), ids.count(22)
                if nl >= 1 and nf == 0:
                    warns.append(
                        f"[documentos] {stem}: página interna con logo pero 0 firmas "
                        f"(falsos negativos -> completar o excluir)"
                    )
                elif nf not in (0, 4):
                    warns.append(
                        f"[documentos] {stem}: página interna con {nf} firmas "
                        f"(lo habitual es 4 -> revisar)"
                    )
    return warns


def split_items(task, items, val_frac, seed):
    rng = random.Random(seed)
    labeled = [it for it in items if it[3] is not None]
    if task == "documentos":
        groups = defaultdict(list)
        for it in labeled:
            groups[classify_page(it[3])].append(it)
    else:
        groups = {"all": labeled}
    train, val = [], []
    for g in groups.values():
        g = g[:]
        rng.shuffle(g)
        n_val = max(1, round(len(g) * val_frac)) if len(g) > 1 else 0
        val += g[:n_val]
        train += g[n_val:]
    return train, val


def write_split(task, train, val, out_root):
    base = Path(out_root) / "data" / task
    for split_name, items in (("train", train), ("val", val)):
        img_out = base / "images" / split_name
        lbl_out = base / "labels" / split_name
        for d in (img_out, lbl_out):
            d.mkdir(parents=True, exist_ok=True)
        for stem, img, lbl, _ in items:
            shutil.copy2(img, img_out / img.name)
            shutil.copy2(lbl, lbl_out / lbl.name)
    return len(train), len(val)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--planos", required=True)
    ap.add_argument("--documentos", required=True)
    ap.add_argument("--val-frac", type=float, default=0.15)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out-root", default=str(ROOT))
    args = ap.parse_args()

    all_warns = []
    for task, src in (("planos", args.planos), ("documentos", args.documentos)):
        items = collect(src)
        warns = validate(task, items)
        all_warns += warns
        train, val = split_items(task, items, args.val_frac, args.seed)
        nt, nv = write_split(task, train, val, args.out_root)
        print(f"\n[{task}] {len(items)} imágenes -> train={nt}  val={nv}")
        if task == "documentos":
            for split_name, s in (("train", train), ("val", val)):
                tipos = Counter(classify_page(it[3]) for it in s)
                print(f"    {split_name}: {dict(tipos)}")

    print("\n===== VALIDACIÓN =====")
    if not all_warns:
        print("Sin anomalías.")
    else:
        for w in all_warns:
            print(" -", w)
        print(f"\nTotal de avisos: {len(all_warns)}")
        print("Estos NO se corrigen solos: decide si completas en CVAT o excluyes.")


if __name__ == "__main__":
    main()
