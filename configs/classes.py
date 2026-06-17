"""
RAMEC - Tabla global de clases (Opción A).

Los dos modelos (planos y documentos) entrenan con la MISMA lista de 23 clases
y nc=23. Cada modelo solo puebla un subconjunto disjunto:
    - planos      -> ids 0..8   (el rótulo)
    - documentos  -> ids 9..22  (carátula, hoja de control, páginas internas)
Las clases no pobladas quedan vacías en cada modelo; eso es esperado y correcto.

Esta tabla es la única fuente de verdad id<->nombre para todo el pipeline
(conversión, entrenamiento e inferencia). Debe coincidir EXACTAMENTE con el
campo `names` de configs/planos.yaml y configs/documentos.yaml.
"""

CLASSES = {
    0:  "membrete",
    1:  "codigo",
    2:  "fecha",
    3:  "contenido",
    4:  "proyecto",
    5:  "revisiones",
    6:  "responsables",
    7:  "validacion_profesional",
    8:  "entidades",
    9:  "validacion_profesional_hoja_control",
    10: "fecha_ultima_revision_hoja_control",
    11: "proyecto_caratula",
    12: "titulo_documento_caratula",
    13: "num_documento_caratula",
    14: "fecha_caratula",
    15: "num_documento_hoja_control",
    16: "titulo_documento_hoja_control",
    17: "fecha_aprobacion_hoja_control",
    18: "responsables_hoja_control",
    19: "firmas_aprobacion_paginas",
    20: "logo_entidades_caratula",
    21: "num_revision_hoja_control",
    22: "logo_entidades_paginas",
}

NAME_TO_ID = {v: k for k, v in CLASSES.items()}
NAMES = [CLASSES[i] for i in range(len(CLASSES))]  # orden por id, para el yaml
NC = len(CLASSES)  # 23

# Subconjuntos reales por modelo. Sirven para validar que un export no traiga
# ids fuera de lo esperado (p.ej. una clase de carátula colada en un plano).
PLANO_IDS = list(range(0, 9))    # 0..8
DOC_IDS = list(range(9, 23))     # 9..22

# Clases "load-bearing": las que alimentan directamente cada pestaña del reporte.
# Estas son las que deben salir casi perfectas del modelo. El resto es riqueza
# para validaciones futuras. (ESTANDAR NOMENCLATURA no usa modelo: sale del
# nombre del archivo + catálogos de base/base.json.)
REPORT_FIELDS = {
    "COMPATIBILIDAD_PLANO":     ["codigo"],
    "COMPATIBILIDAD_DOCUMENTO": ["num_documento_caratula"],
    "COHERENCIA_DOCUMENTO":     ["titulo_documento_caratula"],
    "CONTROL_CAMBIOS_DOC":      [
        "fecha_caratula",
        "fecha_ultima_revision_hoja_control",
        "titulo_documento_hoja_control",
        "num_documento_hoja_control",
    ],
}


def assert_consistencia():
    """Chequeo barato de que ids 0..NC-1 son contiguos y sin huecos."""
    assert sorted(CLASSES) == list(range(NC)), "Los ids deben ser 0..NC-1 contiguos"
    assert len(NAMES) == NC


if __name__ == "__main__":
    assert_consistencia()
    print(f"OK - {NC} clases, planos={len(PLANO_IDS)} doc={len(DOC_IDS)}")
