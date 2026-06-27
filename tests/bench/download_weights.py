"""Download DocTr-IllTr and DocRes-appearance checkpoints into tests/bench/models/.
Sources: HF model DaVinciCode/doctra-docres-main (docres.pkl, 183MB),
         HF space HaoFeng2019/DocTr (model_pretrained/illtr.pth)."""
import os, shutil
from huggingface_hub import hf_hub_download, list_repo_files

HERE = os.path.dirname(os.path.abspath(__file__))
MODELS = os.path.join(HERE, "models")
os.makedirs(MODELS, exist_ok=True)


def fetch(repo_id, filename, repo_type, out_name):
    dst = os.path.join(MODELS, out_name)
    if os.path.exists(dst):
        print(f"[skip] {out_name} already present ({os.path.getsize(dst)/1e6:.1f} MB)")
        return dst
    p = hf_hub_download(repo_id=repo_id, filename=filename, repo_type=repo_type)
    shutil.copy(p, dst)
    print(f"[ok]   {out_name} <- {repo_id}/{filename} ({os.path.getsize(dst)/1e6:.1f} MB)")
    return dst


if __name__ == "__main__":
    # DocRes main weights
    fetch("DaVinciCode/doctra-docres-main", "docres.pkl", "model", "docres.pkl")

    # DocTr IllTr weights live in the HF Space repo; locate the .pth under model_pretrained/
    files = list_repo_files("HaoFeng2019/DocTr", repo_type="space")
    cand = [f for f in files if f.lower().endswith(".pth") and "ill" in f.lower()]
    if not cand:  # fallback: any illtr-looking file
        cand = [f for f in files if "illtr" in f.lower()]
    print("IllTr candidates:", cand)
    assert cand, f"no IllTr checkpoint found in space; files={files}"
    fetch("HaoFeng2019/DocTr", cand[0], "space", "illtr.pth")
    print("DONE")
