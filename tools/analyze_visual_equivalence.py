#!/usr/bin/env python3
"""Conservative local PPTX/PDF equivalence report; never changes pack content."""
from __future__ import annotations
import argparse, json
from collections import defaultdict
from pathlib import Path
from PIL import Image

def dhash(path: Path):
    image=Image.open(path).convert("L").resize((9,8)); pixels=list(image.getdata())
    return sum(1<<index for index,(a,b) in enumerate(zip([pixels[row*9+col] for row in range(8) for col in range(8)],[pixels[row*9+col+1] for row in range(8) for col in range(8)])) if a>b)
def distance(a,b): return (a^b).bit_count()
def align(left,right,gap=12,threshold=8):
    """Order-preserving visual alignment; a filename is never an input."""
    n,m=len(left),len(right); dp=[[0]*(m+1) for _ in range(n+1)]
    for i in range(1,n+1): dp[i][0]=i*gap
    for j in range(1,m+1): dp[0][j]=j*gap
    for i in range(1,n+1):
        for j in range(1,m+1):
            cost=distance(left[i-1],right[j-1])
            dp[i][j]=min(dp[i-1][j-1]+cost,dp[i-1][j]+gap,dp[i][j-1]+gap)
    aligned=[]; ul=[]; ur=[]; i,j=n,m
    while i or j:
        if i and j and dp[i][j]==dp[i-1][j-1]+distance(left[i-1],right[j-1]):
            d=distance(left[i-1],right[j-1])
            if d<=threshold: aligned.append((i,j,d))
            else: ul.append(i); ur.append(j)
            i-=1;j-=1
        elif i and (not j or dp[i][j]==dp[i-1][j]+gap): ul.append(i);i-=1
        else: ur.append(j);j-=1
    return list(reversed(aligned)),sorted(ul),sorted(ur)
def main(workspace):
    review=json.loads((workspace/"review.json").read_text(encoding="utf-8")); groups=defaultdict(list)
    for item in review["items"]:
        if item.get("thumbnail"): groups[item["source_id"]].append(item)
    sources=[]
    for sid,items in groups.items():
        suffix=Path(items[0]["source_filename"]).suffix.lower();
        if suffix in {".pptx",".pdf"}: sources.append((sid,suffix,items))
    pairs=[]
    for psid,ptype,pitems in sources:
        if ptype!='.pptx': continue
        for fsid,ftype,fitems in sources:
            if ftype!='.pdf': continue
            # Count proximity only narrows expensive visual comparisons; it
            # never establishes equivalence and filenames are never consulted.
            if abs(len(pitems)-len(fitems)) > 1: continue
            try:
                left=[dhash(workspace / x['thumbnail']) for x in pitems]; right=[dhash(workspace / x['thumbnail']) for x in fitems]
            except Exception: continue
            aligned,ul,ur=align(left,right); distances=[x[2] for x in aligned]
            equivalent=bool(aligned) and len(aligned)/max(len(pitems),len(fitems))>=.98 and not ul and not ur
            pairs.append({"pptx_source_id":psid,"pdf_source_id":fsid,"pptx_slides":len(pitems),"pdf_pages":len(fitems),"aligned":[{"left_slide":a,"right_page":b,"perceptual_distance":d,"confidence":"high" if d<=4 else "medium"} for a,b,d in aligned],"near_identical":len(aligned),"mean_hamming":round(sum(distances)/len(distances),2) if distances else None,"max_hamming":max(distances) if distances else None,"unmatched_pptx":ul,"unmatched_pdf":ur,"alignment_confidence":"high" if equivalent else "conservative","equivalent":equivalent})
    (workspace/"equivalence.json").write_text(json.dumps({"threshold":"dHash <= 8, >=98% aligned pages; filenames are not used","pairs":pairs},indent=2),encoding="utf-8")
    print(workspace/"equivalence.json")
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('workspace',type=Path);main(p.parse_args().workspace.resolve())
