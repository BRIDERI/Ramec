"""
scripts/build_base.py - Genera base/base.json desde el Excel maestro de catálogos.

Lee las 7 hojas de catálogo (EXPEDIENTE, ORIGINADOR, DIVISIÓN ESPACIAL, FASE,
DOCUMENTO, DISCIPLINA, AREA), extrae la columna de nomenclatura/código de cada
una y arma el base.json que consume nomenclatura.py. De la hoja DOCUMENTO además
deriva el doc_tipo_map (qué código es PLANO / MODELO3D / DOCUMENTO).

Maneja la inconsistencia de nombres de columna (NOMENCLATURA vs NOMECLATURA) con
el mismo buscador flexible de producción.

Uso:
    python scripts/build_base.py --excel <ruta.xlsx> --out base/base.json
"""
import argparse
import json
import re
from pathlib import Path

import pandas as pd

# sheet del Excel -> clave del catálogo en base.json
HOJAS = {
    "EXPEDIENTE": "EXPEDIENTE",
    "ORIGINADOR": "ORIGINADOR",
    "DIVISIÓN ESPACIAL": "DIVISION",
    "FASE": "FASE",
    "DOCUMENTO": "DOCUMENTO",
    "DISCIPLINA": "DISCIPLINA",
    "AREA": "AREA",
}
COD_PATTERNS = [r"NOM[E]?\w*CLATURA", r"\bNOM\b", r"\bCOD"]
TIPO_PATTERNS = [r"\bTIPO\b", r"TIPO\s*DE\s*DOCUMENTO", r"\bCLASE\b", r"\bCATEG"]


def _norm(x):
    return "" if pd.isna(x) else str(x).strip().upper()


def _find_col(df, patterns):
    for pat in patterns:
        rx = re.compile(pat, re.IGNORECASE)
        for c in df.columns:
            if rx.search(str(c).upper()):
                return c
    return None


def _norm_tipo(t):
    """Igual que producción: MOD/3D -> MODELO3D, PLANO/2D/DRW -> PLANO, resto -> DOCUMENTO."""
    t = _norm(t)
    if re.search(r"MOD|3D", t):
        return "MODELO3D"
    if re.search(r"PLANO|2D|DRW", t):
        return "PLANO"
    return "DOCUMENTO"


def build(excel_path):
    xls = pd.ExcelFile(excel_path)
    catalogos = {}
    for hoja, clave in HOJAS.items():
        if hoja not in xls.sheet_names:
            catalogos[clave] = []
            print(f"  AVISO: falta la hoja '{hoja}'")
            continue
        df = pd.read_excel(excel_path, sheet_name=hoja)
        col = _find_col(df, COD_PATTERNS) or (df.columns[0] if len(df.columns) else None)
        codigos = sorted({_norm(v) for v in df[col].dropna()} - {""}) if col is not None else []
        catalogos[clave] = codigos
        print(f"  {clave:12s} <- '{hoja}' col='{col}': {len(codigos)} códigos")

    # doc_tipo_map desde la hoja DOCUMENTO
    doc_tipo_map = {}
    df = pd.read_excel(excel_path, sheet_name="DOCUMENTO")
    col_cod = _find_col(df, COD_PATTERNS) or df.columns[0]
    col_tip = _find_col(df, TIPO_PATTERNS)
    for _, r in df.iterrows():
        cod = _norm(r.get(col_cod, ""))
        if not cod:
            continue
        tip = _norm_tipo(r.get(col_tip, "")) if col_tip else None
        if not tip:
            tip = "MODELO3D" if cod in {"M3D", "MFD", "MDF"} else \
                  "PLANO" if cod in {"M2D", "DRW"} else "DOCUMENTO"
        doc_tipo_map[cod] = tip
    for k in ("M3D", "MFD", "MDF"):
        doc_tipo_map.setdefault(k, "MODELO3D")
    n_plano = sum(1 for v in doc_tipo_map.values() if v == "PLANO")
    n_mod = sum(1 for v in doc_tipo_map.values() if v == "MODELO3D")
    print(f"  doc_tipo_map: {len(doc_tipo_map)} códigos (PLANO={n_plano}, MODELO3D={n_mod})")

    return {
        "_descripcion": f"Generado por build_base.py desde {Path(excel_path).name}",
        "catalogos": catalogos,
        "doc_tipo_map": doc_tipo_map,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--excel", required=True)
    ap.add_argument("--out", default="base/base.json")
    args = ap.parse_args()
    print(f"Leyendo {args.excel} ...")
    data = build(args.excel)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nEscrito: {args.out}")


if __name__ == "__main__":
    main()
