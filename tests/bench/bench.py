"""CPU speed+quality benchmark: DocTr-IllTr vs DocRes-appearance on a scanned PDF.

Usage (from repo root):
    python tests/bench/bench.py                       # default suite, 300 DPI, pages 0-2
    python tests/bench/bench.py --pages all --dpi 300
    python tests/bench/bench.py --engines illtr-int8,docres-int8-1024 --repeats 3

Outputs: per-engine ms/page table + tests/bench/out/results.csv + side-by-side JPGs.
No ground truth, so quality uses no-reference proxies (see metrics()).
"""
import os, sys, time, csv, argparse, statistics
import numpy as np
import cv2
import fitz

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import engines  # noqa: E402

PDF = os.path.join(HERE, "..", "assets", "test_pdf_scan.pdf")
OUT = os.path.join(HERE, "out")
os.makedirs(OUT, exist_ok=True)

# preset key -> (label, factory). Keep the cheap/fast ones first.
SUITE = {
    "illtr-fp32":      ("DocTr-IllTr fp32 (tiled@128)",          lambda t: engines.IllTrEngine("fp32", threads=t)),
    "illtr-int8":      ("DocTr-IllTr int8 (tiled@128)",          lambda t: engines.IllTrEngine("int8", threads=t)),
    "docres-int8-1024":("DocRes int8 resize@1024",               lambda t: engines.DocResEngine("int8", "resize", work=1024, threads=t)),
    "docres-int8-1600":("DocRes int8 resize@1600",               lambda t: engines.DocResEngine("int8", "resize", work=1600, threads=t)),
    "docres-fp32-1024":("DocRes fp32 resize@1024",               lambda t: engines.DocResEngine("fp32", "resize", work=1024, threads=t)),
    "docres-fp32-1600":("DocRes fp32 resize@1600",               lambda t: engines.DocResEngine("fp32", "resize", work=1600, threads=t)),
    "docres-int8-tile":("DocRes int8 tile@512 (native res)",     lambda t: engines.DocResEngine("int8", "tile", tile=512, overlap=48, threads=t)),
}
DEFAULT = "illtr-int8,docres-int8-1024,docres-int8-1600,docres-fp32-1600"


def metrics(gray):
    """No-reference quality proxies on a uint8 grayscale image."""
    g = gray.astype(np.float64)
    sharp = cv2.Laplacian(gray, cv2.CV_64F).var()          # text-edge crispness (higher=sharper)
    bg = g[g >= np.percentile(g, 70)]                       # bright/background pixels
    bg_std = float(bg.std())                                # background flatness (lower=cleaner)
    contrast = float(np.percentile(g, 95) - np.percentile(g, 5))   # dynamic range (higher=better sep.)
    ink = float((gray < 128).mean() * 100)                 # % dark pixels (sanity)
    return dict(sharp=sharp, bg_std=bg_std, contrast=contrast, ink=ink)


def parse_pages(spec, n):
    if spec == "all":
        return list(range(n))
    out = []
    for part in spec.split(","):
        if "-" in part:
            a, b = part.split("-"); out += list(range(int(a), int(b) + 1))
        else:
            out.append(int(part))
    return [p for p in out if 0 <= p < n]


def render(pdf, dpi):
    d = fitz.open(pdf)
    pages = []
    for pg in d:
        pix = pg.get_pixmap(dpi=dpi)
        a = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, pix.n)
        pages.append(cv2.cvtColor(a, cv2.COLOR_RGB2BGR if pix.n == 3 else cv2.COLOR_RGBA2BGR))
    return pages


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dpi", type=int, default=300)
    ap.add_argument("--pages", default="0-2")
    ap.add_argument("--engines", default=DEFAULT)
    ap.add_argument("--repeats", type=int, default=1)
    ap.add_argument("--threads", type=int, default=os.cpu_count())
    args = ap.parse_args()

    keys = [k.strip() for k in args.engines.split(",") if k.strip()]
    bad = [k for k in keys if k not in SUITE]
    if bad:
        sys.exit(f"unknown engine(s): {bad}\navailable: {list(SUITE)}")

    all_pages = render(PDF, args.dpi)
    idx = parse_pages(args.pages, len(all_pages))
    pages = [all_pages[i] for i in idx]
    res = pages[0].shape
    print(f"PDF: {len(all_pages)} pages | render @ {args.dpi} DPI -> {res[1]}x{res[0]} px | "
          f"benchmarking pages {idx} | threads={args.threads}\n")

    in_q = metrics(cv2.cvtColor(pages[0], cv2.COLOR_BGR2GRAY))
    print(f"input page{idx[0]} quality: sharp={in_q['sharp']:.0f} bg_std={in_q['bg_std']:.1f} "
          f"contrast={in_q['contrast']:.0f} ink={in_q['ink']:.1f}%\n")

    rows = []
    hdr = f"{'engine':32s} {'build_s':>8s} {'ms/page':>10s} {'pages/s':>8s} {'sharp':>7s} {'bg_std':>7s} {'contr':>6s}"
    print(hdr); print("-" * len(hdr))
    for k in keys:
        label, factory = SUITE[k]
        t0 = time.perf_counter()
        eng = factory(args.threads)
        build_s = time.perf_counter() - t0
        eng.enhance(pages[0])  # warmup (page0), not timed
        times, q = [], None
        for p in pages:
            best = min(_timed(eng, p) for _ in range(args.repeats))
            times.append(best[0])
            if q is None:
                q = metrics(cv2.cvtColor(best[1], cv2.COLOR_BGR2GRAY))
                _save_sidebyside(k, pages[0], best[1])
        ms = statistics.mean(times) * 1000
        sd = (statistics.pstdev(times) * 1000) if len(times) > 1 else 0.0
        print(f"{label:32s} {build_s:8.1f} {ms:7.0f}±{sd:<3.0f} {1000/ms:8.2f} "
              f"{q['sharp']:7.0f} {q['bg_std']:7.1f} {q['contrast']:6.0f}")
        rows.append(dict(engine=label, key=k, build_s=round(build_s, 1),
                         ms_per_page=round(ms, 1), std_ms=round(sd, 1),
                         pages_per_s=round(1000 / ms, 3), **q))

    with open(os.path.join(OUT, "results.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)
    print(f"\ncsv  -> {os.path.join(OUT, 'results.csv')}")
    print(f"imgs -> {OUT}\\<key>_sidebyside.jpg")


def _timed(eng, page):
    t = time.perf_counter()
    out = eng.enhance(page)
    return time.perf_counter() - t, out


def _save_sidebyside(key, before, after):
    if after.shape[:2] != before.shape[:2]:
        after = cv2.resize(after, (before.shape[1], before.shape[0]))
    combo = np.hstack([before, after])
    scale = 1400 / combo.shape[1]
    combo = cv2.resize(combo, None, fx=scale, fy=scale)
    cv2.imwrite(os.path.join(OUT, f"{key}_sidebyside.jpg"), combo,
                [cv2.IMWRITE_JPEG_QUALITY, 88])


if __name__ == "__main__":
    main()
