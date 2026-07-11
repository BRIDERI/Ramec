"""
Paso 3 - Orquestador. Genera el reporte integral de RAMEC a partir de una carpeta de PDFs.

Por cada PDF:
  1) nomenclatura.validar_nombre -> ESTANDAR NOMENCLATURA.
  2) PLANO: valida compatibilidad del código del rótulo.
  3) DOCUMENTO: valida carátula, hoja de control, coherencia, control de cambios
     y validación profesional.
  4) DOCUMENTO: revisa de forma complementaria sellos, firmantes, CIP y logos por página.

Uso:
    python src/infer.py --pdfs <carpeta_pdfs> --salida outputs/Reporte_validacion.xlsx
"""

import argparse
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

# Clases complementarias por página
FIRMAS_PAG = C.NAME_TO_ID.get("firmas_aprobacion_paginas")
LOGO_CARAT = C.NAME_TO_ID.get("logo_entidades_caratula")
LOGO_PAG = C.NAME_TO_ID.get("logo_entidades_paginas")

# clases de VALIDACIÓN PROFESIONAL (presencia por detección)
PROF_PLANO = ["responsables", "validacion_profesional", "entidades"]
PROF_DOC = ["validacion_profesional_hoja_control", "responsables_hoja_control",
            "firmas_aprobacion_paginas", "logo_entidades_caratula", "logo_entidades_paginas"]

# Palabras clave para deducir el tipo de documento a partir del título.
CLAVES_DOC = {
    "EST": ["estudio"], "INF": ["informe", "reporte", "memoria tecnica"],
    "MCA": ["memoria de calculo", "memoria calculo"], "MDE": ["memoria descriptiva"],
    "MEM": ["memoria"], "BAS": ["bases de diseno", "bases de diseño"],
    "ANE": ["anexo"], "ACT": ["acta"], "CRO": ["cronograma"], "CAR": ["carta", "oficio"],
}

DPI_DOC = 300
DPI_PLANO = 360
DPI_PAGINAS = 220
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


def render_page(pdf_path, page_num, dpi):
    from pdf2image import convert_from_path
    pages = convert_from_path(str(pdf_path), dpi=dpi, first_page=page_num, last_page=page_num)
    return pages[0] if pages else None


def best_boxes(result):
    """{cls_id: (xywhn_tuple, conf)} quedándose con la caja de mayor confianza por clase."""
    out = {}
    if result.boxes is None:
        return out
    for box in result.boxes:
        cid = int(box.cls[0]) if hasattr(box.cls, "__len__") else int(box.cls)
        conf = float(box.conf[0]) if hasattr(box.conf, "__len__") else float(box.conf)
        xywhn = tuple(box.xywhn[0].tolist())
        if cid not in out or conf > out[cid][1]:
            out[cid] = (xywhn, conf)
    return out


def tipo_pagina_documento(page_num):
    if page_num == 1:
        return "Carátula"
    if page_num == 2:
        return "Hoja de control"
    return "Contenido"


def procesar_plano(model, pdf_path, expected):
    pages = render_pages(pdf_path, DPI_PLANO, first=1, last=1)
    if not pages:
        return "", False, set()
    img = pages[0]
    # conf bajo: el codigo es un objeto pequeño, priorizamos recall.
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


def procesar_paginas_complementarias(model, pdf_path, max_pages=None, out_dir=None):
    """Detecta y lee logos/sellos por página para un DOCUMENTO.

    Devuelve tres listas de filas:
      - VALIDACION_FINAL_PAGINAS
      - DETALLE_SELLOS_PAGINAS
      - DETALLE_LOGOS_PAGINAS
    """
    from pdf2image import pdfinfo_from_path

    if out_dir is None:
        out_dir = ROOT / "outputs"

    out_dir = Path(out_dir)
    out_sellos = out_dir / "validacion_paginas_sellos"
    out_logos = out_dir / "validacion_paginas_logos"
    out_sellos.mkdir(parents=True, exist_ok=True)
    out_logos.mkdir(parents=True, exist_ok=True)

    info = pdfinfo_from_path(str(pdf_path))
    total_pages = int(info.get("Pages", 0))
    if max_pages is not None:
        total_pages = min(total_pages, int(max_pages))

    rows_pagina = []
    rows_sellos = []
    rows_logos = []

    clases_sello = {FIRMAS_PAG} if FIRMAS_PAG is not None else set()
    clases_logo = {c for c in (LOGO_CARAT, LOGO_PAG) if c is not None}

    for page_num in range(1, total_pages + 1):
        tipo_pagina = tipo_pagina_documento(page_num)
        img = render_page(pdf_path, page_num, DPI_PAGINAS)
        if img is None:
            continue
        if img.mode != "RGB":
            img = img.convert("RGB")

        res = model.predict(img, imgsz=1280, conf=0.25, verbose=False)[0]

        sellos_pagina = []
        logos_pagina = []

        if res.boxes is not None:
            for box in res.boxes:
                cid = int(box.cls[0]) if hasattr(box.cls, "__len__") else int(box.cls)
                conf = float(box.conf[0]) if hasattr(box.conf, "__len__") else float(box.conf)
                xyxy = tuple(box.xyxy[0].tolist())

                if cid in clases_sello:
                    crop = EX.recortar_xyxy(img, xyxy)
                    sellos_pagina.append((cid, conf, crop))

                if cid in clases_logo:
                    xyxy_exp = EX.expandir_xyxy(xyxy, img.size, margen=100)
                    crop = EX.recortar_xyxy(img, xyxy_exp)
                    logos_pagina.append((cid, conf, crop))

        firmantes = []
        cargos = []
        cips = []
        max_conf_sello = ""

        for i, (cid, conf, crop) in enumerate(sellos_pagina, start=1):
            max_conf_sello = max(float(max_conf_sello or 0), conf)

            crop_name = f"{pdf_path.stem}_pag_{page_num:03d}_sello_{i}.png"
            crop_path = out_sellos / crop_name
            try:
                crop.save(crop_path)
            except Exception:
                crop_path = ""

            texto, rot, psm = EX.ocr_mejor_rotacion(crop, tipo="sello")
            nombre, cargo, cip = EX.extraer_datos_sello(texto)

            if nombre and nombre not in firmantes:
                firmantes.append(nombre)
            if cargo and cargo not in cargos:
                cargos.append(cargo)
            if cip and cip not in cips:
                cips.append(cip)

            rows_sellos.append({
                "Archivo": pdf_path.name,
                "Página": page_num,
                "Tipo_página": tipo_pagina,
                "Sello_detectado": "Sí",
                "Firmante_detectado": nombre,
                "Cargo_detectado": cargo,
                "CIP_detectado": cip,
                "Confianza_sello": round(conf, 3),
                "Rotación_OCR": rot,
                "PSM_OCR": psm,
                "Texto_OCR_sello": texto,
                "Recorte_sello": str(crop_path),
            })

        if not sellos_pagina:
            rows_sellos.append({
                "Archivo": pdf_path.name,
                "Página": page_num,
                "Tipo_página": tipo_pagina,
                "Sello_detectado": "No",
                "Firmante_detectado": "",
                "Cargo_detectado": "",
                "CIP_detectado": "",
                "Confianza_sello": "",
                "Rotación_OCR": "",
                "PSM_OCR": "",
                "Texto_OCR_sello": "",
                "Recorte_sello": "",
            })

        entidades = []
        texto_logos = []
        max_conf_logo = ""

        for i, (cid, conf, crop) in enumerate(logos_pagina, start=1):
            max_conf_logo = max(float(max_conf_logo or 0), conf)

            crop_name = f"{pdf_path.stem}_pag_{page_num:03d}_logo_{i}.png"
            crop_path = out_logos / crop_name
            try:
                crop.save(crop_path)
            except Exception:
                crop_path = ""

            texto_logo, rot_logo, psm_logo = EX.ocr_mejor_rotacion(crop, tipo="logo")
            entidades_logo = EX.identificar_entidades_logo(texto_logo)

            for ent in entidades_logo.split("|"):
                ent = ent.strip()
                if ent and ent not in entidades:
                    entidades.append(ent)

            if texto_logo:
                texto_logos.append(EX.limpiar_lineal(texto_logo))

            rows_logos.append({
                "Archivo": pdf_path.name,
                "Página": page_num,
                "Tipo_página": tipo_pagina,
                "Logo_detectado": "Sí",
                "Clase_logo": C.CLASSES[cid] if cid < len(C.CLASSES) else str(cid),
                "Entidades_detectadas": entidades_logo,
                "Confianza_logo": round(conf, 3),
                "Rotación_OCR_logo": rot_logo,
                "PSM_OCR_logo": psm_logo,
                "Texto_OCR_logo": texto_logo,
                "Recorte_logo": str(crop_path),
            })

        if not logos_pagina:
            rows_logos.append({
                "Archivo": pdf_path.name,
                "Página": page_num,
                "Tipo_página": tipo_pagina,
                "Logo_detectado": "No",
                "Clase_logo": "",
                "Entidades_detectadas": "",
                "Confianza_logo": "",
                "Rotación_OCR_logo": "",
                "PSM_OCR_logo": "",
                "Texto_OCR_logo": "",
                "Recorte_logo": "",
            })

        logo_detectado = "Sí" if logos_pagina else "No"
        sello_detectado = "Sí" if sellos_pagina else "No"

        if tipo_pagina in ["Carátula", "Hoja de control"]:
            validacion = (
                "Conforme preliminar: logo detectado; sello lateral no aplica"
                if logo_detectado == "Sí"
                else "Revisar preliminar: no se detectó logo"
            )
        else:
            if logo_detectado == "Sí" and sello_detectado == "Sí":
                validacion = "Conforme: página con logo y sello detectado"
            elif logo_detectado == "Sí" and sello_detectado == "No":
                validacion = "Revisar: página con logo, sin sello lateral detectado"
            elif logo_detectado == "No" and sello_detectado == "Sí":
                validacion = "Revisar: página con sello, sin logo detectado"
            else:
                validacion = "Revisar: página sin logo ni sello detectado"

        rows_pagina.append({
            "Archivo": pdf_path.name,
            "Página": page_num,
            "Tipo_página": tipo_pagina,
            "Logo_detectado_OCR": logo_detectado,
            "Entidades_logo_detectadas": " | ".join(entidades),
            "Confianza_logo": round(max_conf_logo, 3) if max_conf_logo != "" else "",
            "Sello_detectado": sello_detectado,
            "Cantidad_sellos_detectados": len(sellos_pagina),
            "Firmante_detectado": " | ".join(firmantes),
            "Cargo_detectado": " | ".join(cargos),
            "CIP_detectado": " | ".join(cips),
            "Confianza_sello": round(max_conf_sello, 3) if max_conf_sello != "" else "",
            "Validación_final_página": validacion,
            "Texto_logo_extraido": " | ".join(texto_logos),
        })

    return rows_pagina, rows_sellos, rows_logos


def _parse_max_pages(value):
    if value is None:
        return None
    value = str(value).strip()
    if value.lower() in ("none", "todo", "all", ""):
        return None
    return int(value)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdfs", required=True, help="carpeta con los PDFs a revisar")
    ap.add_argument("--salida", default=str(ROOT / "outputs" / "Reporte_validacion_AVP.xlsx"))
    ap.add_argument("--base", default=str(ROOT / "base" / "base.json"))
    ap.add_argument("--model-planos", default=str(ROOT / "models" / "planos" / "best.pt"))
    ap.add_argument("--model-doc", default=str(ROOT / "models" / "documentos" / "best.pt"))
    ap.add_argument("--entidad-esperada", default="PROINVERSIÓN",
                    help="Entidad esperada para VALIDACION_LOGOS. Ej.: PROINVERSIÓN")
    ap.add_argument("--max-pages-paginas", default="None",
                    help="Páginas a procesar en validación complementaria. Use 10 para prueba o None para todo.")
    ap.add_argument("--sin-validacion-paginas", action="store_true",
                    help="Desactiva la validación complementaria de sellos/logos por página.")
    args = ap.parse_args()

    from ultralytics import YOLO

    sets_validos, doc_tipo_map = NM.load_base(args.base)
    model_planos = YOLO(args.model_planos)
    model_doc = YOLO(args.model_doc)

    estandar, comp_plano, comp_doc, coherencia, control, validacion = [], [], [], [], [], []
    paginas, detalle_sellos, detalle_logos = [], [], []

    max_pages_paginas = _parse_max_pages(args.max_pages_paginas)
    out_dir = Path(args.salida).parent

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

            if not args.sin_validacion_paginas:
                print(f"  validación complementaria por página: {p.name}")
                rows_p, rows_s, rows_l = procesar_paginas_complementarias(
                    model_doc,
                    p,
                    max_pages=max_pages_paginas,
                    out_dir=out_dir,
                )
                paginas.extend(rows_p)
                detalle_sellos.extend(rows_s)
                detalle_logos.extend(rows_l)

    Path(args.salida).parent.mkdir(parents=True, exist_ok=True)
    RP.write_report(
        args.salida,
        estandar,
        comp_plano,
        comp_doc,
        coherencia,
        control,
        validacion,
        paginas=paginas,
        detalle_sellos=detalle_sellos,
        detalle_logos=detalle_logos,
        entidad_esperada=args.entidad_esperada,
    )

    print(f"Listo: {args.salida}")
    print(f"  planos={len(comp_plano)} documentos={len(comp_doc)} "
          f"validacion_profesional={len(validacion)} filas estandar={len(estandar)} "
          f"paginas={len(paginas)}")


if __name__ == "__main__":
    main()
