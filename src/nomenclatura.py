"""
Pestaña ESTANDAR NOMENCLATURA - validación del nombre del archivo. Sin modelo.

Portado de producción (validar_nombre / clasificar_por_documento), pero los
catálogos y el doc_tipo_map se cargan desde base/base.json en vez del Excel
maestro (base.json se genera aparte con scripts/build_base.py).
"""
import json
import re
from pathlib import Path

DOC_EXTS = {"PDF", "DOC", "DOCX", "XLS", "XLSX", "PPT", "PPTX"}
PLANO_EXTS = {"PDF", "DWG", "ZIP", "MPK"}
MODEL_EXTS = {"RVT", "IFC", "NWC", "NWD", "DWG"}
EXT_TOKEN_EQUIV = {"C3D": "DWG", "RVT": "RVT", "IFC": "IFC", "NWC": "NWC", "NWD": "NWD"}
DOC_RE_NUM = re.compile(r"^\d{6,14}$")


def load_base(base_path):
    """Devuelve (sets_validos, doc_tipo_map) desde base.json."""
    data = json.loads(Path(base_path).read_text(encoding="utf-8"))
    cat = data.get("catalogos", {})
    sets_validos = {k: set(str(v).strip().upper() for v in lst) for k, lst in cat.items()}
    doc_tipo_map = {k: v for k, v in data.get("doc_tipo_map", {}).items()
                    if not k.startswith("_")}
    return sets_validos, doc_tipo_map


def clasificar_por_documento(tokens, doc_tipo_map):
    for idx in (3, 4):
        if len(tokens) > idx:
            d = tokens[idx]
            if d in doc_tipo_map:
                return doc_tipo_map[d]
            if d in {"M3D", "MFD", "MDF"}:
                return "MODELO3D"
            if d in {"M2D", "DRW"}:
                return "PLANO"
    return "DOCUMENTO"


def validar_nombre(path, sets_validos, doc_tipo_map):
    path = Path(path)
    ext_real = path.suffix[1:].upper() if path.suffix else ""
    tokens = [t.strip().upper() for t in path.stem.split("-") if t.strip()]
    n = len(tokens)
    errores = []
    catalogo_ok = True
    tipo = clasificar_por_documento(tokens, doc_tipo_map)
    campos = {k: "" for k in ("EXPEDIENTE", "ORIGINADOR", "DIVISION", "FASE",
                              "DOCUMENTO", "DISCIPLINA", "AREA", "NUMDOC", "EXT_token")}
    campos["EXT_real"] = ext_real

    if tipo == "DOCUMENTO":
        orden_ok = (n == 8)
        if not orden_ok:
            errores.append(f"Estructura DOCUMENTO requiere 8 partes, hallado {n}")
        else:
            (campos["EXPEDIENTE"], campos["ORIGINADOR"], campos["DIVISION"], campos["FASE"],
             campos["DOCUMENTO"], campos["DISCIPLINA"], campos["AREA"], campos["NUMDOC"]) = tokens
    elif tipo == "PLANO":
        orden_ok = (n == 7)
        if not orden_ok:
            errores.append(f"Estructura PLANO requiere 7 partes, hallado {n}")
        else:
            (campos["EXPEDIENTE"], campos["DIVISION"], campos["FASE"], campos["DOCUMENTO"],
             campos["DISCIPLINA"], campos["AREA"], campos["NUMDOC"]) = tokens
    else:
        orden_ok = (n >= 7)
        if not orden_ok:
            errores.append(f"Estructura MODELO3D requiere >=7 partes, hallado {n}")
        else:
            (campos["EXPEDIENTE"], campos["DIVISION"], campos["FASE"], campos["DOCUMENTO"],
             campos["DISCIPLINA"], campos["AREA"], campos["NUMDOC"]) = tokens[:7]
            campos["EXT_token"] = tokens[7] if n >= 8 else ""

    def check(campo, grupo):
        nonlocal catalogo_ok
        if campos[campo] and sets_validos.get(grupo) and campos[campo] not in sets_validos[grupo]:
            errores.append(f"{campo} '{campos[campo]}' no existe en catálogo {grupo}")
            catalogo_ok = False

    if orden_ok:
        check("EXPEDIENTE", "EXPEDIENTE")
        if tipo == "DOCUMENTO":
            check("ORIGINADOR", "ORIGINADOR")
        for c, g in [("DIVISION", "DIVISION"), ("FASE", "FASE"), ("DOCUMENTO", "DOCUMENTO"),
                     ("DISCIPLINA", "DISCIPLINA"), ("AREA", "AREA")]:
            check(c, g)
        if campos["NUMDOC"]:
            if not DOC_RE_NUM.fullmatch(campos["NUMDOC"]):
                errores.append(f"NUMDOC '{campos['NUMDOC']}' inválido (6-14 dígitos)")
                catalogo_ok = False
        else:
            errores.append("NUMDOC vacío")
            catalogo_ok = False

    if tipo == "DOCUMENTO" and ext_real not in DOC_EXTS:
        errores.append(f"Extensión '.{ext_real.lower()}' no válida para DOCUMENTO")
        catalogo_ok = False
    if tipo == "PLANO" and ext_real not in PLANO_EXTS:
        errores.append(f"Extensión '.{ext_real.lower()}' no válida para PLANO")
        catalogo_ok = False
    if tipo == "MODELO3D":
        if campos["EXT_token"]:
            esperado = EXT_TOKEN_EQUIV.get(campos["EXT_token"], campos["EXT_token"])
            if ext_real != esperado:
                errores.append(f"EXT_token '{campos['EXT_token']}' != real '.{ext_real.lower()}'")
                catalogo_ok = False
        if ext_real not in MODEL_EXTS:
            errores.append(f"Extensión '.{ext_real.lower()}' no válida para MODELO3D")
            catalogo_ok = False

    return tipo, campos, orden_ok, catalogo_ok, " | ".join(errores)
