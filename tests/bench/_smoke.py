import time, numpy as np, cv2, fitz, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import engines

d = fitz.open(os.path.join(os.path.dirname(__file__), "..", "assets", "test_pdf_scan.pdf"))
pix = d[0].get_pixmap(dpi=150)
a = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, pix.n)
bgr = cv2.cvtColor(a, cv2.COLOR_RGB2BGR)
print("page0", bgr.shape, flush=True)

for name, f in [
    ("docres-int8 resize@512", lambda: engines.DocResEngine("int8", "resize", work=512)),
    ("docres-fp32 resize@512", lambda: engines.DocResEngine("fp32", "resize", work=512)),
    ("illtr-fp32",             lambda: engines.IllTrEngine("fp32")),
    ("illtr-int8",             lambda: engines.IllTrEngine("int8")),
]:
    try:
        t = time.perf_counter(); e = f(); bt = time.perf_counter() - t
        t = time.perf_counter(); o = e.enhance(bgr); et = time.perf_counter() - t
        cv2.imwrite(os.path.join(os.path.dirname(__file__), "out", f"smoke_{name.split()[0]}.jpg"), o)
        print(f"OK  {name:26s} build {bt:6.1f}s  enhance {et:6.2f}s  out {o.shape}", flush=True)
    except Exception as ex:
        import traceback; traceback.print_exc()
        print(f"FAIL {name}: {ex}", flush=True)
print("SMOKE_DONE", flush=True)
