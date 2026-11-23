import zipfile, re, sys, xml.etree.ElementTree as ET
p = "exam.docx"
z = zipfile.ZipFile(p)
xml = z.read("word/document.xml").decode("utf-8")
ns = {"w":"http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
root = ET.fromstring(xml)
body = root.find("w:body", ns)
out = []
def para_text(p):
    parts = []
    for t in p.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t"):
        parts.append(t.text or "")
    return "".join(parts)
for el in body:
    tag = el.tag.split("}")[1]
    if tag == "p":
        txt = para_text(el)
        out.append(txt)
    elif tag == "tbl":
        out.append("[TABLE]")
        for tr in el.findall("w:tr", ns):
            cells = []
            for tc in tr.findall("w:tc", ns):
                cells.append(" ".join(para_text(pp) for pp in tc.findall("w:p", ns)).strip())
            out.append(" | ".join(cells))
        out.append("[/TABLE]")
text = "\n".join(out)
text = re.sub(r"\n{3,}", "\n\n", text)
open("exam_text.txt","w",encoding="utf-8").write(text)
print(len(text))
