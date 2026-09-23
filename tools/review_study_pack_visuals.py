#!/usr/bin/env python3
"""Generate an offline, human-reviewable visual-retention workspace for a pack."""
from __future__ import annotations

import argparse, io, json, shutil, tempfile, zipfile
from pathlib import Path

import fitz
from PIL import Image, ImageDraw
from pptx import Presentation


def source_records(archive):
    records = [json.loads(line) for line in archive.read("meta/documents.jsonl").decode("utf-8").splitlines() if line]
    records = [record for record in records if record.get("source_copy_path")]
    if "meta/exam_manifest.json" in archive.namelist():
        for exam in json.loads(archive.read("meta/exam_manifest.json")).get("exams", []):
            records.append({"source_id": exam["stable_id"], "source_path": exam["original_name"], "source_copy_path": exam["retained_source_path"], "source_type": "past_exam", "exam": exam})
    return records


def pptx_text(slide):
    return "\n".join(shape.text for shape in slide.shapes if getattr(shape, "has_text_frame", False) and shape.text.strip())


def signals(slide):
    return {"pictures": sum(shape.shape_type == 13 for shape in slide.shapes), "charts": sum(getattr(shape, "has_chart", False) for shape in slide.shapes), "tables": sum(getattr(shape, "has_table", False) for shape in slide.shapes), "shapes": len(slide.shapes)}


def placeholder(path, title, text):
    image = Image.new("RGB", (1200, 675), "white"); draw = ImageDraw.Draw(image)
    draw.text((40, 35), title[:120], fill="black")
    draw.multiline_text((40, 100), text[:3000], fill="black", spacing=5)
    image.save(path, "WEBP", quality=88)


def render_pptx(source, output):
    """Use installed PowerPoint when available; fallback keeps a readable text preview."""
    try:
        import win32com.client
        app = win32com.client.DispatchEx("PowerPoint.Application")
        presentation = app.Presentations.Open(str(source), WithWindow=False)
        try:
            presentation.Export(str(output), "PNG", 1600, 900)
        finally:
            presentation.Close(); app.Quit()
        return "PowerPoint COM export"
    except Exception:
        return "PPTX text-preview fallback (PowerPoint unavailable)"


def write_html(workspace):
    (workspace / "index.html").write_text("""<!doctype html><meta charset=utf-8><title>Visual retention review</title><style>body{font:15px system-ui;margin:20px;background:#f7f8fa}header{position:sticky;top:0;background:white;padding:12px;border:1px solid #ddd}article{background:white;margin:16px 0;padding:14px;border:1px solid #ddd}img{max-width:420px;max-height:300px;display:block}button{margin:4px}.TEXT_SUFFICIENT{border-left:6px solid #2a8}.KEEP_VISUAL{border-left:6px solid #e83}.UNCERTAIN{border-left:6px solid #d99}</style><header><b id=count></b> <button onclick="filter('all')">All</button><button onclick="filter('UNCERTAIN')">Unreviewed</button><button onclick="filter('KEEP_VISUAL')">Keep visual</button><button onclick="download()">Export review.json</button></header><main id=items></main><script>let data,shown='all';const key='bklms-visual-review';fetch('review.json').then(x=>x.json()).then(x=>{data=JSON.parse(localStorage.getItem(key)||JSON.stringify(x));draw()});function set(i,v){data.items[i].decision=v;localStorage.setItem(key,JSON.stringify(data));draw()}function filter(v){shown=v;draw()}function draw(){let a=data.items.filter(x=>shown==='all'||x.decision===shown);count.textContent=`${a.length}/${data.items.length} shown`;items.innerHTML=a.map(x=>`<article class="${x.decision}"><b>${x.source_filename}</b> · ${x.locator.type} ${x.locator.number}<br><small>${x.source_id} · ${JSON.stringify(x.signals)}</small><img src="${x.thumbnail}"><pre>${x.text||'[no extracted text]'}</pre>${['TEXT_SUFFICIENT','KEEP_VISUAL','UNCERTAIN'].map(v=>`<button onclick="set(${x.index},'${v}')">${v}</button>`).join('')}</article>`).join('')}function download(){let a=document.createElement('a');a.href=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));a.download='review.json';a.click()}</script>""",encoding="utf-8")


def build(pack, workspace):
    workspace.mkdir(parents=True, exist_ok=True); thumbs=workspace / "thumbnails"; thumbs.mkdir(exist_ok=True)
    items=[]; methods=set()
    with zipfile.ZipFile(pack) as archive, tempfile.TemporaryDirectory(prefix="bklms_visual_review_") as temp:
        for record in source_records(archive):
            copied=record["source_copy_path"]; raw=archive.read(copied); suffix=Path(copied).suffix.lower(); source=Path(temp)/Path(copied).name; source.write_bytes(raw)
            target=thumbs/record["source_id"]; target.mkdir(exist_ok=True)
            if suffix==".pdf":
                document=fitz.open(stream=raw,filetype="pdf"); methods.add("PyMuPDF PDF render")
                for number,page in enumerate(document,1):
                    output=target/f"page_{number:03}.webp"; error=""
                    try:
                        pix=page.get_pixmap(matrix=fitz.Matrix(1.5,1.5),alpha=False); png=output.with_suffix('.png'); pix.save(png); Image.open(png).save(output,'WEBP',quality=88); png.unlink(missing_ok=True)
                        if not output.is_file() or not output.stat().st_size: raise RuntimeError("zero-byte thumbnail")
                    except Exception as exc: output.unlink(missing_ok=True); error=type(exc).__name__
                    items.append({"source_id":record["source_id"],"source_filename":Path(record["source_path"]).name,"source_type":record["source_type"],"locator":{"type":"page","number":number},"text":page.get_text(),"signals":{"low_text":len(page.get_text().strip())<80},"thumbnail":output.relative_to(workspace).as_posix() if not error else "","decision":"UNCERTAIN" if error else "UNREVIEWED","render_error":error})
            elif suffix==".pptx":
                presentation=Presentation(io.BytesIO(raw)); method=render_pptx(source,target); methods.add(method)
                for number,slide in enumerate(presentation.slides,1):
                    output=target/f"slide_{number:03}.webp"
                    exported=target/f"Slide{number}.PNG"
                    if exported.exists():
                        Image.open(exported).save(output,"WEBP",quality=88); exported.unlink()
                    if not output.exists(): placeholder(output,f"{Path(record['source_path']).name} — slide {number}",pptx_text(slide))
                    error="" if output.is_file() and output.stat().st_size else "zero-byte thumbnail"; output.unlink(missing_ok=True) if error else None
                    items.append({"source_id":record["source_id"],"source_filename":Path(record["source_path"]).name,"source_type":record["source_type"],"locator":{"type":"slide","number":number},"text":pptx_text(slide),"signals":signals(slide),"thumbnail":output.relative_to(workspace).as_posix() if not error else "","decision":"UNCERTAIN" if error else "UNREVIEWED","render_error":error})
    payload={"pack":str(pack),"items":[dict(item,index=index) for index,item in enumerate(items)],"rendering_methods":sorted(methods)}
    (workspace/"review.json").write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")
    (workspace/"summary.json").write_text(json.dumps({"sources":len({i['source_id'] for i in items}),"slides_pages":len(items),"unreviewed":sum(i['decision']=='UNREVIEWED' for i in items),"render_failures":sum(bool(i['render_error']) for i in items),"rendering_methods":sorted(methods)},indent=2),encoding="utf-8")
    write_html(workspace); print(workspace)


if __name__=="__main__":
    parser=argparse.ArgumentParser(description="Create a local-only visual review workspace; it never uploads pack content.")
    parser.add_argument("pack",type=Path); parser.add_argument("--output",type=Path,default=Path(".visual-retention-review")); args=parser.parse_args(); build(args.pack.resolve(),args.output.resolve())
