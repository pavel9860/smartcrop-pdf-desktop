import time, numpy as np, cv2, fitz, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import engines

d = fitz.open(os.path.join(os.path.dirname(__file__), "..", "assets", "test_pdf_scan.pdf"))
pix = d[0].get_pixmap(dpi=150)
a = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, pix.n)
bgr = cv2.cvtColor(a, cv2.COLOR_RGB2BGR)

for sz in [256, 384, 512]:
    try:
        t = time.perf_counter()
        e = engines.DocResEngine("int8", "resize", work=sz)
        bt = time.perf_counter() - t
        t = time.perf_counter(); o = e.enhance(bgr); et = time.perf_counter() - t
        print(f"OK   int8 resize@{sz}: calib+build {bt:6.1f}s  enhance {et:6.2f}s", flush=True)
    except Exception as ex:
        print(f"FAIL int8 resize@{sz}: {type(ex).__name__}: {str(ex)[:90]}", flush=True)
print("PROBE_DONE", flush=True)
