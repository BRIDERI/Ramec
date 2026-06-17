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


def limpiar_titulo_control(s):
    norm = _norm_text_cmp(s)
    norm = RX_LABEL_TITULO.sub(" ", norm)
    return re.sub(r"\s+", " ", norm).strip()


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
    """Lee el título prefiriendo la ESCALA DE GRISES por fidelidad de caracteres.

    El gris con autocontraste (variante 0) conserva el antialiasing y distingue 0 de O;
    binarizar mete errores (3PL01 -> 3PLO1). Pero si el gris saliera corto/ruidoso,
    no queremos quedarnos con basura: preferimos el gris solo cuando su longitud es
    comparable a la mejor lectura; si no, caemos a la más larga.
    """
    textos = [re.sub(r"\s+", " ", t).strip() for t in ocr_variants(crop, psm=6)]
    textos = [t for t in textos if len(t) >= 3]
    if not textos:
        return ""
    maxlen = max(len(t) for t in textos)
    for t in textos:  # textos[0] = escala de grises (la de mayor fidelidad)
        if len(t) >= 0.9 * maxlen:
            return t
    return max(textos, key=len)


def leer_fecha(crop):
    for txt in ocr_variants(crop, psm=6):
        f = _normalizar_fecha(txt)
        if f:
            return f
    return ""


def leer_fecha_ultima(crop):
    """Para la columna 'Fecha del cambio' de la hoja de control: la fecha MÁS RECIENTE.

    El recorte abarca varias filas de revisión; producción usaba la última. Leemos
    todas las fechas (formato d/m/aaaa y '6 de abril de 2026'), sobre varias
    binarizaciones, y devolvemos la máxima.
    """
    fechas = []
    for txt in ocr_variants(crop, psm=6):
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
