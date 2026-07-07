"""
scripts/diag_control.py - Diagnóstico de la hoja de control en la inferencia.

Para cada PDF de documento, renderiza las primeras páginas, corre el modelo y
muestra QUÉ clases se detectan en cada página (con su confianza), cuál página se
elige como carátula y cuál como control, y qué lee el OCR en las cajas clave.
Además guarda recortes de:
- fecha_ultima_revision_hoja_control
- fecha_aprobacion_hoja_control
- num_documento_hoja_control
- titulo_documento_hoja_control
- validacion_profesional_hoja_control
- responsables_hoja_control
- firmas_aprobacion_paginas
- logo_entidades_paginas

Uso:
    python scripts/diag_control.py --pdfs pdfs --model-doc models/documentos/best.pt
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "configs"))

import classes as C          # noqa: E402
import extract as EX         # noqa: E402
import nomenclatura as NM    # noqa: E402

# IDs importantes de hoja de control
FEC_ULT_CTRL = C.NAME_TO_ID["fecha_ultima_revision_hoja_control"]      # usualmente 10
NUM_CTRL = C.NAME_TO_ID["num_documento_hoja_control"]                  # usualmente 15
TIT_CTRL = C.NAME_TO_ID["titulo_documento_hoja_control"]               # usualmente 16

# Esta clase existe en tu salida del modelo. La dejamos protegida por si cambia el catálogo.
FEC_APROB_CTRL = C.NAME_TO_ID.get("fecha_aprobacion_hoja_control")

# Clases para diagnosticar validación profesional y firmas/sellos
VALID_PROF_CTRL = C.NAME_TO_ID.get("validacion_profesional_hoja_control")
RESP_CTRL = C.NAME_TO_ID.get("responsables_hoja_control")
FIRMAS_PAGS = C.NAME_TO_ID.get("firmas_aprobacion_paginas")
LOGOS_PAGS = C.NAME_TO_ID.get("logo_entidades_paginas")

DPI_DOC = 300
N_PAGS = 6


def _ocr_fecha(crop):
    """Muestra varias lecturas útiles para diagnosticar fecha."""
    vals = []
    for psm in (6, 11, 4):
        try:
            for t in EX.ocr_variants(crop, psm=psm):
                t = (t or "").strip()
                if t:
                    vals.append(f"psm{psm}: {t[:80]}")
        except Exception as e:
            vals.append(f"psm{psm}: ERROR {e}")

    # Si existe el lector final de fecha, también mostramos su resultado.
    for fn_name in ("leer_fecha_ultima", "leer_fecha"):
        fn = getattr(EX, fn_name, None)
        if fn:
            try:
                vals.append(f"{fn_name}: {fn(crop)}")
            except Exception as e:
                vals.append(f"{fn_name}: ERROR {e}")

    return vals or ["(sin texto OCR)"]


def _ocr_numdoc(crop):
    vals = []
    for psm in (6, 11, 4):
        try:
            for t in EX.ocr_variants(crop, psm=psm):
                vals.append((t or "").strip()[:100])
        except Exception as e:
            vals.append(f"ERROR psm{psm}: {e}")

    fn = getattr(EX, "leer_num_doc_control", None)
    if fn:
        try:
            vals.append(f"leer_num_doc_control: {fn(crop)}")
        except Exception as e:
            vals.append(f"leer_num_doc_control ERROR: {e}")

    return vals or ["(sin texto OCR)"]


def _ocr_titulo(crop):
    vals = []
    try:
        vals = [(t or "").strip()[:120] for t in EX.ocr_variants(crop, psm=6)]
    except Exception as e:
        vals = [f"ERROR psm6: {e}"]

    fn = getattr(EX, "leer_titulo", None)
    if fn:
        try:
            vals.append(f"leer_titulo: {fn(crop)}")
        except Exception as e:
            vals.append(f"leer_titulo ERROR: {e}")

    fn2 = getattr(EX, "limpiar_titulo_control", None)
    if fn2:
        try:
            vals.append(f"limpiar_titulo_control(leer_titulo): {fn2(getattr(EX, 'leer_titulo')(crop))}")
        except Exception:
            pass

    return vals or ["(sin texto OCR)"]


def _guardar_y_mostrar(outdir, pdf_stem, cid, nombre, crop):
    """Guarda recorte y muestra OCR según tipo de campo."""
    safe_name = nombre.replace("/", "_").replace(" ", "_")
    path = outdir / f"{pdf_stem}_{cid}_{safe_name}.png"
    crop.save(path)

    print(f"        [{cid} {nombre}] recorte guardado ({crop.size[0]}x{crop.size[1]}px) -> {path.name}")

    lname = nombre.lower()
    if "fecha" in lname:
        print(f"        [{cid} {nombre}] OCR fecha -> {_ocr_fecha(crop)}")
    elif "num_documento" in lname:
        print(f"        [{cid} {nombre}] OCR numdoc -> {_ocr_numdoc(crop)}")
    elif "titulo_documento" in lname:
        print(f"        [{cid} {nombre}] OCR titulo -> {_ocr_titulo(crop)}")
    else:
        try:
            print(f"        [{cid} {nombre}] OCR -> {[t.strip()[:80] for t in EX.ocr_variants(crop, psm=6)]}")
        except Exception as e:
            print(f"        [{cid} {nombre}] OCR ERROR -> {e}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdfs", required=True)
    ap.add_argument("--model-doc", default=str(ROOT / "models" / "documentos" / "best.pt"))
    ap.add_argument("--base", default=str(ROOT / "base" / "base.json"))
    ap.add_argument("--conf", type=float, default=0.25)
    ap.add_argument("--out-crops", default=str(ROOT / "outputs" / "diag_crops"))
    args = ap.parse_args()

    from ultralytics import YOLO
    from pdf2image import convert_from_path

    model = YOLO(args.model_doc)
    sets_validos, doc_tipo_map = NM.load_base(args.base)

    ids_a_guardar = {
        FEC_ULT_CTRL: "fecha_ultima_revision_hoja_control",
        NUM_CTRL: "num_documento_hoja_control",
        TIT_CTRL: "titulo_documento_hoja_control",
    }
    if FEC_APROB_CTRL is not None:
        ids_a_guardar[FEC_APROB_CTRL] = "fecha_aprobacion_hoja_control"

    extras = {
        VALID_PROF_CTRL: "validacion_profesional_hoja_control",
        RESP_CTRL: "responsables_hoja_control",
        FIRMAS_PAGS: "firmas_aprobacion_paginas",
        LOGOS_PAGS: "logo_entidades_paginas",
    }
    for cid, nombre in extras.items():
        if cid is not None:
            ids_a_guardar[cid] = nombre

    for p in sorted(Path(args.pdfs).rglob("*.pdf")):
        tipo, *_ = NM.validar_nombre(p, sets_validos, doc_tipo_map)
        if tipo != "DOCUMENTO":
            continue

        print("\n" + "=" * 70)
        print(p.name, f"(tipo={tipo})")

        pages = convert_from_path(str(p), dpi=DPI_DOC, first_page=1, last_page=N_PAGS)

        for i, img in enumerate(pages, 1):
            res = model.predict(img, imgsz=1280, conf=args.conf, verbose=False)[0]

            dets = {}
            best = {}

            if res.boxes is not None:
                for b in res.boxes:
                    cid = int(b.cls)
                    conf = float(b.conf)
                    dets[cid] = max(dets.get(cid, 0), conf)
                    if cid not in best or conf > best[cid][1]:
                        best[cid] = (tuple(b.xywhn[0].tolist()), conf)

            etiquetas = ", ".join(f"{C.CLASSES[c]}({dets[c]:.2f})" for c in sorted(dets))
            marca = ""
            if any(cid in dets for cid in ids_a_guardar):
                marca = "  <-- tiene clases de CONTROL"
            print(f"  pág {i}: {etiquetas or '(nada)'}{marca}")

            # Guardar recortes de fecha, numdoc, título, validación profesional, firmas y logos si están en esta página
            presentes = [cid for cid in ids_a_guardar if cid in best]
            if presentes:
                outdir = Path(args.out_crops)
                outdir.mkdir(parents=True, exist_ok=True)

                for cid in presentes:
                    crop = EX.crop_box(img, best[cid][0])
                    _guardar_y_mostrar(outdir, p.stem, cid, ids_a_guardar[cid], crop)


if __name__ == "__main__":
    main()
