"""Tests for smartcrop.imaging — the rewritten (skimage-free) processing module."""
from __future__ import annotations

import cv2
import numpy as np
import pytest

import imaging


def _page_bgr(w=600, h=800, with_text=True):
    """White page with a centred block of black 'text' bars (BGR uint8)."""
    img = np.full((h, w, 3), 255, np.uint8)
    if with_text:
        for row in range(120, 680, 26):
            for x in range(90, 510, 70):
                cv2.rectangle(img, (x, row), (x + 46, row + 12), (0, 0, 0), -1)
    return img


# --------------------------------------------------------------- Sauvola threshold
class TestSauvola:
    def test_shape_and_dtype(self):
        g = np.random.default_rng(0).integers(0, 256, (64, 80), dtype=np.uint8)
        thr = imaging._sauvola_threshold(g, 25, 0.11)
        assert thr.shape == g.shape
        assert thr.dtype == np.float64

    def test_separates_ink_from_paper(self):
        g = _page_bgr()[:, :, 0]                       # grayscale-ish (white + black)
        thr = imaging._sauvola_threshold(g, 31, 0.11)
        ink = g < thr
        assert ink.any()                               # some pixels below threshold (ink)
        assert (~ink).any()                            # and some above (paper)

    def test_even_window_is_forced_odd(self):
        g = np.full((40, 40), 200, np.uint8)
        # must not raise on an even window_size
        assert imaging._sauvola_threshold(g, 30, 0.1).shape == g.shape


# --------------------------------------------------------------- bilevel cleaning
class TestCleanBilevel:
    @pytest.mark.parametrize("strength", [1, 2, 3])
    def test_output_is_strict_bilevel(self, strength):
        out = imaging.clean_document_bilevel(_page_bgr(), strength=strength, upscale=1.0)
        assert out.dtype == np.uint8 and out.ndim == 2
        assert set(np.unique(out)).issubset({0, 255})
        assert (out == 0).any() and (out == 255).any()

    def test_shape_preserved_with_upscale(self):
        page = _page_bgr(640, 480)
        out = imaging.clean_document_bilevel(page, strength=2, upscale=2.0)
        assert out.shape == page.shape[:2]
        assert set(np.unique(out)).issubset({0, 255})

    def test_blank_page_has_no_ink(self):
        out = imaging.clean_document_bilevel(_page_bgr(with_text=False), strength=2, upscale=1.0)
        assert (out == 255).all()

    def test_dpi_scaling_runs(self):
        out = imaging.clean_document_bilevel(_page_bgr(), strength=2, dpi=300.0, upscale=1.0)
        assert out.shape == (800, 600)

    def test_preserve_mask_keeps_grayscale(self):
        page = _page_bgr()
        mask = np.zeros((800, 600), np.uint8)
        mask[300:500, 200:400] = 255                   # protect a region from bilevel
        out = imaging.clean_document_bilevel(page, strength=2, upscale=1.0, preserve_mask=mask)
        assert out.shape == (800, 600)


# --------------------------------------------------------------- grayscale sharpen
def test_sharpen_grayscale_returns_single_channel():
    out = imaging.sharpen_grayscale(_page_bgr())
    assert out.dtype == np.uint8 and out.ndim == 2
    assert out.shape == (800, 600)


# --------------------------------------------------------------- deskew
class TestDeskew:
    def test_tiny_angle_is_passthrough(self):
        img = _page_bgr()
        assert imaging.deskew(img, 0.0) is img

    def test_estimate_then_deskew_straightens(self):
        straight = _page_bgr()[:, :, 0]
        m = cv2.getRotationMatrix2D((300, 400), 7.0, 1.0)
        skewed = cv2.warpAffine(straight, m, (600, 800), borderValue=255)
        est = imaging.estimate_skew(skewed)
        assert abs(est) >= 1.0                          # detects a real skew
        fixed = imaging.deskew(skewed, est)
        assert abs(imaging.estimate_skew(fixed)) < abs(est)   # straighter afterwards

    def test_deskew_auto_returns_image_and_angle(self):
        out, ang = imaging.deskew_auto(_page_bgr())
        assert out.shape == (800, 600, 3)
        assert isinstance(ang, float)


# --------------------------------------------------------------- content box
class TestContentBox:
    def test_tight_box_around_ink(self):
        page = np.full((400, 400), 255, np.uint8)
        page[120:280, 100:300] = 0                      # solid ink block
        box = imaging.content_box(page)
        assert box is not None
        x0, y0, x1, y1 = box
        assert 90 <= x0 <= 110 and 110 <= y0 <= 130
        assert 290 <= x1 <= 310 and 270 <= y1 <= 290

    def test_blank_returns_none(self):
        assert imaging.content_box(np.full((200, 200), 255, np.uint8)) is None


# --------------------------------------------------------------- picture mask
class TestPictureMask:
    def test_textured_region_detected(self):
        page = np.full((400, 400, 3), 255, np.uint8)
        noise = np.random.default_rng(1).integers(0, 256, (160, 160, 3), dtype=np.uint8)
        page[120:280, 120:280] = noise                  # photo-like patch
        mask = imaging.detect_picture_mask(page, min_frac=0.01)
        assert mask is not None and mask.shape == (400, 400)
        assert mask.max() == 255

    def test_blank_page_has_no_picture(self):
        blank = np.full((400, 400, 3), 255, np.uint8)
        assert imaging.detect_picture_mask(blank, min_frac=0.01) is None


# --------------------------------------------------------------- dewarp (unwarp)
class TestDewarp:
    def test_unwarp_available_returns_bool(self):
        assert isinstance(imaging.unwarp_available(), bool)

    def test_force_int64_inputs_casts_int32_only(self):
        class FakeSession:
            received = None

            def run(self, names, feed, opts=None):
                self.received = feed
                return ["ok"]

        sess = FakeSession()
        imaging.force_int64_inputs(sess)                 # wraps sess.run
        out = sess.run(None, {"grid": np.zeros((2, 2), np.int32),
                              "x": np.ones((3,), np.float32)})
        assert out == ["ok"]
        assert sess.received["grid"].dtype == np.int64   # int32 → int64
        assert sess.received["x"].dtype == np.float32    # other inputs untouched

    @pytest.mark.skipif(not imaging.unwarp_available(),
                        reason="docuwarp / onnxruntime not installed")
    def test_unwarp_runs_and_preserves_shape(self):
        page = _page_bgr(400, 320)
        out = imaging.unwarp_bgr(page)
        assert out.dtype == np.uint8 and out.ndim == 3
        assert out.shape == page.shape

    @pytest.mark.skipif(imaging.unwarp_available(),
                        reason="docuwarp installed — missing-dep branch can't be exercised")
    def test_unwarp_missing_dependency_raises(self):
        with pytest.raises(RuntimeError):
            imaging.unwarp_bgr(_page_bgr(64, 64))
