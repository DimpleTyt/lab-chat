"""Extract text, images and image-to-paragraph order from a .docx.

Outputs:
  content/source/method.txt        plain text, images marked as [[IMG imageN.png]]
  content/assets/img/*.png         all embedded images
  content/source/image_order.json  [{"file": "...", "paragraph": N}, ...]
"""
import json
import re
import zipfile
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "content" / "source" / "exam.docx"
OUT_TXT = ROOT / "content" / "source" / "method.txt"
IMG_DIR = ROOT / "content" / "assets" / "img"
ORDER = ROOT / "content" / "source" / "image_order.json"

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"

z = zipfile.ZipFile(SRC)
rels = ET.fromstring(z.read("word/_rels/document.xml.rels"))
relmap = {r.get("Id"): r.get("Target") for r in rels}

doc = ET.fromstring(z.read("word/document.xml"))
body = doc.find(W + "body")

IMG_DIR.mkdir(parents=True, exist_ok=True)
for name in z.namelist():
    if name.startswith("word/media/"):
        (IMG_DIR / Path(name).name).write_bytes(z.read(name))


def ptext(p):
    return "".join(t.text or "" for t in p.iter(W + "t"))


def collect_images(el):
    out = []
    for blip in el.iter(A + "blip"):
        rid = blip.get(R + "embed")
        tgt = relmap.get(rid)
        if tgt:
            out.append(Path(tgt).name)
    return out


lines = []
images = []
para_idx = 0

for el in body:
    tag = el.tag.replace(W, "")
    if tag == "p":
        para_idx += 1
        txt = ptext(el).strip()
        if txt:
            lines.append(txt)
        for f in collect_images(el):
            lines.append(f"[[IMG {f}]]")
            images.append({"file": f, "paragraph": para_idx})
    elif tag == "tbl":
        lines.append("[TABLE]")
        for tr in el.findall(W + "tr"):
            cells = []
            for tc in tr.findall(W + "tc"):
                cells.append(" ".join(ptext(pp).strip() for pp in tc.findall(W + "p")).strip())
            lines.append(" | ".join(cells))
        lines.append("[/TABLE]")

text = re.sub(r"\n{3,}", "\n\n", "\n".join(lines))
OUT_TXT.write_text(text, encoding="utf-8")
ORDER.write_text(json.dumps(images, ensure_ascii=False, indent=2), encoding="utf-8")
print("chars:", len(text), "images:", len(images), "unique:", len({i["file"] for i in images}))
