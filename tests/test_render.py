"""Tests for core.render — the shared crop/resize used by both preview and export.
These guarantee WYSIWYG: the preview path and the export path call the same function."""
from __future__ import annotations

from PIL import Image

from core.geometry import Box
from core.render import crop_to_box, resize_to, output_image, fit_scale, desaturate


def _img(w, h):
    return Image.new("RGB", (w, h), "white")


def test_crop_to_box_maps_page_units_to_pixels():
    img = _img(1000, 2000)                          # render of a 500×1000 page (2 px/unit)
    crop = crop_to_box(img, Box(100, 200, 300, 700), 500, 1000)
    assert crop.size == (400, 1000)                 # (300-100)*2 , (700-200)*2


def test_resize_to_none_is_identity():
    img = _img(120, 80)
    assert resize_to(img, None) is img


def test_resize_to_equal_target_is_noop():
    img = _img(120, 80)
    assert resize_to(img, (120, 80)) is img         # no resample when already the target size


def test_resize_to_changes_size():
    out = resize_to(_img(120, 80), (60, 40))
    assert out.size == (60, 40)


def test_output_image_crop_then_resize_matches_target():
    img = _img(1000, 2000)
    out = output_image(img, Box(0, 0, 500, 1000), 500, 1000, (1080, 1440))
    assert out.size == (1080, 1440)                 # resize wins → preview == export aspect


def test_output_image_original_keeps_native_crop_size():
    img = _img(1000, 2000)
    box = Box(100, 100, 300, 600)
    out = output_image(img, box, 500, 1000, None)     # Original resolution → target None
    assert out.size == crop_to_box(img, box, 500, 1000).size    # native pixels, not downsized


# --------------------------------------------------------------- Output colours (#22)
def test_desaturate_keeps_tone_not_threshold():
    img = Image.new("RGB", (4, 4), (200, 50, 50))
    out = desaturate(img)
    assert out.mode == "L"                            # single channel
    assert 80 <= out.getpixel((0, 0)) <= 110          # luminance kept (~95), not forced to 0/255
    assert desaturate(out) is out                     # already-L passes through


def test_output_image_grayscale_applied_last():
    img = Image.new("RGB", (1000, 2000), (200, 50, 50))
    box = Box(0, 0, 500, 1000)
    colour = output_image(img, box, 500, 1000, (100, 200))
    grey = output_image(img, box, 500, 1000, (100, 200), remove_colours=True)
    assert colour.mode == "RGB" and grey.mode == "L"  # remove_colours desaturates the resized crop
    assert grey.size == colour.size == (100, 200)     # colour removal does not change geometry


def test_fit_scale_picks_limiting_dimension():
    # tall content in a wide canvas → height is limiting
    assert fit_scale(100, 1000, 800, 600, 40) == (600 - 40) / 1000


import pytest


@pytest.mark.parametrize("pw,ph", [(100, 1000), (1000, 100), (800, 600), (612, 792), (2480, 1860)])
@pytest.mark.parametrize("cw,ch", [(400, 400), (1375, 1080), (480, 1200)])
def test_fit_scale_never_overflows_the_window(pw, ph, cw, ch):
    """The fitted page always lands inside the canvas in BOTH axes — it is never magnified out
    of the window border (bug 3: page should always be within the window)."""
    margin = 40
    s = fit_scale(pw, ph, cw, ch, margin)
    assert pw * s <= cw - margin + 1e-6
    assert ph * s <= ch - margin + 1e-6
