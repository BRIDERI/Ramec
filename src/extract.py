"""
Lectura de texto DENTRO de las cajas detectadas (no barrido de zonas).

Los normalizadores (_norm_code, _norm_text_cmp, _clean_code, _normalizar_fecha,
_normalizar_token_plano, _candidate_from_expected_and_ocr) están portados tal cual
del script de producción para conservar el mismo comportamiento de comparación.
La diferencia es que aquí el OCR recibe un recorte limpio (la caja que el modelo
localizó), no la página entera.
"""
import re
import unicodedata

from PIL import Image, ImageOps

try:
    import pytesseract
except Exception:  # pytesseract puede no estar al importar en tests
    pytesseract = None

# ================== PATRONES (idénticos a producción) ==================
SEP = r"[\s\-\u2010-\u2015]*"
DOC_CODE_PAT = (
    rf"AVP{SEP}[A-Z0-9]{{2,6}}{SEP}[A-Z0-9]{{1,6}}{SEP}[A-Z0-9]{{1,3}}{SEP}"
    rf"[A-Z0-9]{{2,4}}{SEP}[A-Z0-9]{{3}}{SEP}[A-Z0-9]{{3}}{SEP}\d{{5,14}}"
)
RX_DOC_CODE = re.compile(DOC_CODE_PAT, re.IGNORECASE)
PLANO_CODE_PAT = (
    rf"AVP{SEP}[A-Z0-9]{{2,6}}{SEP}D{SEP}DRW{SEP}[A-Z0-9]{{3}}{SEP}[A-Z0-9]{{3}}{SEP}\d{{6,14}}"
)
RX_PLANO_CODE = re.compile(PLANO_CODE_PAT, re.IGNORECASE)
NO_DOC_LINE_RX = re.compile(
    r"(?:NO|N[°º])\s*\.?\s*D(?:OC|O[CC])\.?\s*[:\-–]?\s*(.+)$", re.IGNORECASE | re.MULTILINE
)
MESES = {"ENERO": "01", "FEBRERO": "02", "MARZO": "03", "ABRIL": "04", "MAYO": "05",
         "JUNIO": "06", "JULIO": "07", "AGOSTO": "08", "SEPTIEMBRE": "09",
         "SETIEMBRE": "09", "OCTUBRE": "10", "NOVIEMBRE": "11", "DICIEMBRE": "12"}
RX_FECHA_DMY = re.compile(r"\b(\d{1,2})[\/\-.](\d{1,2})[\/\-.](\d{4})\b")
RX_FECHA_TEXTO = re.compile(
    r"\b(\d{1,2})\s+DE\s+(ENERO|FEBRERO|MARZO|ABRIL|MAYO|JUNIO|JULIO|AGOSTO|"
    r"SEPTIEMBRE|SETIEMBRE|OCTUBRE|NOVIEMBRE|DICIEMBRE)\s+DE\s+(\d{4})\b", re.IGNORECASE
)
TESS_WHITELIST = "-c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-"


# ================== NORMALIZADORES (portados) ==================
def _norm_code(s):
    return re.sub(r"[^A-Z0-9]", "", (s or "").upper())


def _strip_accents(s):
    return "".join(ch for ch in unicodedata.normalize("NFD", s or "")
                   if unicodedata.category(ch) != "Mn")


def _norm_text_cmp(s):
    s = _strip_accents(s or "").upper()
    s = re.sub(r"[^A-Z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


# La caja del título de la hoja de control abarca también la etiqueta de la celda
# ("Título del documento"), que el OCR garabatea de muchas formas: "Título dela",
# "tulo de! documento", "tuto ce! documento", "Título del d". La quitamos antes de
# comparar. Toleramos variantes: TITULO/TITUL.../TUTO/TULO + conector + DOCUMENTO/D.
RX_LABEL_TITULO = re.compile(
    r"\b(?:TITULO|TITUL\w*|TUTO|TULO)\s+(?:DELA|DEL\w*|DE|CE)\s+(?:DOCUMENTO|DOCUMENT\w*|DOC|D)\b"
    r"|\b(?:TITULO|TITUL\w*|TUTO|TULO)\s+(?:DELA|DEL|DE|CE)\b"
)

#Cambio
def limpiar_titulo_control(s):
    norm = _norm_text_cmp(s)

    norm = RX_LABEL_TITULO.sub(" ", norm)

    norm = re.sub(
        r"\bTITULO\s+DEL\s+DOCUMENTO\b|\bTITULO\s+DOCUMENTO\b|\bTITULO\s+DEL\s+DOC\b",
        " ",
        norm,
        flags=re.IGNORECASE
    )

    norm = re.sub(
        r"\bTITULO\b|\bDOCUMENTO\b",
        " ",
        norm,
        flags=re.IGNORECASE
    )

    return re.sub(r"\s+", " ", norm).strip()
#fin cambio


def canon_codigos(s):
    """Canoniza la ambigüedad O/0 del OCR SOLO dentro de tokens que tienen algún
    dígito (códigos embebidos): '3PLO1' -> '3PL01'. No toca palabras normales
    ('DESVIOS', 'ASTURIAS' quedan igual). Para comparar títulos con código exacto."""
    def fix(tok):
        return tok.replace("O", "0") if any(c.isdigit() for c in tok) else tok
    return " ".join(fix(t) for t in s.split())


def _clean_code(s):
    s = (s or "").upper().replace("–", "-").replace("—", "-")
    s = re.sub(r"\s*-\s*", "-", s)
    s = re.sub(r"\s{2,}", " ", s).strip()
    m = RX_DOC_CODE.search(s)
    return re.sub(r"\s+", "", m.group(0)).upper() if m else s


def _normalizar_fecha(s):
    s = _strip_accents(s or "").upper()
    m = RX_FECHA_DMY.search(s)
    if m:
        d, mo, y = m.groups()
        return f"{int(d):02d}/{int(mo):02d}/{y}"
    m = RX_FECHA_TEXTO.search(s)
    if m:
        d, mes, y = m.groups()
        mo = MESES.get(_strip_accents(mes).upper(), "")
        if mo:
            return f"{int(d):02d}/{mo}/{y}"
    return ""


def _normalizar_token_plano(tok):
    t = (tok or "").upper()
    t = t.replace("—", "-").replace("–", "-").replace("~", "-").replace("_", "-")
    t = re.sub(r"[^A-Z0-9]", "", t)
    if t in ("AYP", "AUP", "AVF"):
        return "AVP"
    t = t.replace("O", "0") if re.fullmatch(r"[0-9A-Z]{4,6}", t) else t
    t = t.replace("Q", "0") if re.fullmatch(r"[0-9A-Z]{4,6}", t) else t
    t = re.sub(r"^31V", "3IV", t)
    t = re.sub(r"^3IV[OQ]0$", "3IV00", t)
    t = re.sub(r"^3IVOO$", "3IV00", t)
    if t in ("ORW", "0RW", "DRVV", "DW", "DWR"):
        return "DRW"
    if t == "1NG":
        return "ING"
    if t == "TRA1":
        return "TRA"
    return t


def _candidate_from_expected_and_ocr(ocr_txt, expected):
    """Reconstruye el código del rótulo cuando el OCR lee parcialmente (idéntico a producción)."""
    if not ocr_txt:
        return "", False, "sin_texto"
    exp = (expected or "").upper()
    exp_parts = exp.split("-")
    if len(exp_parts) < 7:
        return "", False, "expected_no_estandar"
    exp_div = exp_parts[1]
    exp_num_digits = re.sub(r"\D", "", exp_parts[-1])
    raw = ocr_txt.upper().replace("—", "-").replace("–", "-").replace("~", "-").replace("_", "-")
    raw = re.sub(r"\s+", " ", raw.replace("\n", " "))
    m = RX_PLANO_CODE.search(raw)
    if m:
        cand = re.sub(r"\s+", "", m.group(0)).upper()
        if _norm_code(cand) == _norm_code(expected):
            return cand, True, "regex_directo"
        # NO cortocircuitar: si el regex calzó con una lectura malformada (3->1, etc.)
        # seguimos a la reconstrucción por evidencia, que repara contra el esperado.
    chunks = [raw[mm.start():mm.start() + 180] for mm in re.finditer(r"(AVP|AYP|AUP|AVF)", raw)]
    for line in raw.split(" "):
        if "DRW" in line or "TRA" in line or "ING" in line:
            chunks.append(line)
    best, best_score = "", -1
    for ch in chunks:
        toks = [_normalizar_token_plano(t) for t in re.findall(r"[A-Z0-9]+", ch) if t.strip()]
        joined = "-".join(toks)
        if not (("AVP" in toks or "AVP" in joined) and
                any(x in toks or x in joined for x in ("DRW", "ING", "TRA"))):
            continue
        final_num = ""
        for n in re.findall(r"\d{4,14}", ch):
            nd = re.sub(r"\D", "", n)
            if exp_num_digits.endswith(nd[-4:]) or nd.endswith(exp_num_digits[-4:]):
                final_num = nd.zfill(len(exp_num_digits))[-len(exp_num_digits):]
        if not final_num:
            all_digits = "".join(re.findall(r"\d+", ch))
            if len(all_digits) >= 4 and exp_num_digits.endswith(all_digits[-4:]):
                final_num = all_digits[-len(exp_num_digits):].zfill(len(exp_num_digits))
        score = sum(2 for part in exp_parts[:-1]
                    if _normalizar_token_plano(part) in toks or _normalizar_token_plano(part) in joined)
        if final_num:
            score += 4
        if exp_div in joined or _normalizar_token_plano(exp_div) in joined:
            score += 3
        if score > best_score:
            best_score, best = score, final_num
    if best_score >= 7 and best:
        cand = "-".join(exp_parts[:-1] + [best])
        return cand, (_norm_code(cand) == _norm_code(expected)), f"reconstruido_ocr_score_{best_score}"
    return "", False, "sin_codigo_confiable"


# ================== OCR DENTRO DE LA CAJA ==================
def _otsu_threshold(gray):
    """Umbral óptimo por Otsu desde el histograma (sin cv2)."""
    import numpy as np
    hist = np.asarray(gray.histogram()[:256], dtype=float)
    total = hist.sum()
    if total == 0:
        return 127
    sumT = float(np.dot(np.arange(256), hist))
    wB = sumB = 0.0
    max_var, thr = 0.0, 127
    for i in range(256):
        wB += hist[i]
        if wB == 0:
            continue
        wF = total - wB
        if wF == 0:
            break
        sumB += i * hist[i]
        mB = sumB / wB
        mF = (sumT - sumB) / wF
        var = wB * wF * (mB - mF) ** 2
        if var > max_var:
            max_var, thr = var, i
    return thr


def _prep_variants(img, upscale=2):
    """Genera varias binarizaciones del recorte. Clave para texto GRIS CLARO
    (filas de la hoja de control): el umbral fijo lo borraba; Otsu y un umbral
    alto sí lo recuperan. Reescala recortes chicos para que tesseract lea mejor."""
    g = ImageOps.grayscale(img)
    # Reescalar solo recortes chicos en conjunto. NO reescalar filas anchas (p.ej. la
    # del No. Doc.): ampliarlas mete artefactos y arruina el OCR.
    if upscale and max(g.size) < 1000:
        g = g.resize((g.width * upscale, g.height * upscale), Image.LANCZOS)
    g = ImageOps.autocontrast(g)
    yield g                                              # gris con autocontraste
    otsu = _otsu_threshold(g)
    yield g.point(lambda x: 255 if x > otsu else 0)      # binarización adaptativa
    yield g.point(lambda x: 255 if x > 205 else 0)       # umbral alto (gris claro)


def _prep_for_ocr(img, threshold=170):  # se mantiene por compatibilidad
    return ImageOps.grayscale(img).point(lambda x: 255 if x > threshold else 0)


def crop_box(page_img, box_xywhn):
    """Recorta la caja (cx,cy,w,h normalizados, formato YOLO) del render full-res."""
    W, H = page_img.size
    cx, cy, w, h = box_xywhn
    l = max(0, int((cx - w / 2) * W))
    t = max(0, int((cy - h / 2) * H))
    r = min(W, int((cx + w / 2) * W))
    b = min(H, int((cy + h / 2) * H))
    return page_img.crop((l, t, r, b))


def _ocr_img(prepped, psm=6, whitelist=False, lang="spa"):
    if pytesseract is None:
        raise RuntimeError("pytesseract no disponible")
    cfg = f"--psm {psm}"
    if whitelist:
        cfg += " " + TESS_WHITELIST
    return pytesseract.image_to_string(prepped, lang=lang, config=cfg)


def ocr_text(crop, psm=6, whitelist=False, threshold=170, lang="spa"):
    """OCR de una sola variante (umbral fijo). Para casos simples."""
    return _ocr_img(_prep_for_ocr(crop, threshold), psm=psm, whitelist=whitelist, lang=lang)


def ocr_variants(crop, psm=6, whitelist=False, lang="spa"):
    """OCR sobre todas las binarizaciones; devuelve la lista de textos leídos."""
    out = []
    for prepped in _prep_variants(crop):
        try:
            out.append(_ocr_img(prepped, psm=psm, whitelist=whitelist, lang=lang))
        except Exception:
            pass
    return out


# ================== LECTORES DE CAMPO (sobre el recorte) ==================
def leer_codigo_plano(crop, expected):
    """OCR del recorte de la caja 'codigo' + reconciliación contra el nombre esperado.

    Igual que producción: aunque el regex calce con una lectura del OCR, si NO coincide
    con el esperado se intenta reconstruir (resuelve 3->S, 3->1, O->0, ceros omitidos,
    separadores perdidos como ITSING). Solo se acepta SI cuando hay evidencia suficiente
    (AVP + DRW/ING/TRA + número final que calza con el nombre).
    """
    # Varias pasadas de OCR sobre el mismo recorte (barato) para juntar evidencia:
    # distintos PSM leen mejor según el rótulo. Combinamos todo el texto leído.
    textos = []
    for psm in (7, 6, 11):
        try:
            textos.append(ocr_text(crop, psm=psm, whitelist=True).upper())
        except Exception:
            pass
    txt = "  ".join(textos)
    flat = re.sub(r"\s+", "", txt)
    m = RX_PLANO_CODE.search(flat)
    if m and _norm_code(m.group(0)) == _norm_code(expected):
        return m.group(0).upper(), True
    # Reconciliación contra el esperado (recupera lecturas con errores de OCR)
    cand, coincide, _ = _candidate_from_expected_and_ocr(txt, expected)
    if coincide:
        return cand, True
    # No se pudo confirmar: devolver lo mejor leído, marcado NO
    if m:
        return m.group(0).upper(), False
    return cand, coincide


def leer_no_doc(crop):
    """Prueba varias binarizaciones y PSMs; devuelve el primer código que calce.

    Clave: la caja del No. Doc. es una fila ancha con la etiqueta a la izquierda y
    el valor a la derecha (hueco grande en medio). psm 6 ('bloque uniforme') falla;
    psm 11 ('texto disperso') y psm 4 sí leen ese layout, incluso el valor en gris.
    """
    for psm in (11, 4, 6):
        for txt in ocr_variants(crop, psm=psm) + ocr_variants(crop, psm=psm, whitelist=True):
            txt = txt.upper()
            mline = NO_DOC_LINE_RX.search(txt)
            if mline:
                mcode = RX_DOC_CODE.search(mline.group(1))
                if mcode:
                    return _clean_code(mcode.group(0))
            mcode = RX_DOC_CODE.search(txt)
            if mcode:
                return _clean_code(mcode.group(0))
    return ""


def leer_titulo(crop):
    candidatos = []

    for psm in (11, 4, 6):
        for t in ocr_variants(crop, psm=psm):
            t = re.sub(r"\s+", " ", t).strip()
            t = limpiar_titulo_control(t)

            # Quitar basura típica del OCR, sin borrar palabras reales del título
            t = re.sub(r"\b(DON|DN|HUTO|GOCUMENTO)\b", " ", t, flags=re.I)
            t = re.sub(r"\s+", " ", t).strip()

            # Evitar lecturas que solo son etiqueta o basura
            if len(t) >= 10 and not re.fullmatch(r"(DOCUMENTO|TITULO|DEL|DE|\s)+", t, flags=re.I):
                candidatos.append(t)

    if not candidatos:
        return ""

    # Preferir el candidato con palabras técnicas reales y sin repetir "DE DE"
    candidatos = sorted(
        set(candidatos),
        key=lambda x: (
            "ESTUDIO" in x.upper(),
            "ESTRUCTURAS" in x.upper(),
            len(x)
        ),
        reverse=True
    )

    titulo = candidatos[0]
    titulo = re.sub(r"\bDE\s+DE\b", "DE", titulo, flags=re.I)
    return re.sub(r"\s+", " ", titulo).strip()


def leer_fecha(crop):
    for txt in ocr_variants(crop, psm=6):
        f = _normalizar_fecha(txt)
        if f:
            return f
    return ""


def leer_fecha_ultima(crop):
    fechas = []
    for psm in (4, 11, 6):
        for txt in ocr_variants(crop, psm=psm):
            txt = _strip_accents(txt).upper()
            for m in RX_FECHA_DMY.finditer(txt):
                d, mo, y = m.groups()
                fechas.append((int(y), int(mo), int(d)))
            for m in RX_FECHA_TEXTO.finditer(txt):
                d, mes, y = m.groups()
                mo = MESES.get(_strip_accents(mes).upper(), "")
                if mo:
                    fechas.append((int(y), int(mo), int(d)))

    if not fechas:
        return ""

    y, mo, d = max(fechas)
    return f"{d:02d}/{mo:02d}/{y}"

# ================== VALIDACIÓN PROFESIONAL DE HOJA DE CONTROL ==================
def _cluster_indices(indices):
    """Agrupa índices consecutivos. Se usa para localizar líneas horizontales de tabla."""
    out = []
    indices = list(indices)
    if not indices:
        return out
    start = prev = int(indices[0])
    for value in indices[1:]:
        value = int(value)
        if value <= prev + 1:
            prev = value
        else:
            out.append((start, prev))
            start = prev = value
    out.append((start, prev))
    return out


def _segmentar_filas_tabla(crop, line_ratio=0.45, filas_esperadas=None):
    """Divide un recorte tabular en filas usando las líneas horizontales.

    line_ratio alto (0.85): ignora líneas internas de Nombre/Cargo y conserva
    solamente los límites completos de cada responsable.
    line_ratio medio (0.45): funciona para la columna de firmas.
    """
    import numpy as np

    gray = np.asarray(ImageOps.grayscale(crop))
    if gray.size == 0:
        return []

    dark = gray < 135
    score = dark.mean(axis=1)
    idx = np.where(score >= line_ratio)[0]
    clusters = _cluster_indices(idx)
    bounds = [int(round((a + b) / 2)) for a, b in clusters]

    height = crop.height
    edge_tol = max(5, int(height * 0.02))

    if not bounds or bounds[0] > edge_tol:
        bounds = [0] + bounds
    else:
        bounds[0] = 0

    if not bounds or bounds[-1] < height - 1 - edge_tol:
        bounds.append(height - 1)
    else:
        bounds[-1] = height - 1

    # Fusiona líneas casi contiguas (una línea de tabla suele ocupar 2-4 píxeles).
    min_gap = max(10, int(height * 0.035))
    compact = []
    for y in bounds:
        if not compact or y - compact[-1] >= min_gap:
            compact.append(y)
        else:
            compact[-1] = int(round((compact[-1] + y) / 2))

    min_row_h = max(18, int(height * 0.08))
    rows = [(a, b) for a, b in zip(compact[:-1], compact[1:]) if b - a >= min_row_h]

    if filas_esperadas and 2 <= int(filas_esperadas) <= 6 and len(rows) != int(filas_esperadas):
        n = int(filas_esperadas)
        rows = [
            (int(round(i * height / n)), int(round((i + 1) * height / n)))
            for i in range(n)
        ]

    return rows


def _limpiar_nombre_responsable(nombre):
    """Limpia solo ruido OCR alrededor del nombre, conservando mayúsculas/minúsculas."""
    nombre = (nombre or "").replace("|", " ").replace("_", " ")
    nombre = re.split(
        r"\b(?:CARGO|FECHA|FIRMA|ELABOR[ÓO]?|REVIS[ÓO]?|APROB[ÓO]?)\b",
        nombre,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    nombre = re.sub(r"^[^A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+", "", nombre)
    nombre = re.sub(r"[^A-Za-zÁÉÍÓÚÜÑáéíóúüñ'´.\-\s]", " ", nombre)
    nombre = re.sub(r"\s+", " ", nombre).strip(" .:-")

    # Evita aceptar como nombre una etiqueta o una lectura demasiado pobre.
    palabras = re.findall(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]{2,}", nombre)
    if len(palabras) < 2:
        return ""
    return nombre


def _extraer_nombres_de_texto(texto):
    """Extrae, en orden, cada valor ubicado después de 'Nombre:'."""
    nombres = []
    for match in re.finditer(r"(?im)\bNOMBRE\s*[:.;\-]?\s*([^\r\n]+)", texto or ""):
        nombre = _limpiar_nombre_responsable(match.group(1))
        if nombre:
            nombres.append(nombre)
    return nombres


def leer_responsables_control(crop):
    """Lee Elaboró, Revisó, Aprobó 1 y, si existe, Aprobó 2.

    Devuelve:
        {
            "nombres": [nombre1, nombre2, ...],
            "filas": 3 o 4,
            "texto_ocr": texto seleccionado
        }

    Las posiciones se asignan por el orden vertical de la tabla:
    1=Elaboró, 2=Revisó, 3=Aprobó 1, 4=Aprobó 2.
    """
    candidatos = []

    for psm in (6, 4, 11):
        for texto in ocr_variants(crop, psm=psm):
            nombres = _extraer_nombres_de_texto(texto)
            texto_norm = _strip_accents(texto).upper()
            roles = len(re.findall(r"\b(?:ELABOR\w*|REVIS\w*|APROB\w*)\b", texto_norm))
            score = len(nombres) * 100 + roles * 10 + min(len(texto), 300) / 300
            candidatos.append((score, nombres, texto))

    if candidatos:
        _, nombres_globales, mejor_texto = max(candidatos, key=lambda x: x[0])
    else:
        nombres_globales, mejor_texto = [], ""

    # Las líneas de ancho completo separan responsables; las líneas Nombre/Cargo
    # no cruzan todo el bloque y se descartan con line_ratio=0.85.
    rows = _segmentar_filas_tabla(crop, line_ratio=0.85)
    n_filas = len(rows) if 2 <= len(rows) <= 6 else 0

    nombres_por_fila = []
    for y0, y1 in rows[:4]:
        row = crop.crop((0, y0, crop.width, y1))
        mejores = []
        for psm in (6, 11, 4):
            for texto in ocr_variants(row, psm=psm):
                ns = _extraer_nombres_de_texto(texto)
                if ns:
                    mejores.append(ns[0])
        nombres_por_fila.append(max(mejores, key=len) if mejores else "")

    # Si la lectura por fila produjo más información posicional, se prefiere.
    if nombres_por_fila and sum(bool(x) for x in nombres_por_fila) >= len(nombres_globales):
        nombres = nombres_por_fila
    else:
        nombres = list(nombres_globales)

    n_filas = max(n_filas, len(nombres))
    if n_filas == 0:
        # Aunque el cuadro esté completamente vacío, los tres roles mínimos
        # siguen siendo obligatorios: Elaboró, Revisó y Aprobó.
        n_filas = 3
    n_filas = max(3, min(4, n_filas))

    nombres = (nombres + [""] * n_filas)[:n_filas]
    return {"nombres": nombres, "filas": n_filas, "texto_ocr": mejor_texto}


def _extraer_fechas_texto(texto):
    """Devuelve fechas válidas dd/mm/aaaa encontradas en un texto OCR."""
    import datetime as _dt

    out = []
    texto_sin_tildes = _strip_accents(texto or "").upper()

    for match in RX_FECHA_DMY.finditer(texto_sin_tildes):
        d, mo, y = map(int, match.groups())
        try:
            _dt.date(y, mo, d)
        except ValueError:
            continue
        out.append(f"{d:02d}/{mo:02d}/{y:04d}")

    for match in RX_FECHA_TEXTO.finditer(texto_sin_tildes):
        d, mes, y = match.groups()
        mo = MESES.get(_strip_accents(mes).upper())
        if not mo:
            continue
        try:
            _dt.date(int(y), int(mo), int(d))
        except ValueError:
            continue
        out.append(f"{int(d):02d}/{int(mo):02d}/{int(y):04d}")

    return out


def leer_fechas(crop):
    """Lee todas las fechas distintas del recorte, conservando su orden."""
    fechas = []
    for psm in (4, 11, 6):
        for texto in ocr_variants(crop, psm=psm):
            for fecha in _extraer_fechas_texto(texto):
                if fecha not in fechas:
                    fechas.append(fecha)
    return fechas


def _fila_tiene_firma(row_crop):
    """Determina si una fila contiene rúbrica/sello, no solo la palabra 'Firma'.

    Se ignora la parte izquierda de la celda, donde está impresa la etiqueta
    'Firma', y se evalúa tinta coloreada o tinta oscura con extensión suficiente.
    """
    import numpy as np

    arr = np.asarray(row_crop.convert("RGB"))
    if arr.size == 0:
        return False, {"pixeles_color": 0, "pixeles_oscuros": 0}

    height, width = arr.shape[:2]
    x0 = max(1, int(width * 0.32))
    x1 = max(x0 + 1, width - max(2, int(width * 0.015)))
    y0 = max(1, int(height * 0.06))
    y1 = max(y0 + 1, height - max(2, int(height * 0.06)))
    sub = arr[y0:y1, x0:x1]

    if sub.size == 0:
        return False, {"pixeles_color": 0, "pixeles_oscuros": 0}

    gray = np.asarray(ImageOps.grayscale(Image.fromarray(sub)))
    sat = sub.max(axis=2).astype(int) - sub.min(axis=2).astype(int)

    # Color: útil para firmas azules incluso muy tenues.
    color_mask = (sat > 8) & (gray < 252)
    # Oscuro: útil para firmas negras, sellos y firmas escaneadas.
    dark_mask = gray < 210

    # Elimina líneas rectas de tabla que pudieran quedar en el recorte.
    for mask in (color_mask, dark_mask):
        if mask.size:
            mask[mask.mean(axis=1) > 0.65, :] = False
            mask[:, mask.mean(axis=0) > 0.65] = False

    def metrics(mask):
        ys, xs = np.where(mask)
        if len(xs) == 0:
            return 0, 0, 0
        return (
            int(len(xs)),
            int(xs.max() - xs.min() + 1),
            int(ys.max() - ys.min() + 1),
        )

    color_px, color_w, color_h = metrics(color_mask)
    dark_px, dark_w, dark_h = metrics(dark_mask)
    area = int(gray.size)

    color_ok = (
        color_px >= max(18, int(area * 0.0015))
        and color_w >= max(8, int(gray.shape[1] * 0.08))
        and color_h >= max(4, int(gray.shape[0] * 0.06))
    )
    dark_ok = (
        dark_px >= max(60, int(area * 0.004))
        and dark_w >= max(10, int(gray.shape[1] * 0.10))
        and dark_h >= max(5, int(gray.shape[0] * 0.10))
    )

    return bool(color_ok or dark_ok), {
        "pixeles_color": color_px,
        "ancho_color": color_w,
        "alto_color": color_h,
        "pixeles_oscuros": dark_px,
        "ancho_oscuro": dark_w,
        "alto_oscuro": dark_h,
        "area": area,
    }


def analizar_firmas_control(crop, filas_esperadas=None):
    """Verifica la firma real de cada responsable dentro de la hoja de control."""
    rows = _segmentar_filas_tabla(
        crop,
        line_ratio=0.45,
        filas_esperadas=filas_esperadas,
    )

    if not rows:
        n = int(filas_esperadas or 3)
        n = max(3, min(4, n))
        rows = [
            (int(round(i * crop.height / n)), int(round((i + 1) * crop.height / n)))
            for i in range(n)
        ]

    firmas = []
    metricas = []
    for y0, y1 in rows[:4]:
        row = crop.crop((0, y0, crop.width, y1))
        tiene, metrica = _fila_tiene_firma(row)
        firmas.append(tiene)
        metricas.append(metrica)

    n_filas = max(3, min(4, int(filas_esperadas or len(firmas) or 3)))
    firmas = (firmas + [False] * n_filas)[:n_filas]
    metricas = (metricas + [{}] * n_filas)[:n_filas]

    return {"firmas": firmas, "filas": n_filas, "metricas": metricas}


# ================== VALIDACIÓN COMPLEMENTARIA POR PÁGINA ==================
def limpiar_texto(txt):
    """Limpia texto OCR conservando saltos de línea útiles."""
    txt = "" if txt is None else str(txt)
    txt = txt.replace("\x0c", " ")
    txt = re.sub(r"[ \t]+", " ", txt)
    txt = re.sub(r"\n{2,}", "\n", txt)
    return txt.strip()

# Estas funciones apoyan a infer.py para leer sellos laterales, firmantes,
# cargos, CIP y entidades/logo en páginas completas. Se mantienen aquí porque
# son funciones de extracción/OCR, no de armado del reporte.

def limpiar_lineal(txt):
    """Normaliza un texto OCR a una sola línea segura para Excel/reporte."""
    txt = limpiar_texto(txt) if "limpiar_texto" in globals() else (txt or "")
    txt = (txt or "").replace("\n", " ")
    txt = re.sub(r"\s+", " ", txt).strip()
    if txt.lower() in ("nan", "none", "null"):
        return ""
    return txt


def _ocr_img_safe(prepped, psm=6, whitelist=False, lang="spa"):
    """OCR con fallback a inglés si el idioma spa no está instalado."""
    try:
        return _ocr_img(prepped, psm=psm, whitelist=whitelist, lang=lang)
    except Exception:
        return _ocr_img(prepped, psm=psm, whitelist=whitelist, lang="eng")


def ocr_mejor_rotacion(crop, tipo="sello"):
    """Prueba rotaciones y PSMs para quedarse con el OCR más útil.

    Args:
        crop: PIL.Image del recorte.
        tipo: "sello" o "logo"; cambia las palabras que mejoran el puntaje.

    Returns:
        (texto, rotacion, psm)
    """
    candidatos = []

    if crop is None:
        return "", 0, 6

    if crop.mode != "RGB":
        crop = crop.convert("RGB")

    if tipo == "sello":
        claves = [
            "CIP", "REG", "GERENTE", "JEFE", "ESPECIALISTA",
            "PROYECTO", "CONCESIONARIA", "CONSTRUCCION", "CONSTRUCCIÓN"
        ]
    else:
        claves = [
            "PROINVERSION", "PROINVERSIÓN", "MTC", "MINISTERIO", "TRANSPORTES",
            "COMUNICACIONES", "OSITRAN", "CONCESIONARIA", "ANILLO", "VIAL", "AVP"
        ]

    for rot in (0, 90, 180, 270):
        pil = crop.rotate(rot, expand=True)

        for psm in (6, 11, 12):
            textos = []
            for prepped in _prep_variants(pil):
                try:
                    textos.append(_ocr_img_safe(prepped, psm=psm, whitelist=False, lang="spa"))
                except Exception:
                    pass

            texto = limpiar_texto(" ".join(textos))
            texto_u = _strip_accents(texto).upper()

            score = len(re.sub(r"[^A-Z0-9]", "", texto_u))
            for clave in claves:
                if _strip_accents(clave).upper() in texto_u:
                    score += 40

            candidatos.append((score, rot, psm, texto))

    if not candidatos:
        return "", 0, 6

    candidatos.sort(reverse=True, key=lambda x: x[0])
    _, rot, psm, texto = candidatos[0]
    return texto, rot, psm


def extraer_datos_sello(texto):
    """Extrae nombre, cargo y CIP desde el OCR de un sello/firma lateral."""
    texto_limpio = limpiar_texto(texto)
    texto_u = _strip_accents(texto_limpio).upper()

    nombre = ""
    cargo = ""
    cip = ""

    m = re.search(r"(?:REG\.?\s*)?CIP\.?\s*(?:N[°º]?\s*)?(\d{3,8})", texto_u)
    if m:
        cip = m.group(1)
    elif "2049" in texto_u:
        cip = "2049"
    elif "264301" in texto_u:
        cip = "264301"

    # Reglas para los sellos frecuentes encontrados en el dataset AVP.
    if "MAYRA" in texto_u and "GOMEZ" in texto_u and "SANDOVAL" in texto_u:
        nombre = "Mayra Gómez Sandoval"
        cargo = "Jefe de Proyecto"

    elif "ELISEO" in texto_u and "ALVAREZ" in texto_u:
        nombre = "Eliseo Álvarez Palomares"
        cargo = "Especialista"
        if not cip and "2049" in texto_u:
            cip = "2049"

    elif "ARMANDO" in texto_u and "GON" in texto_u:
        nombre = "Armando González González"
        cargo = "Gerente de Proyecto"
        if not cip and "264301" in texto_u:
            cip = "264301"

    elif "MIGUE" in texto_u and "GUTI" in texto_u:
        nombre = "Miguel Núñez Gutiérrez"
        cargo = "Gerente de Construcción" if "CONSTRU" in texto_u else "Gerente"

    # Fallback genérico: toma una línea que parezca nombre propio.
    if not nombre:
        lineas = [l.strip() for l in texto_limpio.splitlines() if l.strip()]
        excluir = [
            "CIP", "REG", "GERENTE", "JEFE", "ESPECIALISTA",
            "COORDINADOR", "RESPONSABLE", "SUPERVISOR",
            "SOCIEDAD", "CONCESIONARIA", "PROYECTO", "SAC", "S.A.C"
        ]
        for linea in lineas:
            u = _strip_accents(linea).upper()
            u = re.sub(r"[^A-ZÑ ]", " ", u)
            u = re.sub(r"\s+", " ", u).strip()
            if len(u.split()) >= 2 and not any(e in u for e in excluir):
                nombre = linea.title()
                break

    if not cargo:
        if "JEFE" in texto_u:
            cargo = "Jefe de Proyecto"
        elif "ESPECIALISTA" in texto_u:
            cargo = "Especialista"
        elif "GERENTE" in texto_u and "CONSTRU" in texto_u:
            cargo = "Gerente de Construcción"
        elif "GERENTE" in texto_u:
            cargo = "Gerente de Proyecto"

    return nombre, cargo, cip


def identificar_entidades_logo(texto):
    """Devuelve entidades limpias detectadas desde el OCR de un logo."""
    txt = _strip_accents(texto or "").upper()
    entidades = []

    if "PROINVERSION" in txt:
        entidades.append("PROINVERSIÓN")

    if "MTC" in txt or "MINISTERIO" in txt or "TRANSPORTES" in txt:
        entidades.append("MTC")

    if "OSITRAN" in txt:
        entidades.append("OSITRAN")

    if "CONCESIONARIA" in txt or "ANILLO VIAL" in txt or "AVP" in txt:
        entidades.append("Sociedad Concesionaria Anillo Vial")

    salida = []
    for entidad in entidades:
        if entidad not in salida:
            salida.append(entidad)

    if not salida:
        return "Logo detectado; entidad no identificada por OCR"

    return " | ".join(salida)


def recortar_xyxy(page_img, xyxy):
    """Recorta una caja xyxy en píxeles sobre una imagen PIL."""
    w, h = page_img.size
    x1, y1, x2, y2 = [int(v) for v in xyxy]
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(w, x2), min(h, y2)
    if x2 <= x1 or y2 <= y1:
        return page_img.crop((0, 0, 1, 1))
    return page_img.crop((x1, y1, x2, y2))


def expandir_xyxy(xyxy, image_size, margen=80):
    """Amplía una caja xyxy para que el OCR capture texto alrededor del logo."""
    w, h = image_size
    x1, y1, x2, y2 = [int(v) for v in xyxy]
    return (
        max(0, x1 - margen),
        max(0, y1 - margen),
        min(w, x2 + margen),
        min(h, y2 + margen),
    )

