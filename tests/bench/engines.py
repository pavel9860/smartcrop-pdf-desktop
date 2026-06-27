"""Enhancement engines for the CPU benchmark.

  DocTr  -> IllTr   (illumination/appearance transformer, inherently tiled @128px)
  DocRes -> Restormer 'appearance' task (whole-image, downscaled <=working; or native tiled)

Each engine exposes:
    .name
    .enhance(bgr_uint8) -> bgr_uint8           # full per-page op (prompt+infer+stitch)
The bench times .enhance() end to end (plus a finer split where cheap).
"""
import os, sys, time, types
import cv2
import numpy as np
import torch

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "vendor"))
MODELS = os.path.join(HERE, "models")

from illtr import IllTr                                  # noqa: E402
from restormer_arch import Restormer                     # noqa: E402
from docres_helpers import (convert_state_dict, stride_integral,  # noqa: E402
                            appearance_prompt)

torch.set_grad_enabled(False)


# --------------------------------------------------------------------------- IllTr
# The repo's PatchEmbed/DePatchEmbed use python per-patch loops (~1k iters/patch,
# ~1k patches/page -> minutes/page). These vectorized drop-ins are numerically
# identical (verified in _selftest) but ~100x faster.
def _patch_embed_fast(self, x):
    N, C, H, W = ori = x.shape
    p = self.patch_size
    RB, CB = H // p, W // p
    t = x.unfold(2, p, p).unfold(3, p, p)        # N,C,RB,CB,p,p
    t = t.permute(0, 3, 2, 1, 4, 5).contiguous()  # N,CB,RB,C,p,p  (k = cb*RB+rb)
    return t.view(N, CB * RB, C * p * p), ori


def _depatch_embed_fast(self, x, ori_shape):
    N, C, H, W = ori_shape
    p = self.patch_size
    RB, CB = H // p, W // p
    t = x.view(N, CB, RB, C, p, p)
    t = t.permute(0, 3, 2, 1, 4, 5).contiguous()  # N,C,RB,CB,p,p
    t = t.permute(0, 1, 2, 4, 3, 5).contiguous()  # N,C,RB,p,CB,p
    return t.view(N, C, RB * p, CB * p)


def _vectorize_illtr(model):
    model.patch_embedding.forward = types.MethodType(_patch_embed_fast, model.patch_embedding)
    model.de_patch_embedding.forward = types.MethodType(_depatch_embed_fast, model.de_patch_embedding)
    return model


def _pad_crop(img, patch=128, ovlp=16):
    """Verbatim DocTr padCropImg: returns totalPatch (ynum,xnum,patch,patch,3), padH, padW."""
    H, W = img.shape[:2]
    step = patch - ovlp
    padH = (int((H - patch) / step + 1) * step + patch) - H
    padW = (int((W - patch) / step + 1) * step + patch) - W
    padImg = cv2.copyMakeBorder(img, 0, padH, 0, padW, cv2.BORDER_REPLICATE)
    ynum = int((padImg.shape[0] - patch) / step) + 1
    xnum = int((padImg.shape[1] - patch) / step) + 1
    tp = np.zeros((ynum, xnum, patch, patch, 3), dtype=np.uint8)
    for j in range(ynum):
        for i in range(xnum):
            x, y = i * step, j * step
            if j == ynum - 1 and i == xnum - 1:
                tp[j, i] = img[-patch:, -patch:]
            elif j == ynum - 1:
                tp[j, i] = img[-patch:, x:x + patch]
            elif i == xnum - 1:
                tp[j, i] = img[y:y + patch, -patch:]
            else:
                tp[j, i] = padImg[y:y + patch, x:x + patch]
    return tp, padH, padW


def _compose(results, img, patch=128, ovlp=16):
    """Verbatim DocTr composePatch (seam-trim stitch)."""
    ynum, xnum = results.shape[:2]
    step = patch - ovlp
    res = np.zeros_like(img).astype("uint8")
    for j in range(ynum):
        for i in range(xnum):
            sy, sx = j * step, i * step
            if j == 0 and i != xnum - 1:
                res[sy:sy + patch, sx:sx + patch] = results[j, i]
            elif i == 0 and j != ynum - 1:
                res[sy + 10:sy + patch, sx:sx + patch] = results[j, i, 10:]
            elif j == ynum - 1 and i == xnum - 1:
                res[-patch + 10:, -patch + 10:] = results[j, i, 10:, 10:]
            elif j == ynum - 1 and i == 0:
                res[-patch + 10:, sx:sx + patch] = results[j, i, 10:]
            elif j == ynum - 1 and i != 0:
                res[-patch + 10:, sx + 10:sx + patch] = results[j, i, 10:, 10:]
            elif i == xnum - 1 and j == 0:
                res[sy:sy + patch, -patch + 10:] = results[j, i, :, 10:]
            elif i == xnum - 1 and j != 0:
                res[sy + 10:sy + patch, -patch + 10:] = results[j, i, 10:, 10:]
            else:
                res[sy + 10:sy + patch, sx + 10:sx + patch] = results[j, i, 10:, 10:]
    res[0, :, :] = 255
    return res


class IllTrEngine:
    """DocTr illumination/appearance. precision: 'fp32' | 'int8' (dynamic-quant Linear)."""
    def __init__(self, precision="fp32", batch=8, threads=None):
        self.precision = precision
        self.batch = batch
        self.name = f"DocTr-IllTr [{precision}, tiled@128]"
        if threads:
            torch.set_num_threads(threads)
        m = IllTr()
        sd = convert_state_dict(torch.load(os.path.join(MODELS, "illtr.pth"), map_location="cpu"))
        m.load_state_dict(sd)
        m.eval()
        _vectorize_illtr(m)
        if precision == "int8":
            m = torch.ao.quantization.quantize_dynamic(m, {torch.nn.Linear}, dtype=torch.qint8)
        self.model = m

    def enhance(self, bgr):
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        tp, padH, padW = _pad_crop(rgb)
        ynum, xnum = tp.shape[:2]
        flat = tp.reshape(-1, 128, 128, 3).astype(np.float32) / 255.0
        ten = torch.from_numpy(flat.transpose(0, 3, 1, 2))          # (P,3,128,128)
        outs = []
        for s in range(0, ten.shape[0], self.batch):
            o = self.model(ten[s:s + self.batch])
            outs.append((o.permute(0, 2, 3, 1).numpy() * 255.0).astype(np.uint8))
        results = np.concatenate(outs, 0).reshape(ynum, xnum, 128, 128, 3)
        out_rgb = _compose(results, rgb)
        return cv2.cvtColor(out_rgb, cv2.COLOR_RGB2BGR)


def _selftest_patch():
    """Assert the vectorized patch embed matches the original loop ordering."""
    p, C, N = 4, 16, 1
    x = torch.randn(N, C, 128, 128)
    RB = CB = 128 // p
    ref = torch.zeros(N, RB * CB, C * p * p)
    i = j = 0
    for k in range(RB * CB):
        if i + p > 128:
            i = 0; j += p
        ref[:, k, :] = x[:, :, i:i + p, j:j + p].flatten(1)
        i += p
    got, ori = _patch_embed_fast(types.SimpleNamespace(patch_size=p), x)
    assert torch.allclose(got, ref), "patch_embed mismatch"
    back = _depatch_embed_fast(types.SimpleNamespace(patch_size=p), got, ori)
    assert torch.allclose(back, x), "depatch_embed roundtrip mismatch"


# ------------------------------------------------------------------------- DocRes
def _build_restormer():
    m = Restormer(inp_channels=6, out_channels=3, dim=48, num_blocks=[2, 3, 3, 4],
                  num_refinement_blocks=4, heads=[1, 2, 4, 8], ffn_expansion_factor=2.66,
                  bias=False, LayerNorm_type="WithBias", dual_pixel_task=True)
    state = convert_state_dict(torch.load(os.path.join(MODELS, "docres.pkl"),
                                          map_location="cpu")["model_state"])
    m.load_state_dict(state)
    m.eval()
    return m


TEST_PDF = os.path.join(HERE, "..", "assets", "test_pdf_scan.pdf")


def _calib_inputs(size, n=8):
    """Realistic (1,6,size,size) float32 inputs for static quant calibration,
    built from the benchmark PDF's own pages (appearance 6ch tensors)."""
    import fitz
    d = fitz.open(TEST_PDF)
    outs = []
    for pi in range(min(len(d), 3)):
        pix = d[pi].get_pixmap(dpi=150)
        a = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, pix.n)
        bgr = cv2.cvtColor(a, cv2.COLOR_RGB2BGR if pix.n == 3 else cv2.COLOR_RGBA2BGR)
        in6 = np.concatenate((bgr, appearance_prompt(bgr)), -1)
        outs.append(cv2.resize(in6, (size, size)))                       # whole-page square
        for _ in range(2):                                               # a couple of crops
            y = np.random.randint(0, max(in6.shape[0] - size, 1))
            x = np.random.randint(0, max(in6.shape[1] - size, 1))
            crop = in6[y:y + size, x:x + size]
            if crop.shape[:2] != (size, size):
                crop = cv2.resize(crop, (size, size))
            outs.append(crop)
    arrs = [c.astype(np.float32).transpose(2, 0, 1)[None] / 255.0 for c in outs[:n]]
    return arrs


def _export_onnx_int8(size):
    """Export Restormer at fixed (1,6,size,size) and statically quantize to INT8 (QDQ).
    Static quant -> QLinearConv (CPU-supported), unlike dynamic -> ConvInteger. Cached."""
    from onnxruntime.quantization import (quantize_static, CalibrationDataReader,
                                          QuantType, QuantFormat)
    fp32 = os.path.join(MODELS, f"docres_{size}.onnx")
    int8 = os.path.join(MODELS, f"docres_{size}.int8.onnx")
    if os.path.exists(int8):
        return int8
    if not os.path.exists(fp32):
        m = _build_restormer()
        torch.onnx.export(m, torch.zeros(1, 6, size, size), fp32, opset_version=17,
                          dynamo=False, input_names=["x"], output_names=["y"])

    class _Reader(CalibrationDataReader):
        def __init__(self):
            self.it = iter([{"x": a} for a in _calib_inputs(size)])
        def get_next(self):
            return next(self.it, None)

    quantize_static(fp32, int8, _Reader(), quant_format=QuantFormat.QDQ,
                    per_channel=True, weight_type=QuantType.QInt8,
                    activation_type=QuantType.QUInt8)
    return int8


class DocResEngine:
    """DocRes appearance.
    mode='resize'  -> official single pass, image resized so long side <= work (fast).
    mode='tile'    -> native-resolution tiled pass (quality, slower).
    precision='fp32' (torch) | 'int8' (onnxruntime dynamic-quant)."""
    def __init__(self, precision="int8", mode="resize", work=1024, tile=256,
                 overlap=32, threads=None):
        self.precision, self.mode, self.work = precision, mode, work
        self.tile, self.overlap = tile, overlap
        self.proc = work if mode == "resize" else tile      # fixed processing square
        tag = mode + (f"@{work}" if mode == "resize" else f"@native,tile{tile}")
        self.name = f"DocRes-appearance [{precision}, {tag}]"
        self.threads = threads or os.cpu_count()
        if precision == "fp32":
            if threads:
                torch.set_num_threads(threads)
            self.model = _build_restormer().float()
            self.sess = None
        else:
            import onnxruntime as ort
            so = ort.SessionOptions()
            so.intra_op_num_threads = self.threads
            so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
            self.sess = ort.InferenceSession(_export_onnx_int8(self.proc), so,
                                             providers=["CPUExecutionProvider"])
            self.model = None

    # -- low level: run one fixed-size 6ch float tile through the active backend
    def _infer(self, x6):                     # x6: (1,6,h,w) float32 in [0,1] -> (1,3,h,w)
        if self.sess is not None:
            return self.sess.run(None, {"x": x6.astype(np.float32)})[0]
        with torch.no_grad():
            return self.model(torch.from_numpy(x6).float()).clamp(0, 1).numpy()

    def _run_tiles(self, in6):                # in6: (H,W,6) float [0,1] -> (H,W,3) [0,1]
        H, W = in6.shape[:2]
        T, O = self.tile, self.overlap
        step = T - O
        out = np.zeros((H, W, 3), np.float32)
        wsum = np.zeros((H, W, 1), np.float32)
        # feather weight (linear ramp into the overlap band)
        r = np.minimum(np.arange(T), np.arange(T)[::-1]).astype(np.float32)
        r = np.clip((r - (0 if O == 0 else 0)) / max(O, 1), 0.05, 1.0)
        wij = np.outer(r, r)[:, :, None]
        ys = list(range(0, max(H - T, 0) + 1, step)) or [0]
        xs = list(range(0, max(W - T, 0) + 1, step)) or [0]
        if ys[-1] != H - T and H > T: ys.append(H - T)
        if xs[-1] != W - T and W > T: xs.append(W - T)
        for y in ys:
            for x in xs:
                tile = in6[y:y + T, x:x + T]
                th, tw = tile.shape[:2]
                if (th, tw) != (T, T):
                    tile = cv2.copyMakeBorder(tile, 0, T - th, 0, T - tw, cv2.BORDER_REPLICATE)
                pred = self._infer(tile.transpose(2, 0, 1)[None])[0].transpose(1, 2, 0)
                out[y:y + th, x:x + tw] += (pred * wij)[:th, :tw]
                wsum[y:y + th, x:x + tw] += wij[:th, :tw]
        return out / np.maximum(wsum, 1e-6)

    def enhance(self, bgr):
        h, w = bgr.shape[:2]
        prompt = appearance_prompt(bgr)
        in6 = np.concatenate((bgr, prompt), -1)            # HxWx6 uint8

        if self.mode == "tile":
            in6f = (in6.astype(np.float32) / 255.0)
            in6f, ph, pw = stride_integral(in6f, 8)
            out = self._run_tiles(in6f)
            out = (np.clip(out, 0, 1) * 255).astype(np.uint8)[ph:, pw:]
            return out

        # resize mode (official appearance >MAX path): fixed work x work square + shadow upscale
        work = self.work
        small = cv2.resize(in6, (work, work)).astype(np.float32).transpose(2, 0, 1)[None] / 255.0
        pred = np.clip(self._infer(small)[0].transpose(1, 2, 0), 0, 1)
        pred = (pred * 255).astype(np.uint8)
        pred[pred == 0] = 1
        shadow = cv2.resize(bgr, (work, work)).astype(float) / pred.astype(float)
        shadow = cv2.resize(shadow, (w, h))
        shadow[shadow == 0] = 1e-5
        return np.clip(bgr.astype(float) / shadow, 0, 255).astype(np.uint8)


if __name__ == "__main__":
    _selftest_patch()
    print("patch-embed selftest OK")
