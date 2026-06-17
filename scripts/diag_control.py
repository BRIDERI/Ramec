"""
scripts/diag_control.py - Diagnóstico de la hoja de control en la inferencia.

Para cada PDF de documento, renderiza las primeras páginas, corre el modelo y
muestra QUÉ clases se detectan en cada página (con su confianza), cuál página se
elige como carátula y cuál como control, y qué lee el OCR en las cajas 15 y 16.
Así sabemos si el problema es DETECCIÓN (15/16 no aparecen) o OCR (aparecen pero
no se leen) o SELECCIÓN DE PÁGINA (15/16 están en otra página).

Uso:
    python scripts/diag_control.py --pdfs pdfs --model-doc models/documentos/best.pt
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "configs"))
import classes as C          # noqa: E402
import extract as EX         # noqa: E402
import nomenclatura as NM    # noqa: E402

NUM_CTRL = C.NAME_TO_ID["num_documento_hoja_control"]      # 15
TIT_CTRL = C.NAME_TO_ID["titulo_documento_hoja_control"]   # 16
FEC_CTRL = C.NAME_TO_ID["fecha_ultima_revision_hoja_control"]  # 10
DPI_DOC = 300
N_PAGS = 6


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdfs", required=True)
    ap.add_argument("--model-doc", default=str(ROOT / "models" / "documentos" / "best.pt"))
    ap.add_argument("--base", default=str(ROOT / "base" / "base.json"))
    ap.add_argument("--conf", type=float, default=0.25)
    ap.add_argument("--out-crops", default=str(ROOT / "outputs" / "diag_crops"))
    args = ap.parse_args()

    from ultralytics import YOLO
    from pdf2image import convert_from_path
    model = YOLO(args.model_doc)
    sets_validos, doc_tipo_map = NM.load_base(args.base)

    for p in sorted(Path(args.pdfs).rglob("*.pdf")):
        tipo, *_ = NM.validar_nombre(p, sets_validos, doc_tipo_map)
        if tipo != "DOCUMENTO":
            continue
        print("\n" + "=" * 70)
        print(p.name, f"(tipo={tipo})")
        pages = convert_from_path(str(p), dpi=DPI_DOC, first_page=1, last_page=N_PAGS)
        for i, img in enumerate(pages, 1):
            res = model.predict(img, imgsz=1280, conf=args.conf, verbose=False)[0]
            dets = {}
            if res.boxes is not None:
                for b in res.boxes:
                    cid = int(b.cls)
                    dets[cid] = max(dets.get(cid, 0), float(b.conf))
            etiquetas = ", ".join(f"{C.CLASSES[c]}({dets[c]:.2f})" for c in sorted(dets))
            marca = ""
            if any(c in dets for c in (NUM_CTRL, TIT_CTRL, FEC_CTRL)):
                marca = "  <-- tiene clases de CONTROL"
            print(f"  pág {i}: {etiquetas or '(nada)'}{marca}")

            # si esta página tiene 15 o 16, mostrar qué lee el OCR y GUARDAR el recorte
            if NUM_CTRL in dets or TIT_CTRL in dets:
                res2 = model.predict(img, imgsz=1280, conf=args.conf, verbose=False)[0]
                best = {}
                for b in res2.boxes:
                    cid = int(b.cls); conf = float(b.conf)
                    if cid not in best or conf > best[cid][1]:
                        best[cid] = (tuple(b.xywhn[0].tolist()), conf)
                outdir = Path(args.out_crops)
                outdir.mkdir(parents=True, exist_ok=True)
                if NUM_CTRL in best:
                    crop = EX.crop_box(img, best[NUM_CTRL][0])
                    crop.save(outdir / f"{p.stem}_15_numdoc.png")
                    print(f"        [15 num_ctrl] OCR variantes -> {EX.ocr_variants(crop, psm=6)}")
                    print(f"        [15 num_ctrl] recorte guardado ({crop.size[0]}x{crop.size[1]}px)")
                if TIT_CTRL in best:
                    crop = EX.crop_box(img, best[TIT_CTRL][0])
                    crop.save(outdir / f"{p.stem}_16_titulo.png")
                    print(f"        [16 tit_ctrl] OCR -> {[t.strip()[:60] for t in EX.ocr_variants(crop, psm=6)]}")


if __name__ == "__main__":
    main()
