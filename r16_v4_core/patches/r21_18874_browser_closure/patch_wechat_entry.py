"""Prepare the exact-date WeChat entry in the isolated compiled app."""
from hashlib import sha256
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
WORK = Path(__file__).resolve().parent
FRONTEND = "frontend/dist"
INDEX = f"{FRONTEND}/index.html"
ASSET = f"{FRONTEND}/assets/main-r21-formal-886a0ddf6b5c.js"
PATCHES = (
    (
        '__name:"ResearchView",props:{archiveDate:{}},emits:',
        '__name:"ResearchView",props:{archiveDate:{},initialFeedFilter:{}},emits:',
    ),
    (
        'const _=j("latest"),k=j(vs[0])',
        'const _=j(n.initialFeedFilter==="wechat"?"wechat":"latest"),k=j(vs[0])',
    ),
    (
        'function De(){document.querySelector("#researchWechatSource")?.scrollIntoView({behavior:"smooth"})}',
        'function De(){_.value="wechat";requestAnimationFrame(()=>document.querySelector("#wechatResearchArchive")?.scrollIntoView({behavior:"smooth"}))}',
    ),
    (
        '!u.value&&!o.value&&i.value?.status==="NOT_MATERIALIZED"?(s(),l("section",Y_',
        '(i.value?.status==="NOT_MATERIALIZED"||(!i.value&&_.value==="wechat"))?(s(),l("section",Y_',
    ),
    (
        '"feed-cards":[],"feed-filter":_.value,"archive-date":S.value',
        '"feed-cards":[],"feed-filter":_.value,"archive-date":S.value||n.archiveDate',
    ),
    ('g[24]=z=>r(Bt)(!0)', 'g[24]=z=>r(Bt)(!0,r(X))'),
    ('g[25]=z=>r(Bt)(!0)', 'g[25]=z=>r(Bt)(!0,r(X))'),
)


def prepare():
    source = ROOT / ASSET
    index = ROOT / INDEX
    base = source.read_bytes()
    raw = base.decode()
    for before, after in PATCHES:
        if raw.count(before) != 1:
            raise RuntimeError(f"R21_WECHAT_PATCH_ANCHOR_MISMATCH:{before}")
        raw = raw.replace(before, after, 1)
    updated = raw.encode()
    new_sha = sha256(updated).hexdigest()
    new_rel = f"{FRONTEND}/assets/main-r21-formal-{new_sha[:12]}.js"
    index_raw, matches = re.subn(
        "/assets/" + re.escape(source.name),
        "/assets/" + Path(new_rel).name,
        index.read_text(),
    )
    if matches != 1:
        raise RuntimeError("R21_WECHAT_INDEX_ANCHOR_MISMATCH")
    for rel, value in ((new_rel, updated), (INDEX, index_raw.encode())):
        dst = WORK / "candidate" / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(value)
    subprocess.run(
        ["node", "--input-type=module", "--check"],
        check=True,
        input=updated,
        capture_output=True,
    )
    evidence = {
        "baseline_script": ASSET,
        "baseline_sha256": sha256(base).hexdigest(),
        "script_path": new_rel,
        "script_sha256": new_sha,
        "index_path": INDEX,
        "index_sha256": sha256(index_raw.encode()).hexdigest(),
        "syntax_check": "PASS",
    }
    (WORK / "WECHAT_PATCH_RECEIPT.json").write_text(json.dumps(evidence, indent=2) + "\n")
    print(json.dumps(evidence))


if __name__ == "__main__":
    prepare()
