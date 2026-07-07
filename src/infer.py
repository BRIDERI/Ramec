"""
Paso 3 - Orquestador. Genera el reporte de 5 pestañas a partir de una carpeta de PDFs.

Por cada PDF:
  1) nomenclatura.validar_nombre -> fila ESTANDAR NOMENCLATURA + tipo (PLANO/DOCUMENTO/...)
  2) PLANO: renderiza, corre el modelo de planos, ubica la caja 'codigo' (id 1),
     OCR dentro -> COMPATIBILIDAD_PLANO.
  3) DOCUMENTO: renderiza las primeras páginas, corre el modelo de documentos,
     clasifica cada página por las clases detectadas (carátula vs control) y lee
     los campos -> COMPATIBILIDAD_DOCUMENTO, COHERENCIA_DOCUMENTO, CONTROL_CAMBIOS_DOC.

A diferencia de producción, no se barre por zonas: el OCR lee dentro de la caja
que el modelo localizó, sobre el render full-res.

Uso:
    python src/infer.py --pdfs <carpeta_pdfs> --salida outputs/Reporte_validacion_AVP.xlsx
"""
import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "configs"))

import classes as C            # noqa: E402
import nomenclatura as NM      # noqa: E402
import extract as EX           # noqa: E402
import report as RP            # noqa: E402

# ids de las clases load-bearing
COD_PLANO = C.NAME_TO_ID["codigo"]                          # 1
NUM_CARAT = C.NAME_TO_ID["num_documento_caratula"]          # 13
TIT_CARAT = C.NAME_TO_ID["titulo_documento_caratula"]       # 12
FEC_CARAT = C.NAME_TO_ID["fecha_caratula"]                  # 14
NUM_CTRL = C.NAME_TO_ID["num_documento_hoja_control"]       # 15
TIT_CTRL = C.NAME_TO_ID["titulo_documento_hoja_control"]    # 16
FEC_CTRL = C.NAME_TO_ID["fecha_ultima_revision_hoja_control"]  # 10
VAL_CTRL = C.NAME_TO_ID["validacion_profesional_hoja_control"]  # 9
FEC_APROB = C.NAME_TO_ID["fecha_aprobacion_hoja_control"]      # 17
RESP_CTRL = C.NAME_TO_ID["responsables_hoja_control"]          # 18

# clases de VALIDACIÓN PROFESIONAL (presencia por detección)
PROF_PLANO = ["responsables", "validacion_profesional", "entidades"]
PROF_DOC = ["validacion_profesional_hoja_control", "responsables_hoja_control",
            "firmas_aprobacion_paginas", "logo_entidades_caratula", "logo_entidades_paginas"]

# Palabras clave para deducir el tipo de documento a partir del título (subset de
# producción; se puede enriquecer desde base.json -> claves_documento).
CLAVES_DOC = {
    "EST": ["estudio"], "INF": ["informe", "reporte", "memoria tecnica"],
    "MCA": ["memoria de calculo", "memoria calculo"], "MDE": ["memoria descriptiva"],
    "MEM": ["memoria"], "BAS": ["bases de diseno", "bases de diseño"],
    "ANE": ["anexo"], "ACT": ["acta"], "CRO": ["cronograma"], "CAR": ["carta", "oficio"],
}

DPI_DOC = 300
DPI_PLANO = 360
PAGS_DOC_A_REVISAR = 5  # busca carátula/control entre las primeras N páginas


def tipo_por_titulo(titulo):
    t = EX._strip_accents((titulo or "").lower())
    best, best_len = "DESCONOCIDO", 0
    for cod, kws in CLAVES_DOC.items():
        for kw in kws:
            if kw in t and len(kw) > best_len:
                best, best_len = cod, len(kw)
    return best


def render_pages(pdf_path, dpi, first=1, last=None):
    from pdf2image import convert_from_path
    return convert_from_path(str(pdf_path), dpi=dpi, first_page=first, last_page=last)


def best_boxes(result):
    """{cls_id: (xywhn_tuple, conf)} quedándose con la caja de mayor confianza por clase."""
    out = {}
    if result.boxes is None:
        return out
    for box in result.boxes:
        cid = int(box.cls)
        conf = float(box.conf)
        xywhn = tuple(box.xywhn[0].tolist())
        if cid not in out or conf > out[cid][1]:
            out[cid] = (xywhn, conf)
    return out


def procesar_plano(model, pdf_path, expected):
    pages = render_pages(pdf_path, DPI_PLANO, first=1, last=1)
    if not pages:
        return "", False, set()
    img = pages[0]
    # conf bajo: el codigo es un objeto pequeño, priorizamos recall (luego el OCR
    # + reconciliación filtran). Sube/baja según falsos positivos.
    res = model.predict(img, imgsz=1536, conf=0.15, verbose=False)[0]
    boxes = best_boxes(res)
    det_nombres = {C.CLASSES[c] for c in boxes}
    if COD_PLANO not in boxes:
        return "", False, det_nombres
    crop = EX.crop_box(img, boxes[COD_PLANO][0])
    code, coincide = EX.leer_codigo_plano(crop, expected)
    return code, coincide, det_nombres


def procesar_documento(model, pdf_path):
    """Devuelve dict con los campos de carátula y de control de cambios."""
    pages = render_pages(pdf_path, DPI_DOC, first=1, last=PAGS_DOC_A_REVISAR)
    caratula = None  # (img, boxes)
    control = None
    prof = set()     # nombres de clases de validación profesional vistas en cualquier página
    for img in pages:
        res = model.predict(img, imgsz=1280, conf=0.25, verbose=False)[0]
        boxes = best_boxes(res)
        prof |= {C.CLASSES[c] for c in boxes if C.CLASSES[c] in PROF_DOC}
        if caratula is None and (NUM_CARAT in boxes or TIT_CARAT in boxes):
            caratula = (img, boxes)
        if control is None and (NUM_CTRL in boxes or TIT_CTRL in boxes or FEC_CTRL in boxes):
            control = (img, boxes)
        # seguimos recorriendo aunque ya tengamos carátula y control: firmas y logos
        # de páginas aparecen en hojas posteriores y alimentan la validación profesional.

    f = {"nd": "", "titulo": "", "fecha_caratula": "",
         "existe_ctrl": control is not None, "fecha_ctrl": "", "titulo_ctrl": "", "nodoc_ctrl": "",
         "prof": prof,
         "prof_detalle": {
             "nombres": [],
             "firmas": [],
             "filas": 3,
             "fecha_validacion": "",
             "fechas_validacion": [],
             "fecha_caratula": "",
             "fecha_ultima_revision": "",
         }}
    if caratula:
        img, boxes = caratula
        if NUM_CARAT in boxes:
            f["nd"] = EX.leer_no_doc(EX.crop_box(img, boxes[NUM_CARAT][0]))
        if TIT_CARAT in boxes:
            f["titulo"] = EX.leer_titulo(EX.crop_box(img, boxes[TIT_CARAT][0]))
        if FEC_CARAT in boxes:
            f["fecha_caratula"] = EX.leer_fecha(EX.crop_box(img, boxes[FEC_CARAT][0]))
    if control:
        img, boxes = control
        if NUM_CTRL in boxes:
            f["nodoc_ctrl"] = EX.leer_no_doc(EX.crop_box(img, boxes[NUM_CTRL][0]))
        if TIT_CTRL in boxes:
            f["titulo_ctrl"] = EX.leer_titulo(EX.crop_box(img, boxes[TIT_CTRL][0]))
        if FEC_CTRL in boxes:
            f["fecha_ctrl"] = EX.leer_fecha_ultima(EX.crop_box(img, boxes[FEC_CTRL][0]))

        resp_info = {"nombres": [], "filas": 3}
        if RESP_CTRL in boxes:
            resp_crop = EX.crop_box(img, boxes[RESP_CTRL][0])
            resp_info = EX.leer_responsables_control(resp_crop)

        firma_info = {"firmas": [], "filas": resp_info.get("filas", 3)}
        if VAL_CTRL in boxes:
            firma_crop = EX.crop_box(img, boxes[VAL_CTRL][0])
            firma_info = EX.analizar_firmas_control(
                firma_crop,
                filas_esperadas=resp_info.get("filas", 3),
            )

        fechas_validacion = []
        if FEC_APROB in boxes:
            fecha_crop = EX.crop_box(img, boxes[FEC_APROB][0])
            fechas_validacion = EX.leer_fechas(fecha_crop)

        if len(fechas_validacion) == 1:
            fecha_validacion = fechas_validacion[0]
        elif fechas_validacion:
            fecha_validacion = " | ".join(fechas_validacion)
        else:
            fecha_validacion = ""

        f["prof_detalle"] = {
            "nombres": resp_info.get("nombres", []),
            "firmas": firma_info.get("firmas", []),
            "filas": max(resp_info.get("filas", 3), firma_info.get("filas", 3)),
            "fecha_validacion": fecha_validacion,
            "fechas_validacion": fechas_validacion,
            "fecha_caratula": f["fecha_caratula"],
            "fecha_ultima_revision": f["fecha_ctrl"],
        }

    return f


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdfs", required=True, help="carpeta con los PDFs a revisar")
    ap.add_argument("--salida", default=str(ROOT / "outputs" / "Reporte_validacion_AVP.xlsx"))
    ap.add_argument("--base", default=str(ROOT / "base" / "base.json"))
    ap.add_argument("--model-planos", default=str(ROOT / "models" / "planos" / "best.pt"))
    ap.add_argument("--model-doc", default=str(ROOT / "models" / "documentos" / "best.pt"))
    args = ap.parse_args()

    from ultralytics import YOLO
    sets_validos, doc_tipo_map = NM.load_base(args.base)
    model_planos = YOLO(args.model_planos)
    model_doc = YOLO(args.model_doc)

    estandar, comp_plano, comp_doc, coherencia, control, validacion = [], [], [], [], [], []

    for p in sorted(Path(args.pdfs).rglob("*")):
        if not p.is_file():
            continue
        tipo, campos, orden_ok, catalogo_ok, errores = NM.validar_nombre(p, sets_validos, doc_tipo_map)
        estandar.append(RP.fila_estandar(p, tipo, campos, orden_ok, catalogo_ok, errores))

        if p.suffix.lower() != ".pdf":
            continue
        expected = p.stem

        if tipo == "PLANO":
            code, coincide, det = procesar_plano(model_planos, p, expected)
            comp_plano.append(RP.fila_comp_plano(p, expected, code, coincide))
            pres = {n: (n in det) for n in PROF_PLANO}
            validacion.append(RP.fila_validacion_profesional(p, tipo, pres))

        elif tipo == "DOCUMENTO":
            f = procesar_documento(model_doc, p)
            comp_doc.append(RP.fila_comp_doc(p, expected, f["nd"]))
            tipo_texto = tipo_por_titulo(f["titulo"])
            coherencia.append(RP.fila_coherencia(p, f["titulo"], f["nd"], campos["DOCUMENTO"], tipo_texto))
            control.append(RP.fila_control_cambios(
                p, f["existe_ctrl"], f["fecha_caratula"], f["fecha_ctrl"],
                f["titulo"], f["titulo_ctrl"], f["nd"], f["nodoc_ctrl"]))
            validacion.append(RP.fila_validacion_profesional(
                p, tipo, f["prof_detalle"]))

    Path(args.salida).parent.mkdir(parents=True, exist_ok=True)
    RP.write_report(args.salida, estandar, comp_plano, comp_doc, coherencia, control, validacion)
    print(f"Listo: {args.salida}")
    print(f"  planos={len(comp_plano)} documentos={len(comp_doc)} "
          f"validacion_profesional={len(validacion)} filas estandar={len(estandar)}")


if __name__ == "__main__":
    main()
