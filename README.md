# RAMEC — Revisión Automática Multimodal de Entregables de Construcción - Revisión de entregables AVP

Sistema que replica el reporte de 5 pestañas del validador de producción
(`REVARCHIVOS_*.py`), pero reemplazando el barrido de OCR a ciegas por dos modelos
de detección entrenados con anotaciones de CVAT. El OCR solo lee **dentro** de la
caja que el modelo localiza, sobre el render a resolución nativa.

---

> Examen Final - Maestría en Inteligencia Artificial · Curso de Redes Neuronales y Aprendizaje Profundo · Sección A · Grupo 7

Integrantes:
- Julio Machado Torres.
- Brigitte Scarlett Del Río Ricce.

Docente:
- Ph.D. Aldo Camargo Fernández Baca.

---

[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/BRIDERI/Ramec/blob/main/RAMEC_colab.ipynb)

## Instalación y ejecución

Para **solo ejecutar la validación** (sin reentrenar) necesitas: el código (ya en este
repo), las dependencias de sistema (Tesseract + Poppler), las de Python, y los pesos
entrenados `best.pt` (se distribuyen aparte; ver paso 3).

### 1. Clonar e instalar dependencias del sistema
Tesseract y Poppler **no** se instalan con pip:
```bash
git clone https://github.com/BRIDERI/Ramec.git
cd ramec
# Ubuntu/Debian
sudo apt-get update && sudo apt-get install -y tesseract-ocr tesseract-ocr-spa poppler-utils
# macOS (Homebrew)
brew install tesseract tesseract-lang poppler
```
El paquete de idioma `tesseract-ocr-spa` es necesario para leer los textos en español.

### 2. Dependencias de Python
```bash
python -m venv .venv && source .venv/bin/activate   # recomendado
pip install -r requirements.txt
```

### 3. Descargar los pesos del modelo
Los pesos `best.pt` (~40 MB c/u) se publican como assets del *Release*. Descárgalos con:
```bash
REPO=BRIDERI/Ramec TAG=v1.0 bash scripts/download_models.sh
```
Esto deja `models/planos/best.pt` y `models/documentos/best.pt`. También puedes bajarlos
a mano desde la pestaña **Releases** del repositorio.

### 4. Ejecutar la validación
```bash
python src/infer.py --pdfs <carpeta_con_PDFs> --salida outputs/Reporte_validacion.xlsx
```
El resultado es un Excel con seis hojas de verificación. Los PDFs de entrada los aportas
tú (no se incluyen entregables reales por confidencialidad).

### Reentrenar (opcional)
Requiere el dataset anotado en CVAT (no incluido en el repo). Con tu dataset en `data/raw/`:
```bash
python src/convert.py --planos data/raw/planos --documentos data/raw/documentos --val-frac 0.15
python src/train.py --task both
```

## Estado: funcionando

Validado sobre el lote de prueba (5 planos + 5 documentos), el rebuild reproduce
el reporte de producción y lo supera en planos:

| Pestaña | Rebuild | Producción |
|---|---|---|
| ESTANDAR NOMENCLATURA | 4 NO de catálogo (correctos) | iguales |
| COMPATIBILIDAD_PLANO | **5/5** | 4/5 |
| COMPATIBILIDAD_DOCUMENTO | 5/5 | 5/5 |
| COHERENCIA_DOCUMENTO | 5/5 | 5/5 |
| CONTROL_CAMBIOS_DOC (fecha / título / No.Doc) | 5/5 · 5/5 · 5/5 | 5/5 |

Además del reporte de producción, RAMEC añade una sexta hoja
**VALIDACION_PROFESIONAL** (módulo nuevo): verifica por presencia de detección los
elementos de validación profesional (responsables, validación profesional, firmas
de aprobación y logos de entidades). Es presencia, no autenticidad de firma.

Los 4 `B_Catalogo_OK = NO` (división `3PL01`/`3PL02`, disciplina `DES`) coinciden
con producción: confirmar si son errores del entregable o huecos del catálogo maestro.

## Decisiones tomadas

- **Dos modelos** entrenados por separado: `planos` (rótulo) y `documentos`
  (carátula + hoja de control + páginas internas).
- **Opción A (clases):** ambos modelos usan `nc=23` y la lista global completa.
  Cada uno solo puebla su subconjunto (planos 0–8, documentos 9–22); el resto
  quedan vacías. Única fuente de verdad: `configs/classes.py`.
- **Páginas internas (documentos):** se etiqueta una *muestra* (~3 por documento,
  variadas), cada una al 100%. Las no etiquetadas NO entran al dataset (serían
  falsos negativos). Carátula (p1) y control (p2) siempre entran completas.
- **Planos a `imgsz` alto (1536):** con resize agresivo el `codigo` queda en ~20 px
  y no se aprende; a 1536 se detecta bien. Las láminas miden ~6623×4678.
- **Comparación de títulos exacta** (orden importa), tras limpiar la etiqueta
  "Título del documento" y canonizar la ambigüedad O/0 dentro de códigos.

## Estructura

```
ramec/
├── configs/
│   ├── classes.py          # tabla global id<->nombre (Opción A) + grupos del reporte
│   ├── planos.yaml         # data.yaml YOLO (nc=23)
│   └── documentos.yaml     # data.yaml YOLO (nc=23)
├── base/
│   └── base.json           # catálogos del estándar (pestaña 1) + doc_tipo_map
├── data/
│   ├── raw/{planos,documentos}/   # exports CVAT (YOLO) descomprimidos
│   ├── planos/             # images/{train,val} + labels/{train,val}
│   └── documentos/         # images/{train,val} + labels/{train,val}
├── src/
│   ├── convert.py          # paso 1: CVAT -> YOLO + split val estratificado
│   ├── train.py            # paso 2: entrena planos y documentos
│   ├── extract.py          # OCR dentro de las cajas + normalizadores
│   ├── nomenclatura.py     # pestaña ESTANDAR NOMENCLATURA (sin modelo)
│   ├── report.py           # arma el xlsx (5 hojas de producción + VALIDACION_PROFESIONAL)
│   └── infer.py            # paso 3: orquesta todo y genera el reporte
├── scripts/
│   ├── build_base.py       # genera base.json desde el Excel maestro de catálogos
│   ├── sync.py             # Drive <-> /content
│   └── diag_control.py     # diagnóstico de la hoja de control (detección + OCR)
├── models/{planos,documentos}/   # best.pt (se persisten a Drive)
├── outputs/                # Reporte_validacion_AVP.xlsx
├── requirements.txt
└── README.md
```

## Uso (Colab, A100)

`/content` se borra al reiniciar; Drive persiste. Los datos viven en Drive y se
copian a `/content` para leer rápido; los modelos vuelven a Drive al terminar.

```python
# 1) Montar Drive y traer el repo
from google.colab import drive
drive.mount('/content/drive')
!cp -r /content/drive/MyDrive/ramec /content/ramec
%cd /content/ramec

# 2) Dependencias (apt-get update evita el 404 de paquetes)
!apt-get -qq update
!apt-get -qq install -y tesseract-ocr tesseract-ocr-spa poppler-utils
!pip -q install -r requirements.txt
```

```bash
# 3) Pipeline
python scripts/build_base.py --excel base/AVP-BASE_DE_DATOS_PARA_REVISION_DE_ENTREGABLES.xlsx --out base/base.json
python src/convert.py --planos data/raw/planos --documentos data/raw/documentos --val-frac 0.15
python src/train.py --task both          # --model yolo26m.pt para probar planos
python src/infer.py --pdfs pdfs --salida outputs/Reporte_validacion_AVP.xlsx
```

```python
# 4) Persistir a Drive (los modelos también se sincronizan solos al final de train)
!python scripts/sync.py push-models
!cp outputs/Reporte_validacion_AVP.xlsx /content/drive/MyDrive/ramec/outputs/
```

Para una corrida nueva sin reentrenar: salta `convert`/`train` (los `best.pt`
viajan con el repo) y corre directo `infer.py`. El notebook `RAMEC_colab.ipynb`
tiene cada paso en su celda.

## Detalles que hacen que funcione

- **Augmentation segura para layout** (`train.py`): sin flips ni rotaciones
  (espejaría el texto y rompería la semántica de posición); planos **sin mosaic**
  (encoge el `codigo`, que ya es chico); documentos sí usa mosaic.
- **OCR en escala de grises, no binarizado puro** (`extract.py`): el gris con
  autocontraste conserva el antialiasing y distingue 0 de O; binarizar mete
  errores. El No. Doc. de la hoja de control va en gris claro y en fila ancha:
  se lee con PSM 11/4 (no el 6) y sin reescalar filas anchas.
- **Reconciliación del código de plano**: si el OCR lee parcial/mal, se reconstruye
  contra el nombre esperado (resuelve O/0, ceros omitidos, separadores perdidos).
- **Fecha de control**: toma la fecha más reciente de la columna, no la primera.
- **Títulos de control**: se quita la etiqueta de celda y se canoniza O/0 en
  tokens con dígitos antes de la comparación exacta.

## Diagnóstico

Si un campo de la hoja de control falla, `scripts/diag_control.py` muestra, por
PDF y por página, qué clases se detectan (con confianza), qué página se elige y
qué lee el OCR en las cajas 15/16, y guarda los recortes para inspección:

```bash
python scripts/diag_control.py --pdfs pdfs
```

Principio que guió todo el desarrollo: medir antes de actuar. La matriz de
confusión mostró que el modelo de documentos era perfecto (evitó un reentrenamiento
innecesario) y los recortes guardados revelaron que el No. Doc. era un problema de
PSM, no de detección. Cada vez que se adivinó la causa se falló; cada vez que se
miró el dato real, se resolvió.
