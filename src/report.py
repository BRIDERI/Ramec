"""
Construye el reporte de 5 pestañas con las MISMAS columnas y la misma lógica
SI / NO / SIN_DATO / NO_APLICA que el script de producción.

Cada builder recibe los campos ya extraídos (por nomenclatura.py y extract.py) y
devuelve el dict de una fila. write_report() arma el xlsx.
"""
import pandas as pd

from extract import _norm_code, _norm_text_cmp, limpiar_titulo_control, canon_codigos


def fila_estandar(path, tipo, campos, orden_ok, catalogo_ok, errores):
    return {
        "Ruta": str(path), "Archivo": path.name, "Tipo": tipo,
        "EXPEDIENTE": campos["EXPEDIENTE"], "ORIGINADOR": campos["ORIGINADOR"],
        "DIVISION": campos["DIVISION"], "FASE": campos["FASE"], "DOCUMENTO": campos["DOCUMENTO"],
        "DISCIPLINA": campos["DISCIPLINA"], "AREA": campos["AREA"], "NUMDOC": campos["NUMDOC"],
        "EXT_token": campos["EXT_token"], "EXT_real": campos["EXT_real"],
        "A_Orden_OK": "SI" if orden_ok else "NO",
        "B_Catalogo_OK": "SI" if catalogo_ok else "NO",
        "Detalle_errores": errores,
    }


def fila_comp_plano(path, expected, code, coincide):
    return {
        "Ruta": str(path), "Archivo": path.name, "Nombre_sin_ext": expected,
        "Codigo_rotulo": code,
        "Coincide": "SI" if coincide else ("NO" if code else "SIN_DATO"),
    }


def fila_comp_doc(path, expected, nd):
    coincide = (_norm_code(nd) == _norm_code(expected)) if nd else False
    return {
        "Ruta": str(path), "Archivo": path.name, "Nombre_sin_ext": expected,
        "No_Doc_caratula": nd,
        "Coincide": "SI" if coincide else ("NO" if nd else "SIN_DATO"),
    }


def fila_coherencia(path, titulo, nd, cod_doc_nombre, tipo_texto):
    return {
        "Ruta": str(path), "Archivo": path.name,
        "Titulo_detectado_caratula": titulo,
        "No_Doc_caratula": nd,
        "Cod_doc_nombre": cod_doc_nombre,
        "Tipo_detectado_caratula": tipo_texto,
        "Coherente": "SI" if (tipo_texto and tipo_texto == cod_doc_nombre) else "NO",
    }


def fila_control_cambios(path, existe, fecha_caratula, fecha_ctrl,
                         titulo, titulo_ctrl, nd, nodoc_ctrl):
    if not existe:
        fecha_ok = titulo_ok = nodoc_ok = "NO_APLICA"
        obs = "No tiene hoja de control de cambios en página 2"
    else:
        fecha_ok = "SI" if (fecha_caratula and fecha_ctrl and fecha_caratula == fecha_ctrl) else "NO"
        titulo_ok = "SI" if (_norm_text_cmp(titulo) and
                             canon_codigos(_norm_text_cmp(titulo)) ==
                             canon_codigos(limpiar_titulo_control(titulo_ctrl))) else "NO"
        nodoc_ok = "SI" if (_norm_code(nd) and _norm_code(nd) == _norm_code(nodoc_ctrl)) else "NO"
        obs_parts = []
        if not fecha_caratula:
            obs_parts.append("No se pudo leer fecha de carátula")
        if not fecha_ctrl:
            obs_parts.append("No se pudo leer fecha de control de cambios")
        if not titulo_ctrl:
            obs_parts.append("No se pudo leer título en control de cambios")
        if not nodoc_ctrl:
            obs_parts.append("No se pudo leer No. Doc. en control de cambios")
        obs = " | ".join(obs_parts)
    return {
        "Ruta": str(path), "Archivo": path.name,
        "Control_Cambios_Existe": "SI" if existe else "NO",
        "Fecha_Caratula": fecha_caratula, "Fecha_Ultimo_Cambio": fecha_ctrl,
        "Fecha_Coincide": fecha_ok,
        "Titulo_Caratula": titulo, "Titulo_Control_Cambios": titulo_ctrl,
        "Titulo_Coincide": titulo_ok,
        "NoDoc_Caratula": nd, "NoDoc_Control_Cambios": nodoc_ctrl,
        "NoDoc_Coincide": nodoc_ok,
        "Observacion": obs,
    }


def fila_validacion_profesional(path, tipo, pres):
    """Módulo NUEVO: verifica la PRESENCIA de los elementos de validación profesional
    que el detector localiza. No usa OCR; es presencia por detección.

    PLANO     -> responsables (6), validacion_profesional (7), entidades/logos (8).
    DOCUMENTO -> validacion_profesional_hoja_control (9), responsables_hoja_control (18),
                 firmas_aprobacion_paginas (19), logo_entidades (20 o 22).
    """
    def f(b):
        return "SI" if b else "NO"
    if tipo == "PLANO":
        responsables = pres.get("responsables", False)
        validacion = pres.get("validacion_profesional", False)
        logos = pres.get("entidades", False)
        firmas_val = "NO_APLICA"
        ok = responsables and validacion and logos
    else:
        responsables = pres.get("responsables_hoja_control", False)
        validacion = pres.get("validacion_profesional_hoja_control", False)
        firmas = pres.get("firmas_aprobacion_paginas", False)
        logos = pres.get("logo_entidades_caratula", False) or pres.get("logo_entidades_paginas", False)
        firmas_val = f(firmas)
        ok = responsables and validacion and firmas and logos
    return {
        "Ruta": str(path), "Archivo": path.name, "Tipo": tipo,
        "Responsables": f(responsables),
        "Validacion_Profesional": f(validacion),
        "Firmas_Aprobacion": firmas_val,
        "Logo_Entidades": f(logos),
        "Validacion_Profesional_OK": "SI" if ok else "NO",
    }


def write_report(salida, estandar, comp_plano, comp_doc, coherencia, control, validacion=None):
    with pd.ExcelWriter(salida, engine="openpyxl") as xw:
        pd.DataFrame(estandar).to_excel(xw, sheet_name="ESTANDAR NOMENCLATURA", index=False)
        if comp_plano:
            pd.DataFrame(comp_plano).to_excel(xw, sheet_name="COMPATIBILIDAD_PLANO", index=False)
        if comp_doc:
            pd.DataFrame(comp_doc).to_excel(xw, sheet_name="COMPATIBILIDAD_DOCUMENTO", index=False)
        if coherencia:
            pd.DataFrame(coherencia).to_excel(xw, sheet_name="COHERENCIA_DOCUMENTO", index=False)
        if control:
            pd.DataFrame(control).to_excel(xw, sheet_name="CONTROL_CAMBIOS_DOC", index=False)
        if validacion:
            pd.DataFrame(validacion).to_excel(xw, sheet_name="VALIDACION_PROFESIONAL", index=False)
