"""Création DOCX et conversions documentaires natives de Marvin."""

from __future__ import annotations

import asyncio
import os
import re as _re
from pathlib import Path
from typing import Callable

from document_formatting import parse_markdown_blocks as _parse_md_blocks
from document_profile import get_identity as _document_identity


_resolver: Callable[[str], str] | None = None


def configure(*, resolve_path: Callable[[str], str]) -> None:
    global _resolver
    _resolver = resolve_path


def _resolve_path(raw: str) -> str:
    if _resolver is None:
        raise RuntimeError("Le domaine documents n'est pas configuré")
    return _resolver(raw)


async def create_docx(args: dict) -> dict:
    path = _resolve_path(args.get("path", ""))
    title = args.get("title", "Document")
    subtitle = args.get("subtitle", "")
    content = args.get("content", "")
    _identity = _document_identity()
    author = args.get("author") or _identity.get("author") or "Marvin"
    accent = args.get("accent", "#c9a84c").lstrip("#")
    footer_text = args.get("footer_text") or _identity.get("footer_text") or ""
    confidentiality = args.get("confidentiality") or _identity.get("confidentiality") or ""
    want_toc = bool(args.get("toc"))
    try:
        from docx import Document
        from docx.shared import Pt, RGBColor, Cm
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        from docx.enum.table import WD_TABLE_ALIGNMENT
        from docx.enum.text import WD_BREAK
        from docx.oxml.ns import qn
        from docx.oxml import OxmlElement
        from datetime import datetime as _dt

        ar, ag, ab = int(accent[0:2], 16), int(accent[2:4], 16), int(accent[4:6], 16)
        ACCENT = RGBColor(ar, ag, ab)

        doc = Document()
        # Police par défaut professionnelle
        normal = doc.styles["Normal"]
        normal.font.name = "Calibri"
        normal.font.size = Pt(11)
        doc.core_properties.author = author
        doc.core_properties.title = title
        if want_toc:
            # Word ne recalcule un champ TOC qu'à la demande (clic droit > Mettre à jour) sauf
            # si le document est marqué "à mettre à jour à l'ouverture" — évite un sommaire
            # vide/périmé au premier affichage.
            try:
                settings_el = doc.settings.element
                upd = OxmlElement("w:updateFields"); upd.set(qn("w:val"), "true")
                settings_el.append(upd)
            except Exception:
                pass

        # ── En-tête PERSONNALISABLE (choisi par le rédacteur, sur toutes les pages) ──
        lh = args.get("letterhead") or {k: _identity[k] for k in
                                         ("org", "address", "phone", "email", "website", "logo")
                                         if _identity.get(k)}
        if any(lh.get(k) for k in ("org", "address", "phone", "email", "website", "logo")):
            try:
                hdr = doc.sections[0].header
                hp = hdr.paragraphs[0]
                hp.alignment = WD_ALIGN_PARAGRAPH.LEFT
                logo = lh.get("logo")
                if logo:
                    lp = _resolve_path(logo)
                    if os.path.exists(lp):
                        try:
                            hp.add_run().add_picture(lp, height=Cm(1.3))
                        except Exception:
                            pass
                if lh.get("org"):
                    r = hp.add_run(("   " if hp.runs else "") + lh["org"])
                    r.bold = True; r.font.size = Pt(12); r.font.color.rgb = ACCENT
                info = "  ·  ".join(x for x in [lh.get("address"), lh.get("phone"), lh.get("email"), lh.get("website")] if x)
                if info:
                    ip = hdr.add_paragraph(info)
                    ip.runs[0].font.size = Pt(8); ip.runs[0].font.color.rgb = RGBColor(0x88, 0x88, 0x88)
            except Exception:
                pass

        # ── Page de titre soignée ────────────────────────────────────────────
        h = doc.add_heading(title, level=0)
        h.alignment = WD_ALIGN_PARAGRAPH.CENTER
        for run in h.runs:
            run.font.color.rgb = ACCENT
            run.font.size = Pt(26)
        if subtitle:
            sp = doc.add_paragraph(subtitle); sp.alignment = WD_ALIGN_PARAGRAPH.CENTER
            sp.runs[0].font.size = Pt(13); sp.runs[0].font.color.rgb = RGBColor(0x66, 0x66, 0x66)
        meta = doc.add_paragraph(f"{author}  ·  {_dt.now().strftime('%d/%m/%Y')}")
        meta.alignment = WD_ALIGN_PARAGRAPH.CENTER
        meta.runs[0].font.size = Pt(9); meta.runs[0].font.color.rgb = RGBColor(0x99, 0x99, 0x99)

        # ── Références du document (client, référence) — choisies par le rédacteur ──
        refs = args.get("references") or {}
        ref_line = "      ".join(x for x in [
            (f"Client : {refs['client']}" if refs.get("client") else None),
            (f"Réf. : {refs['reference']}" if refs.get("reference") else None),
        ] if x)
        if ref_line:
            rp = doc.add_paragraph(ref_line); rp.alignment = WD_ALIGN_PARAGRAPH.CENTER
            rp.runs[0].font.size = Pt(9); rp.runs[0].font.color.rgb = RGBColor(0x77, 0x77, 0x77)

        # ── Sommaire (champ TOC natif Word — se recalcule à l'ouverture grâce à
        # updateFields ci-dessus, ou via clic droit > Mettre à jour les champs) ──
        if want_toc:
            doc.add_page_break()
            toc_h = doc.add_heading("Sommaire", level=1)
            for run in toc_h.runs:
                run.font.color.rgb = ACCENT
            toc_p = doc.add_paragraph()
            run = toc_p.add_run()
            fld_begin = OxmlElement("w:fldChar"); fld_begin.set(qn("w:fldCharType"), "begin")
            instr = OxmlElement("w:instrText"); instr.set(qn("xml:space"), "preserve")
            instr.text = 'TOC \\o "1-3" \\h \\z \\u'
            fld_sep = OxmlElement("w:fldChar"); fld_sep.set(qn("w:fldCharType"), "separate")
            placeholder = OxmlElement("w:t")
            placeholder.text = "Clic droit → Mettre à jour les champs pour générer le sommaire."
            fld_end = OxmlElement("w:fldChar"); fld_end.set(qn("w:fldCharType"), "end")
            run._r.append(fld_begin); run._r.append(instr); run._r.append(fld_sep)
            run._r.append(placeholder); run._r.append(fld_end)
            doc.add_page_break()

        def _inline_runs(paragraph, text):
            """Ajoute des runs en interprétant **gras** *italique* `code`."""
            tokens = _re.split(r"(\*\*.+?\*\*|\*.+?\*|`[^`]+`)", text)
            for tok in tokens:
                if not tok:
                    continue
                if tok.startswith("**") and tok.endswith("**"):
                    r = paragraph.add_run(tok[2:-2]); r.bold = True
                elif tok.startswith("`") and tok.endswith("`"):
                    r = paragraph.add_run(tok[1:-1]); r.font.name = "Consolas"; r.font.size = Pt(10)
                elif tok.startswith("*") and tok.endswith("*"):
                    r = paragraph.add_run(tok[1:-1]); r.italic = True
                else:
                    paragraph.add_run(tok)

        for kind, payload in _parse_md_blocks(content):
            if kind in ("h1", "h2", "h3"):
                lvl = {"h1": 1, "h2": 2, "h3": 3}[kind]
                hh = doc.add_heading("", level=lvl); _inline_runs(hh, payload)
                for run in hh.runs:
                    run.font.color.rgb = ACCENT
            elif kind == "bullet":
                _inline_runs(doc.add_paragraph(style="List Bullet"), payload)
            elif kind == "num":
                _inline_runs(doc.add_paragraph(style="List Number"), payload)
            elif kind == "quote":
                q = doc.add_paragraph(); q.paragraph_format.left_indent = Cm(0.8)
                rr = q.add_run(payload); rr.italic = True; rr.font.color.rgb = RGBColor(0x55, 0x55, 0x55)
            elif kind == "image":
                _alt, _img_path = payload
                _resolved_img = _resolve_path(_img_path)
                if os.path.exists(_resolved_img):
                    try:
                        ip = doc.add_paragraph(); ip.alignment = WD_ALIGN_PARAGRAPH.CENTER
                        ip.add_run().add_picture(_resolved_img, width=Cm(15))
                        if _alt:
                            cap = doc.add_paragraph(_alt); cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
                            cap.runs[0].italic = True; cap.runs[0].font.size = Pt(9)
                            cap.runs[0].font.color.rgb = RGBColor(0x77, 0x77, 0x77)
                    except Exception:
                        doc.add_paragraph(f"[Image introuvable : {_img_path}]")
                else:
                    doc.add_paragraph(f"[Image introuvable : {_img_path}]")
            elif kind == "code":
                cp = doc.add_paragraph(); rr = cp.add_run(payload)
                rr.font.name = "Consolas"; rr.font.size = Pt(9)
            elif kind == "hr":
                doc.add_paragraph("─" * 50).runs[0].font.color.rgb = RGBColor(0xCC, 0xCC, 0xCC)
            elif kind == "table" and payload:
                cols = max(len(r) for r in payload)
                tbl = doc.add_table(rows=0, cols=cols); tbl.style = "Light Grid Accent 1"
                tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
                for ri, row in enumerate(payload):
                    cells = tbl.add_row().cells
                    for ci in range(cols):
                        txt = row[ci] if ci < len(row) else ""
                        cells[ci].text = ""
                        _inline_runs(cells[ci].paragraphs[0], txt)
                        if ri == 0:
                            for rn in cells[ci].paragraphs[0].runs:
                                rn.bold = True
            elif kind == "space":
                doc.add_paragraph("")
            else:
                _inline_runs(doc.add_paragraph(), payload)

        # ── Bloc signature (choisi par le rédacteur) ─────────────────────────
        sig = args.get("signature") or {}
        if sig.get("name") or sig.get("lieu"):
            doc.add_paragraph("")
            if sig.get("lieu"):
                lp = doc.add_paragraph(f"Fait à {sig['lieu']}, le {_dt.now().strftime('%d/%m/%Y')}.")
                lp.alignment = WD_ALIGN_PARAGRAPH.RIGHT; lp.runs[0].font.size = Pt(10)
            if sig.get("name"):
                doc.add_paragraph("")
                np = doc.add_paragraph(sig["name"]); np.alignment = WD_ALIGN_PARAGRAPH.RIGHT
                np.runs[0].bold = True
                if sig.get("title"):
                    tp = doc.add_paragraph(sig["title"]); tp.alignment = WD_ALIGN_PARAGRAPH.RIGHT
                    tp.runs[0].font.size = Pt(9); tp.runs[0].font.color.rgb = RGBColor(0x77, 0x77, 0x77)

        # ── Pied de page : texte libre + confidentialité (optionnels) + Page X / Y ──
        try:
            foot_section = doc.sections[0].footer
            foot_line = "  ·  ".join(x for x in [footer_text, confidentiality] if x)
            if foot_line:
                fp = foot_section.paragraphs[0]
                fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
                fr = fp.add_run(foot_line)
                fr.font.size = Pt(8); fr.font.color.rgb = RGBColor(0x99, 0x99, 0x99)
                page_p = foot_section.add_paragraph()
            else:
                page_p = foot_section.paragraphs[0]
            page_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            for instr in ("PAGE", None, "NUMPAGES"):
                if instr is None:
                    page_p.add_run(" / ")
                    continue
                r = page_p.add_run()
                fld = OxmlElement("w:fldSimple"); fld.set(qn("w:instr"), instr)
                r._r.append(fld)
            for r in page_p.runs:
                r.font.size = Pt(8); r.font.color.rgb = RGBColor(0x99, 0x99, 0x99)
        except Exception:
            pass

        p = Path(path)
        if not p.suffix:
            p = p.with_suffix(".docx")
        p.parent.mkdir(parents=True, exist_ok=True)
        doc.save(str(p))
        return {"success": True, "message": f"Document Word créé : {p}", "path": str(p)}
    except Exception as e:
        return {"error": str(e)}


async def convert_docx_to_pdf(args: dict) -> dict:
    path = _resolve_path(args.get("path", ""))
    output_dir = args.get("output_dir", None)
    if output_dir:
        output_dir = _resolve_path(output_dir)
    p = Path(path)
    if not p.exists():
        return {"error": f"Fichier introuvable : {path}"}
    if not p.is_file() or p.suffix.casefold() != ".docx":
        return {"error": "La conversion PDF exige un fichier source .docx."}
    out = Path(output_dir) if output_dir else p.parent
    try:
        out.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return {"error": f"Impossible de préparer le dossier de sortie : {exc}"}

    def _convert_sync():
        # docx2pdf pilote Word via COM (win32com) — nécessite CoInitialize() sur LE THREAD
        # qui l'exécute (sinon "CoInitialize n'a pas été appelé", même piège que system_search).
        import pythoncom
        from docx2pdf import convert
        pythoncom.CoInitialize()
        try:
            convert(str(p), str(out))
        finally:
            pythoncom.CoUninitialize()

    try:
        # v2.138 — trouvé via le nouveau tableau de bord de fiabilité (100% d'échec récent,
        # invisible dans l'audit précédent qui triait par VOLUME, pas par TAUX) : le
        # CoInitialize() ci-dessus était déjà présent (fix v2.106) mais l'erreur persistait.
        # Cause : `asyncio.to_thread` réutilise le pool de threads PARTAGÉ par défaut de
        # FastAPI — un thread du pool peut avoir déjà servi un AUTRE appel COM (ex.
        # system_search) dont l'appartement COM a été refermé (CoUninitialize) de façon
        # incompatible avec une réutilisation ultérieure sur ce même thread. Corrigé : un
        # ThreadPoolExecutor DÉDIÉ à usage unique (1 thread frais, jamais partagé/réutilisé)
        # garantit un appartement COM propre à chaque conversion.
        import concurrent.futures as _cf
        loop = asyncio.get_running_loop()
        with _cf.ThreadPoolExecutor(max_workers=1) as _executor:
            await loop.run_in_executor(_executor, _convert_sync)
        pdf_name = p.stem + ".pdf"
        return {"success": True, "message": f"PDF créé : {out / pdf_name}", "path": str(out / pdf_name)}
    except Exception as e:
        return {"error": f"Erreur conversion PDF : {e}. Vérifiez que Microsoft Word est installé."}


async def convert_format(args: dict) -> dict:
    """Convertit un document déjà généré vers un AUTRE format (docx<->pdf) -- pour laisser le
    choix du format même APRÈS génération, sans faire regénérer le contenu depuis zéro par
    le LLM (risque d'incohérence). docx->pdf réutilise Word (docx2pdf) ; pdf->docx utilise
    pdf2docx (mise en page reconstituée, pas garantie identique à 100% -- normal pour un
    format d'origine non-éditable)."""
    path = _resolve_path(args.get("path", ""))
    p = Path(path)
    if not p.exists():
        return {"error": f"Fichier introuvable : {path}"}
    target = (args.get("target_format") or "").strip(".").lower()
    if target not in ("pdf", "docx"):
        return {"error": "Paramètre 'target_format' requis : 'pdf' ou 'docx'."}
    src_ext = p.suffix.lower().lstrip(".")
    if src_ext == target:
        return {"error": f"Le fichier est déjà au format {target}."}

    if src_ext == "docx" and target == "pdf":
        return await convert_docx_to_pdf({"path": str(p)})

    if src_ext == "pdf" and target == "docx":
        out_path = p.with_suffix(".docx")

        def _convert_sync():
            from pdf2docx import Converter
            cv = Converter(str(p))
            try:
                cv.convert(str(out_path))
            finally:
                cv.close()

        try:
            await asyncio.to_thread(_convert_sync)
            return {"success": True, "message": f"Word créé : {out_path}", "path": str(out_path)}
        except Exception as e:
            return {"error": f"Erreur conversion Word : {e}"}

    return {"error": f"Conversion {src_ext} → {target} non supportée (formats gérés : docx<->pdf)."}
