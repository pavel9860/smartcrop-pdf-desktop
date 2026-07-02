"""Apply & export: WYSIWYG, compress, colours, formats, settings survive Undo
(spec §12; inv 12, 20, 21, 22)."""
from __future__ import annotations

import fitz
from PIL import Image

from core.enums import FilterMode


def _commit_page0(m, run_job):
    run_job(m.detect_content())
    m.apply_crop()
    m.current_page = 0


# ── inv 12: preview and export are pixel-identical (one render path) ─────────────
def test_preview_matches_exported_png(loaded, run_job, tmp_path):
    m = loaded(2)
    m.set_compress_preset("Original resolution")
    _commit_page0(m, run_job)
    preview = m.view_snapshot().image
    out = tmp_path / "w.png"
    m.set_export_format("PNG")
    run_job(m.export(out))
    written = Image.open(str(tmp_path / "w_001.png"))
    assert written.size == preview.size
    assert written.tobytes() == preview.tobytes()      # WYSIWYG, pixel-for-pixel


# ── inv 20: compress downsamples; Original keeps native ──────────────────────────
def test_compress_downsamples_below_native(loaded, run_job):
    m = loaded(1)
    _commit_page0(m, run_job)
    m.set_compress_preset("Original resolution")
    native = m.view_snapshot().image.size
    m.set_compress_preset("Low — 75 dpi")             # below the 150-dpi native render
    low = m.view_snapshot().image.size
    assert low[0] < native[0] and low[1] < native[1]


# ── inv 22: grayscale desaturates; original colours untouched ────────────────────
def test_grayscale_outputs_single_channel(loaded, run_job):
    m = loaded(1)
    _commit_page0(m, run_job)
    m.set_output_colours("Grayscale")
    img = m.view_snapshot().image
    assert img.mode == "L"
    assert min(img.getdata()) < 250                    # tone preserved, not thresholded
    m.set_output_colours("Original colors")
    assert m.view_snapshot().image.mode == "RGB"


# ── inv 21: export formats ───────────────────────────────────────────────────────
def test_export_pdf_is_one_file_with_all_pages(loaded, run_job, tmp_path):
    m = loaded(3)
    out = tmp_path / "out.pdf"
    run_job(m.export(out))
    assert out.exists()
    d = fitz.open(str(out))
    assert d.page_count == 3
    d.close()


def test_export_split_pdf_multiplies_pages(loaded, run_job, tmp_path):
    m = loaded(3)
    m.set_split(2)
    out = tmp_path / "split.pdf"
    run_job(m.export(out))
    d = fitz.open(str(out))
    assert d.page_count == 6                            # 3 source pages × 2 splits
    d.close()


def test_export_per_page_image_formats(loaded, run_job, tmp_path):
    for fmt, ext in [("JPG", "jpg"), ("PNG", "png"), ("TIFF", "tif")]:
        m = loaded(2)
        m.set_export_format(fmt)
        run_job(m.export(tmp_path / f"{fmt}.{ext}"))   # one file per output page, indexed
        assert (tmp_path / f"{fmt}_001.{ext}").exists()
        assert (tmp_path / f"{fmt}_002.{ext}").exists()


def test_suggested_export_name_uses_postfix_and_folder(loaded):
    m = loaded(1)
    m.set_export_format("JPG")
    m.settings.output_postfix = "_trimmed"
    name, _folder = m.suggested_export_name()
    assert name.endswith("_trimmed.jpg")


# ── PDF embed encoder: JPEG for tone, PNG for bilevel (§12.6) ────────────────────
def _first_embed_ext(path):
    d = fitz.open(str(path))
    xref = d.get_page_images(0)[0][0]
    ext = d.extract_image(xref)["ext"]
    d.close()
    return ext


def test_pdf_embeds_jpeg_for_tone_and_png_for_bilevel(scanned, run_job, tmp_path):
    m = scanned(1)
    run_job(m.export(tmp_path / "tone.pdf"))
    assert _first_embed_ext(tmp_path / "tone.pdf") in ("jpeg", "jpg")
    run_job(m.set_filter_mode(FilterMode.BW))        # B/W page must stay lossless
    run_job(m.export(tmp_path / "bw.pdf"))
    assert _first_embed_ext(tmp_path / "bw.pdf") == "png"


# ── output settings survive Undo (inv 22 corollary; §22) ─────────────────────────
def test_output_settings_survive_undo(loaded, run_job):
    m = loaded(2)
    _commit_page0(m, run_job)
    m.set_compress_preset("Low — 75 dpi")
    m.set_output_colours("Grayscale")
    m.rotate_pages()                                   # a real undoable mutation
    m.undo()
    assert m.compress_preset == "Low — 75 dpi"         # live settings outside History
    assert m.output_colours == "Grayscale"
