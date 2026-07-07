"""
Construye el reporte de RAMEC con la lógica SI / NO / SIN_DATO / NO_APLICA.

La hoja VALIDACION_PROFESIONAL ya no considera suficiente la presencia de una
caja detectada. En documentos, informa responsables, firma real por fila, fecha
de validación y una conclusión final.
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
        "Titulo_Caratula": titulo, "Titulo_Control_Cambios": limpiar_titulo_control(titulo_ctrl),
        "Titulo_Coincide": titulo_ok,
        "NoDoc_Caratula": nd, "NoDoc_Control_Cambios": nodoc_ctrl,
        "NoDoc_Coincide": nodoc_ok,
        "Observacion": obs,
    }


def _sn(valor):
    return "SI" if bool(valor) else "NO"


def fila_validacion_profesional(path, tipo, datos):
    """Construye la fila de validación profesional.

    PLANO:
        Mantiene la validación por presencia de responsables, validación y entidades.

    DOCUMENTO:
        - Extrae Elaboró, Revisó, Aprobó 1 y Aprobó 2 (si existe).
        - Verifica una rúbrica real por cada fila.
        - Extrae la fecha de validación.
        - Compara esa fecha con carátula y última revisión.
        - Concluye SI únicamente si responsables, firmas y fecha están completos.
    """
    if tipo == "PLANO":
        responsables = datos.get("responsables", False)
        validacion = datos.get("validacion_profesional", False)
        logos = datos.get("entidades", False)
        ok = responsables and validacion and logos
        return {
            "Ruta": str(path), "Archivo": path.name, "Tipo": tipo,
            "Responsables_Plano": _sn(responsables),
            "Validacion_Profesional_Plano": _sn(validacion),
            "Logo_Entidades": _sn(logos),
            "Validacion_Profesional": _sn(ok),
        }

    nombres = list(datos.get("nombres", []))
    firmas = list(datos.get("firmas", []))
    filas = int(datos.get("filas", 0) or 0)

    filas = max(filas, len(nombres), len(firmas))
    # Los tres roles mínimos siempre son obligatorios.
    filas = max(3, min(4, filas or 3))

    nombres = (nombres + [""] * 4)[:4]
    firmas = (firmas + [False] * 4)[:4]

    aplica_aprobo2 = filas >= 4
    requeridos = 4 if aplica_aprobo2 else 3

    responsables_completos = all(bool(nombres[i].strip()) for i in range(requeridos))
    firmas_completas = all(bool(firmas[i]) for i in range(requeridos))

    fecha_validacion = datos.get("fecha_validacion", "")
    fechas_validacion = list(datos.get("fechas_validacion", []))
    fechas_uniformes = bool(fecha_validacion) and len(set(fechas_validacion or [fecha_validacion])) == 1

    fecha_caratula = datos.get("fecha_caratula", "")
    fecha_ultima_revision = datos.get("fecha_ultima_revision", "")
    fecha_coincide = bool(
        fechas_uniformes
        and fecha_caratula
        and fecha_ultima_revision
        and fecha_validacion == fecha_caratula == fecha_ultima_revision
    )

    validacion_ok = responsables_completos and firmas_completas and fecha_coincide

    return {
        "Ruta": str(path),
        "Archivo": path.name,
        "Tipo": tipo,
        "Elaboró": nombres[0],
        "Revisó": nombres[1],
        "Aprobó_1": nombres[2],
        "Aprobó_2": nombres[3] if aplica_aprobo2 else "",
        "Firma_Elaboró": _sn(firmas[0]),
        "Firma_Revisó": _sn(firmas[1]),
        "Firma_Aprobó_1": _sn(firmas[2]),
        "Firma_Aprobó_2": _sn(firmas[3]) if aplica_aprobo2 else "NO_APLICA",
        "Fecha_validacion": fecha_validacion,
        "Responsables_completos": _sn(responsables_completos),
        "Firmas_completas": _sn(firmas_completas),
        "Fecha_coincide": _sn(fecha_coincide),
        "Validacion_profesional": _sn(validacion_ok),
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
            df = pd.DataFrame(validacion)
            preferidas = [
                "Ruta", "Archivo", "Tipo",
                "Elaboró", "Revisó", "Aprobó_1", "Aprobó_2",
                "Firma_Elaboró", "Firma_Revisó", "Firma_Aprobó_1", "Firma_Aprobó_2",
                "Fecha_validacion", "Responsables_completos", "Firmas_completas",
                "Fecha_coincide", "Validacion_profesional",
            ]
            orden = [c for c in preferidas if c in df.columns]
            orden += [c for c in df.columns if c not in orden]
            df[orden].to_excel(xw, sheet_name="VALIDACION_PROFESIONAL", index=False)
