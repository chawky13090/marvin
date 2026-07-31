"""Création DOCX et conversions documentaires natives de Marvin."""

from __future__ import annotations

import asyncio
import os
import re as _re
import tempfile
from pathlib import Path
from typing import Awaitable, Callable

from office_packages import validate_office_package
from document_formatting import (
    markdown_inline_to_reportlab as _md_inline_to_rl,
    parse_markdown_blocks as _parse_md_blocks,
)
from document_profile import get_identity as _document_identity
from document_profile import TEMPLATES
import database as db
from platform_paths import PATHS as _SYSTEM_PATHS


_resolver: Callable[[str], str] | None = None
_text_generator: Callable[..., Awaitable[object]] | None = None
_generated_dir: Path | None = None


def configure(*, resolve_path: Callable[[str], str]) -> None:
    global _resolver
    _resolver = resolve_path


def configure_generation(
    *,
    text_generator: Callable[..., Awaitable[object]],
    generated_dir: Path,
) -> None:
    global _text_generator, _generated_dir
    _text_generator = text_generator
    _generated_dir = generated_dir.resolve()


async def _generate_text(*args, **kwargs) -> str:
    if _text_generator is None:
        raise RuntimeError("Le générateur documentaire n'est pas configuré")
    return await _text_generator(*args, **kwargs)


async def _generate_with_provenance(*args, **kwargs) -> tuple[str, dict]:
    generated = await _generate_text(*args, return_metadata=True, **kwargs)
    if isinstance(generated, dict):
        text = str(generated.get("text") or "")
        provenance = {
            key: generated[key]
            for key in (
                "model",
                "provider",
                "privacy_preset",
                "cloud_only",
            )
            if key in generated
        }
        return text, provenance
    return str(generated or ""), {}


def _documents_output_dir() -> Path:
    if _generated_dir is None:
        raise RuntimeError("Le dossier documentaire n'est pas configuré")
    _generated_dir.mkdir(parents=True, exist_ok=True)
    return _generated_dir


def _resolve_path(raw: str) -> str:
    if _resolver is None:
        raise RuntimeError("Le domaine documents n'est pas configuré")
    return _resolver(raw)


_LOGO_CACHE_MAX_WIDTH = 400


def _optimized_logo_path(raw_path: str) -> str:
    """Redimensionne/compresse le logo une fois et réutilise le cache tant que la source ne change pas.

    Un logo brut non compressé (plusieurs Mo) embarqué tel quel dans chaque
    document généré fait exploser la taille des DOCX/PDF pour un rendu
    identique (affiché à ~1 cm de haut). On met en cache une version réduite.
    """
    try:
        source = Path(raw_path)
        stat = source.stat()
        cache_dir = _documents_output_dir() / ".logo_cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_path = cache_dir / f"{source.stem}_{int(stat.st_mtime)}_{stat.st_size}.png"
        if cache_path.exists():
            return str(cache_path)
        from PIL import Image as _PILLogo

        with _PILLogo.open(source) as img:
            img = img.convert("RGBA") if img.mode not in ("RGB", "RGBA") else img
            if img.width > _LOGO_CACHE_MAX_WIDTH:
                ratio = _LOGO_CACHE_MAX_WIDTH / img.width
                img = img.resize((_LOGO_CACHE_MAX_WIDTH, max(1, round(img.height * ratio))), _PILLogo.LANCZOS)
            img.save(cache_path, format="PNG", optimize=True)
        return str(cache_path)
    except Exception:
        return raw_path


def _markdown_cell(value: str) -> str:
    return value.replace("\\", "\\\\").replace("|", "\\|").replace("\r", "").replace("\n", "<br>")


def _paragraph_markdown(paragraph) -> str:
    text = paragraph.text.strip()
    if not text:
        return ""
    style_name = (paragraph.style.name or "") if paragraph.style else ""
    style_id = (paragraph.style.style_id or "") if paragraph.style else ""
    style = f"{style_name} {style_id}".casefold()
    heading = _re.search(r"(?:heading|titre)\s*([1-9])", style)
    if heading:
        return f"{'#' * min(int(heading.group(1)), 6)} {text}"
    if "list" in style or "bullet" in style or "puce" in style:
        return f"- {text}"
    return text


def _table_markdown(table) -> list[str]:
    if not table.rows:
        return []
    header = [_markdown_cell(cell.text.strip()) for cell in table.rows[0].cells]
    lines = ["| " + " | ".join(header) + " |"]
    lines.append("| " + " | ".join("---" for _ in header) + " |")
    for row in table.rows[1:]:
        values = [_markdown_cell(cell.text.strip()) for cell in row.cells]
        lines.append("| " + " | ".join(values) + " |")
    return lines


def _extract_docx(path: Path, *, markdown: bool) -> tuple[str, int, int]:
    from docx import Document
    from docx.table import Table

    validate_office_package(path, suffix=".docx", marker="word/document.xml")
    document = Document(path)
    lines: list[str] = []
    total = 0
    maximum = 2_000_000
    for block in document.iter_inner_content():
        if isinstance(block, Table):
            block_lines = (
                _table_markdown(block)
                if markdown
                else [
                    " | ".join(cell.text.strip() for cell in row.cells)
                    for row in block.rows
                ]
            )
        else:
            block_lines = [
                _paragraph_markdown(block) if markdown else block.text.strip()
            ]
        for line in block_lines:
            total += len(line) + 1
            if total > maximum:
                raise ValueError("Texte DOCX extrait limité à 2 000 000 caractères.")
            lines.append(line)
    return "\n".join(lines).strip(), len(document.paragraphs), len(document.tables)


async def extract_docx_text(args: dict) -> dict:
    raw_path = args.get("path")
    if not isinstance(raw_path, str) or not raw_path.strip():
        return {"error": "Paramètre 'path' requis."}
    output_value = args.get("output_path")
    if output_value is not None and not isinstance(output_value, str):
        return {"error": "Paramètre 'output_path' invalide."}
    output_value = str(output_value or "").strip()
    target_format = str(args.get("format") or "markdown").strip().lower()
    if target_format not in {"markdown", "text"}:
        return {"error": "Format attendu : markdown | text."}
    try:
        path = Path(_resolve_path(raw_path.strip()))
        text, paragraphs, tables = await asyncio.to_thread(
            _extract_docx,
            path,
            markdown=target_format == "markdown",
        )
        saved: Path | None = None
        if output_value:
            saved = Path(_resolve_path(output_value))
            if saved.suffix.casefold() not in {".txt", ".md", ".markdown"}:
                return {"error": "La sortie texte doit utiliser .txt, .md ou .markdown."}
            saved.parent.mkdir(parents=True, exist_ok=True)
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{saved.stem}.",
                suffix=saved.suffix,
                dir=str(saved.parent),
            )
            os.close(descriptor)
            temporary = Path(temporary_name)
            try:
                temporary.write_text(text, encoding="utf-8")
                os.replace(temporary, saved)
            finally:
                temporary.unlink(missing_ok=True)
    except FileNotFoundError as exc:
        return {"error": str(exc)}
    except (OSError, ValueError) as exc:
        return {"error": f"Extraction Word échouée : {exc}"}
    return {
        "success": True,
        "text": text[:8_000],
        "truncated": len(text) > 8_000,
        "paragraphs": paragraphs,
        "tables": tables,
        "path": str(saved) if saved else None,
        "message": f"Word extrait ({paragraphs} paragraphes, {tables} tableau(x))",
    }


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
                            hp.add_run().add_picture(_optimized_logo_path(lp), height=Cm(1.3))
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
async def generate(args: dict) -> dict:
    """Génère un document professionnel COMPLET au format Word (.docx) à partir de notes
    brutes, selon un modèle (rapport d'intervention, dossier pro, procédure...). Rédige
    section par section pour un rendu complet et soigné. PDF optionnel."""
    import re as _re
    raw = (args.get("text") or args.get("raw") or args.get("notes") or "").strip()
    tpl_key = (args.get("template") or "libre").strip()
    tpl = TEMPLATES.get(tpl_key, TEMPLATES["libre"])
    if not raw and not args.get("title"):
        return {"error": "Fournis des notes (paramètre 'text') ou au moins un 'title'."}
    title = (args.get("title") or "").strip() or (raw.split("\n")[0][:80] if raw else tpl["name"])

    author = (args.get("author") or "").strip()
    if not author:
        try:
            import learning
            rec = await learning.recall("nom et prénom de l'utilisateur")
            for f in rec.get("facts", []):
                m = _re.search(r"appelle\s+([A-ZÀ-Ÿ][^\s,.;]+)", f)
                if m:
                    author = m.group(1)
                    break
        except Exception:
            pass
        author = author or "Marvin"

    # Contexte optionnel depuis les documents indexés (RAG)
    sources_ctx = ""
    if args.get("use_documents"):
        try:
            import vector_store as vs
            hits = await vs.search(raw or title, collections=["documents"], limit=4)
            sources_ctx = "\n".join(f"- {h['text'][:400]}" for h in hits)
        except Exception:
            pass

    sections = args.get("sections") or tpl["sections"]
    # Mode par défaut piloté par le MODE de performance (rapide sur petite machine, detaille sur puissante)
    mode = (args.get("mode") or db.get_setting("doc_default_mode") or "rapide").lower()
    src_block = (f"\nCONTEXTE (extraits de documents) :\n{sources_ctx}\n" if sources_ctx else "")
    generation_models: set[str] = set()
    generation_provenance: dict = {}

    if mode == "detaille":
        # Section par section : plus complet/profond, mais plusieurs appels LLM (lent sur petit GPU).
        md_parts = []
        for section in sections[:8]:
            prompt = (
                f"Tu es un rédacteur professionnel francophone. Document de type « {tpl['name']} » "
                f"intitulé « {title} ». Rédige UNIQUEMENT la section « {section} », COMPLÈTE et "
                f"professionnelle, en français sans fautes. Commence par « ## {section} ». "
                f"Sous-titres/listes/tableaux si utile, reste factuel.\n\n"
                f"NOTES :\n{raw or '(peu d éléments — propose un contenu plausible)'}\n" + src_block + "\nRÉDACTION :"
            )
            try:
                generated, provenance = await _generate_with_provenance(
                    prompt, model=args.get("model"), timeout=180
                )
                part = generated.strip()
                if provenance.get("model"):
                    generation_models.add(str(provenance["model"]))
                    generation_provenance = provenance
            except Exception as e:
                part = f"## {section}\n\n(génération échouée : {str(e)[:80]})"
            if "##" not in part[:60]:
                part = f"## {section}\n\n" + part
            md_parts.append(part)
        content = f"# {title}\n\n" + "\n\n".join(md_parts)
    else:
        # Une seule passe : génère tout le document d'un coup (rapide).
        sec_list = "\n".join(f"## {s}" for s in sections)
        prompt = (
            f"Tu es un rédacteur professionnel francophone. Rédige un document COMPLET de type "
            f"« {tpl['name']} » intitulé « {title} », en français impeccable (sans fautes), au format markdown.\n"
            f"Respecte EXACTEMENT cette structure (une section « ## » par titre, dans l'ordre) :\n{sec_list}\n"
            f"Chaque section doit être complète et professionnelle (sous-titres, listes ou tableaux si utile). "
            f"Reste factuel, pas de remplissage.\n\n"
            f"NOTES / ÉLÉMENTS FOURNIS :\n{raw or '(peu d éléments — propose un contenu plausible)'}\n"
            + src_block + "\nDOCUMENT COMPLET (markdown) :"
        )
        try:
            generated, generation_provenance = await _generate_with_provenance(
                prompt, model=args.get("model"), timeout=240
            )
            body = generated.strip()
            if generation_provenance.get("model"):
                generation_models.add(str(generation_provenance["model"]))
        except Exception as e:
            return {"error": f"Génération échouée : {str(e)[:120]}"}
        content = body if body.lstrip().startswith("#") else f"# {title}\n\n{body}"

    # ── En-tête / signature / références — CHOISIS par le rédacteur ──────────────
    saved_lh = db.get_setting("doc_letterhead")
    if isinstance(saved_lh, str):
        try:
            import json as _j; saved_lh = _j.loads(saved_lh)
        except Exception:
            saved_lh = {}
    saved_lh = saved_lh if isinstance(saved_lh, dict) else {}
    lh_arg = args.get("letterhead") if isinstance(args.get("letterhead"), dict) else {}
    letterhead = {**saved_lh, **lh_arg} if args.get("include_header", True) else {}
    references = {"client": (args.get("client") or "").strip(), "reference": (args.get("reference") or "").strip()}
    signature = {}
    if args.get("sign") or args.get("lieu"):
        signature = {"name": (args.get("signataire") or saved_lh.get("signataire_name") or author),
                     "title": (args.get("signataire_title") or saved_lh.get("signataire_title") or ""),
                     "lieu": (args.get("lieu") or "").strip()}

    safe = (_re.sub(r"[^\w\- ]", "", title)[:50].strip() or "document").replace(" ", "_")
    out_dir = _documents_output_dir()
    out_path = str(out_dir / f"{safe}.docx")
    r = await create_docx({"path": out_path, "title": title, "subtitle": tpl["name"],
                                        "content": content, "author": author,
                                        "letterhead": letterhead, "references": references, "signature": signature})
    if r.get("error"):
        return {"error": f"Rendu Word échoué : {r['error']}"}
    docx_path = r.get("path", out_path)
    # Sidecar : permet d'affiner une section plus tard (document_refine_section)
    try:
        import json as _json
        meta = {"title": title, "subtitle": tpl["name"], "template": tpl_key, "author": author,
                "letterhead": letterhead, "references": references, "signature": signature,
                "sections": sections, "markdown": content,
                "generation": {**generation_provenance, "models": sorted(generation_models)}}
        with open(docx_path + ".meta.json", "w", encoding="utf-8") as _mf:
            _json.dump(meta, _mf, ensure_ascii=False)
    except Exception:
        pass
    result = {"success": True, "file": docx_path, "title": title, "template": tpl["name"],
              "author": author, "sections": sections, "markdown": content[:4000],
              "message": f"📄 Document « {title} » généré ({len(sections)} sections) → {os.path.basename(docx_path)}"}
    if generation_provenance:
        result["generation"] = {
            **generation_provenance,
            "models": sorted(generation_models),
        }
    if args.get("pdf"):
        try:
            pr = await convert_docx_to_pdf({"path": docx_path})
            if pr.get("success"):
                result["pdf"] = pr.get("path")
        except Exception:
            pass
    return result
async def create_pdf(args: dict) -> dict:
    """Crée un fichier PDF avec du texte formaté (sans Word requis)."""
    _path_raw = args.get("path", "")
    path = _resolve_path(_path_raw) if _path_raw else str(Path(_SYSTEM_PATHS["desktop"]) / f"document_{int(time.time())}.pdf")
    title = args.get("title", "Document")
    content = args.get("content", "")
    _identity = _document_identity()
    author = args.get("author") or _identity.get("author") or "Marvin"
    header = args.get("header") or {k: _identity[k] for k in
                                      ("org", "address", "phone", "email", "website", "logo")
                                      if _identity.get(k)}
    footer_text = args.get("footer_text") or _identity.get("footer_text") or ""
    confidentiality = args.get("confidentiality") or _identity.get("confidentiality") or ""
    want_toc = bool(args.get("toc"))

    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import cm
        from reportlab.lib import colors
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable, Image as RLImage, PageBreak
        from reportlab.platypus.tableofcontents import TableOfContents
        from reportlab.pdfgen import canvas as _canvas_mod
        from reportlab.lib.enums import TA_CENTER, TA_LEFT

        GOLD_COLOR = colors.HexColor("#c9a84c")
        TEXT_COLOR = colors.HexColor("#1a1a1a")
        LIGHT_COLOR = colors.HexColor("#555555")

        out = Path(path)
        if not out.suffix:
            out = out.with_suffix(".pdf")
        out.parent.mkdir(parents=True, exist_ok=True)

        # v2.174 — sommaire (TOC) : nécessite d'intercepter chaque titre h1/h2 rendu
        # (afterFlowable) pour poser un signet + une entrée TOC avec son VRAI numéro de page
        # (connu seulement après mise en page) — SimpleDocTemplate.afterFlowable() est un
        # no-op par défaut, d'où la sous-classe.
        class _TocDocTemplate(SimpleDocTemplate):
            def build(self, flowables, **kw):
                # multiBuild() refait plusieurs passes jusqu'à ce que les entrées TOC notifiées
                # soient IDENTIQUES d'une passe à l'autre — sans ce reset, les clés de signet
                # ("tocentry1", "tocentry2"...) continuaient de s'incrémenter à chaque passe et
                # ne convergeaient jamais ("Index entries not resolved after 10 passes").
                self._toc_seq = 0
                SimpleDocTemplate.build(self, flowables, **kw)

            def afterFlowable(self, flowable):
                try:
                    if isinstance(flowable, Paragraph):
                        style_name = getattr(flowable.style, "name", "")
                        if style_name in ("h1", "h2"):
                            text = flowable.getPlainText()
                            level = 0 if style_name == "h1" else 1
                            self._toc_seq = getattr(self, "_toc_seq", 0) + 1
                            key = f"tocentry{self._toc_seq}"
                            self.canv.bookmarkPage(key)
                            self.canv.addOutlineEntry(text, key, level=level, closed=False)
                            self.notify("TOCEntry", (level, text, self.page, key))
                except Exception:
                    pass

        doc = _TocDocTemplate(
            str(out), pagesize=A4,
            rightMargin=2.5*cm, leftMargin=2.5*cm,
            topMargin=(3.4*cm if header else 2.5*cm), bottomMargin=2.5*cm,
            title=title, author=author,
        )

        from reportlab.platypus import Table, TableStyle, ListFlowable, ListItem
        from datetime import datetime as _dt
        accent = args.get("accent")
        if accent:
            try: GOLD_COLOR = colors.HexColor(accent if accent.startswith("#") else "#" + accent)
            except Exception: pass
        subtitle = args.get("subtitle", "")

        styles = getSampleStyleSheet()
        story = []

        # Styles personnalisés
        h0_style = ParagraphStyle("h0", parent=styles["Title"], textColor=GOLD_COLOR, fontSize=24, spaceAfter=6, alignment=TA_CENTER)
        sub_style = ParagraphStyle("sub", parent=styles["Normal"], textColor=LIGHT_COLOR, fontSize=12, alignment=TA_CENTER, spaceAfter=2)
        meta_style = ParagraphStyle("meta", parent=styles["Normal"], textColor=colors.HexColor("#999999"), fontSize=9, alignment=TA_CENTER, spaceAfter=12)
        h1_style = ParagraphStyle("h1", parent=styles["Heading1"], textColor=GOLD_COLOR, fontSize=16, spaceAfter=6, spaceBefore=16)
        h2_style = ParagraphStyle("h2", parent=styles["Heading2"], textColor=GOLD_COLOR, fontSize=13, spaceAfter=5, spaceBefore=12)
        h3_style = ParagraphStyle("h3", parent=styles["Heading3"], textColor=TEXT_COLOR, fontSize=11, spaceAfter=4, spaceBefore=8)
        body_style = ParagraphStyle("body", parent=styles["Normal"], textColor=TEXT_COLOR, fontSize=10.5, leading=15, spaceAfter=5)
        bullet_style = ParagraphStyle("bullet", parent=body_style, leftIndent=16, spaceAfter=2)
        quote_style = ParagraphStyle("quote", parent=body_style, leftIndent=16, textColor=LIGHT_COLOR, fontName="Helvetica-Oblique", borderPadding=4)
        code_style = ParagraphStyle("code", parent=styles["Code"], fontSize=9, backColor=colors.HexColor("#f5f5f5"), borderPadding=6, leading=12)
        hmap = {"h1": h1_style, "h2": h2_style, "h3": h3_style}

        # ── Bloc de titre ────────────────────────────────────────────────────
        # v2.183 -- avec `toc=True`, le titre est forcé sur sa PROPRE page (PageBreak juste
        # avant le Sommaire) : sans ce spacer, le bloc titre restait collé en haut avec ~70%
        # de page blanche en dessous (signalé par l'utilisateur : "une ou deux page assez
        # vide"). Un espaceur fixe pousse le bloc vers le centre visuel de la page -- pas un
        # centrage exact (la hauteur du Paragraph n'est connue qu'après mise en page), mais
        # suffisant pour ne plus lire comme une page de contenu à moitié vide. Sans `toc`, le
        # titre enchaîne directement sur le corps du document (pas de page dédiée) -> inutile.
        if want_toc:
            story.append(Spacer(1, 8*cm))
        story.append(Paragraph(title, h0_style))
        if subtitle:
            story.append(Paragraph(_md_inline_to_rl(subtitle), sub_style))
        story.append(Paragraph(f"{author} &nbsp;·&nbsp; {_dt.now().strftime('%d/%m/%Y')}", meta_style))
        story.append(HRFlowable(width="100%", thickness=1.5, color=GOLD_COLOR, spaceAfter=14))

        # ── Sommaire (rempli automatiquement via afterFlowable ci-dessus, résolu par le
        # 2e passage de doc.multiBuild) ──────────────────────────────────────────────
        if want_toc:
            story.append(PageBreak())
            story.append(Paragraph("Sommaire", h1_style))
            toc = TableOfContents()
            toc.levelStyles = [
                ParagraphStyle("TOCH1", fontName="Helvetica-Bold", fontSize=11, leftIndent=0,
                               firstLineIndent=0, spaceBefore=8, leading=16, textColor=TEXT_COLOR),
                ParagraphStyle("TOCH2", fontName="Helvetica", fontSize=9.5, leftIndent=16,
                               firstLineIndent=0, spaceBefore=2, leading=13, textColor=LIGHT_COLOR),
            ]
            story.append(toc)
            story.append(PageBreak())

        # v2.172 — les blocs "dessin de boîte" (═ ║ ╔ ╗ ┌ ┐ ...) n'ont AUCUN glyphe dans
        # les polices PDF standard (Courier/Helvetica, encodage WinAnsi) : reportlab les
        # remplace par des carrés noirs pleins (illisible). Détectés via leur plage Unicode
        # (U+2500-257F) et rendus en image PNG (police Consolas, glyphes Unicode complets)
        # plutôt qu'en Paragraph texte — seul moyen fiable de préserver l'alignement ASCII.
        _box_drawing_re = _re.compile(r"[─-╿]")
        _tmp_art_files = []

        # v2.173 — emoji trouvés en conditions réelles dans des schémas ASCII (✅❌🌍🔴🟢, statuts
        # de matrice VLAN + icônes de nœud) : Consolas ne les couvre pas non plus -> même tofu
        # que les caractères de dessin de boîte à l'origine du bug v2.172. Remplacement 1-pour-1
        # (jamais multi-caractères) pour ne PAS décaler l'alignement des colonnes/bordures.
        _EMOJI_ASCII_MAP = {"✅": "V", "❌": "X", "⚠️": "!", "⚠": "!", "🌍": "*", "🔴": "*",
                             "🟢": "*", "🟡": "*", "🔵": "*", "⭐": "*", "🎓": "*", "✔": "V", "✖": "X"}

        def _sanitize_for_font(text: str, font) -> str:
            cache = {}
            out = []
            for ch in text:
                if ch == "\n" or ch.isspace():
                    out.append(ch); continue
                repl = cache.get(ch)
                if repl is None:
                    repl = _EMOJI_ASCII_MAP.get(ch)
                    if repl is None:
                        bbox = font.getmask(ch).getbbox()
                        repl = ch if bbox is not None else " "
                    cache[ch] = repl
                out.append(repl)
            return "".join(out)

        def _render_ascii_art_image(text: str):
            from PIL import Image as _PILImage, ImageDraw, ImageFont
            import uuid as _uuid
            font_size = 20
            font = None
            for fname in ("consola.ttf", "lucon.ttf", "cour.ttf"):
                try:
                    font = ImageFont.truetype(fname, font_size)
                    break
                except Exception:
                    continue
            if font is None:
                font = ImageFont.load_default()
            text = _sanitize_for_font(text, font)
            lines = text.split("\n")
            dummy = _PILImage.new("RGB", (10, 10))
            d = ImageDraw.Draw(dummy)
            bbox_ref = font.getbbox("Hg")
            line_h = (bbox_ref[3] - bbox_ref[1]) + 8
            pad = 20
            max_w = 1
            for ln in lines:
                bb = d.textbbox((0, 0), ln if ln else " ", font=font)
                max_w = max(max_w, bb[2] - bb[0])
            W, H = max_w + pad * 2, line_h * len(lines) + pad * 2
            img = _PILImage.new("RGB", (W, H), "#f5f5f5")
            d = ImageDraw.Draw(img)
            y = pad
            for ln in lines:
                d.text((pad, y), ln, font=font, fill="#1a1a1a")
                y += line_h
            tmp_path = Path(tempfile.gettempdir()) / f"marvin_asciiart_{_uuid.uuid4().hex}.png"
            img.save(tmp_path)
            _tmp_art_files.append(tmp_path)
            return str(tmp_path), W, H

        for kind, payload in _parse_md_blocks(content):
            if kind in hmap:
                story.append(Paragraph(_md_inline_to_rl(payload), hmap[kind]))
            elif kind == "bullet":
                story.append(Paragraph("• " + _md_inline_to_rl(payload), bullet_style))
            elif kind == "num":
                story.append(Paragraph(_md_inline_to_rl(payload), bullet_style))
            elif kind == "quote":
                story.append(Paragraph(_md_inline_to_rl(payload), quote_style))
            elif kind == "image":
                alt, img_rel_path = payload
                resolved_img = _resolve_path(img_rel_path)
                if os.path.exists(resolved_img):
                    try:
                        from PIL import Image as _PILImageCheck
                        with _PILImageCheck.open(resolved_img) as _pi:
                            iw, ih = _pi.size
                        # même garde largeur+hauteur que le fix v2.173 (schémas ASCII) — un
                        # flowable Image ne se scinde jamais sur 2 pages.
                        avail_w, avail_h = doc.width - 12, doc.height - 12
                        scale = min(1.0, avail_w / iw, avail_h / ih)
                        story.append(Spacer(1, 4))
                        story.append(RLImage(resolved_img, width=iw * scale, height=ih * scale))
                        if alt:
                            story.append(Paragraph(_md_inline_to_rl(alt),
                                         ParagraphStyle("imgcap", parent=body_style, fontSize=8.5,
                                                        textColor=LIGHT_COLOR, alignment=TA_CENTER, spaceAfter=4)))
                        story.append(Spacer(1, 8))
                    except Exception:
                        story.append(Paragraph(f"[Image introuvable : {img_rel_path}]", body_style))
                else:
                    story.append(Paragraph(f"[Image introuvable : {img_rel_path}]", body_style))
            elif kind == "code" and _box_drawing_re.search(payload):
                try:
                    img_path, iw, ih = _render_ascii_art_image(payload)
                    # v2.173 — un flowable Image n'est jamais scindé sur 2 pages : contraindre
                    # aussi par la HAUTEUR (pas seulement la largeur, bug trouvé en conditions
                    # réelles) sous peine de LayoutError "too large on page" sur un schéma haut.
                    # -12pt de marge de sécurité = padding par défaut du frame reportlab (6pt x2).
                    avail_w, avail_h = doc.width - 12, doc.height - 12
                    scale = min(1.0, avail_w / iw, avail_h / ih)
                    story.append(Spacer(1, 4))
                    story.append(RLImage(img_path, width=iw * scale, height=ih * scale))
                    story.append(Spacer(1, 8))
                except Exception:
                    story.append(Paragraph(payload.replace("&", "&amp;").replace("<", "&lt;").replace("\n", "<br/>"), code_style))
            elif kind == "code":
                story.append(Paragraph(payload.replace("&", "&amp;").replace("<", "&lt;").replace("\n", "<br/>"), code_style))
            elif kind == "hr":
                story.append(HRFlowable(width="100%", thickness=0.5, color=LIGHT_COLOR, spaceBefore=6, spaceAfter=6))
            elif kind == "table" and payload:
                cols = max(len(r) for r in payload)
                data = [[Paragraph(_md_inline_to_rl(c if c else ""),
                                   ParagraphStyle("tc", parent=body_style, fontSize=9.5, textColor=(colors.white if ri == 0 else TEXT_COLOR)))
                         for c in (row + [""] * (cols - len(row)))]
                        for ri, row in enumerate(payload)]
                t = Table(data, hAlign="LEFT")
                t.setStyle(TableStyle([
                    ("BACKGROUND", (0, 0), (-1, 0), GOLD_COLOR),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#faf8f2")]),
                    ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#dddddd")),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 7), ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                    ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ]))
                story.append(Spacer(1, 4)); story.append(t); story.append(Spacer(1, 8))
            elif kind == "space":
                story.append(Spacer(1, 6))
            else:
                story.append(Paragraph(_md_inline_to_rl(payload), body_style))

        # ── En-tête personnalisé + pied de page (texte libre + confidentialité + "Page X / Y")
        # Recette standard reportlab "NumberedCanvas" : le total de pages n'est connu qu'APRÈS
        # la mise en page complète -> on bufferise chaque page (showPage) et on ne dessine
        # vraiment qu'au save(), une fois le total connu.
        class _NumberedCanvas(_canvas_mod.Canvas):
            def __init__(self, *a, **kw):
                _canvas_mod.Canvas.__init__(self, *a, **kw)
                self._saved_states = []

            def showPage(self):
                self._saved_states.append(dict(self.__dict__))
                self._startPage()

            def save(self):
                total = len(self._saved_states)
                for state in self._saved_states:
                    self.__dict__.update(state)
                    self._draw_decorations(total)
                    _canvas_mod.Canvas.showPage(self)
                _canvas_mod.Canvas.save(self)

            def _draw_decorations(self, total):
                self.saveState()
                if header:
                    x, y = 2.5 * cm, A4[1] - 1.3 * cm
                    logo = header.get("logo")
                    if logo:
                        lp = _resolve_path(logo)
                        if os.path.exists(lp):
                            try:
                                self.drawImage(_optimized_logo_path(lp), x, y - 0.55 * cm, height=1.1 * cm,
                                                preserveAspectRatio=True, mask="auto")
                                x += 1.6 * cm
                            except Exception:
                                pass
                    if header.get("org"):
                        self.setFont("Helvetica-Bold", 11)
                        self.setFillColor(GOLD_COLOR)
                        self.drawString(x, y, header["org"])
                    info = "  ·  ".join(v for v in [header.get("address"), header.get("phone"),
                                                     header.get("email"), header.get("website")] if v)
                    if info:
                        self.setFont("Helvetica", 7)
                        self.setFillColor(colors.HexColor("#888888"))
                        self.drawString(x, y - 0.4 * cm, info)
                    self.setStrokeColor(GOLD_COLOR)
                    self.setLineWidth(0.8)
                    self.line(2.5 * cm, A4[1] - 2.9 * cm, A4[0] - 2.5 * cm, A4[1] - 2.9 * cm)
                self.setFont("Helvetica", 8)
                self.setFillColor(colors.HexColor("#999999"))
                foot_line = "  ·  ".join(v for v in [footer_text, confidentiality] if v)
                if foot_line:
                    self.drawCentredString(A4[0] / 2, 1.55 * cm, foot_line)
                self.drawCentredString(A4[0] / 2, 1.2 * cm, f"Page {self.getPageNumber()} / {total}")
                self.drawRightString(A4[0] - 2.5 * cm, 1.2 * cm, title[:50])
                self.restoreState()

        if want_toc:
            doc.multiBuild(story, canvasmaker=_NumberedCanvas)
        else:
            doc.build(story, canvasmaker=_NumberedCanvas)
        for _p in _tmp_art_files:
            try:
                Path(_p).unlink(missing_ok=True)
            except Exception:
                pass
        return {"success": True, "message": f"PDF créé : {out}", "path": str(out)}
    except Exception as e:
        return {"error": str(e)}
