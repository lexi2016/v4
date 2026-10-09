import csv, json, runpy, shutil, socket, sys, urllib.request
from pathlib import Path
args = list(sys.argv[1:])
out = Path(args[args.index("--out") + 1])
source_run = Path('/Users/lexi/Desktop/学习/v3_system/选股池/微信公众号/evidence/issue31_r2_mac_20261009/reviewer/candidate/runs/20261008_html_recovery_ZfZPPo1xSsfROmFZbaqSuw')
source_images = source_run / "wechat_article_images"
target_images = out / "wechat_article_images"
target_images.mkdir(parents=True, exist_ok=True)
for image in source_images.iterdir():
    if image.is_file(): shutil.copy2(image, target_images / image.name)
checkpoint = json.loads((source_run / "wechat_article_image_checkpoint.json").read_text(encoding="utf-8-sig"))
checkpoint["images"] = [{**row, "local_path": str(target_images / Path(row["local_path"]).name)} for row in checkpoint["images"]]
(out / "wechat_article_image_checkpoint.json").write_text(json.dumps(checkpoint), encoding="utf-8")
with (source_run / "wechat_article_image_manifest.csv").open(encoding="utf-8-sig", newline="") as stream:
    reader = csv.DictReader(stream); fields = list(reader.fieldnames or []); rows = list(reader)
for row in rows: row["local_path"] = str(target_images / Path(row["local_path"]).name)
with (out / "wechat_article_image_manifest.csv").open("w", encoding="utf-8-sig", newline="") as stream:
    writer = csv.DictWriter(stream, fieldnames=fields); writer.writeheader(); writer.writerows(rows)
def blocked(*args, **kwargs):
    with Path('/Users/lexi/Desktop/学习/v3_system/选股池/微信公众号/evidence/issue31_r2_mac_20261009/reviewer/collector_cli_network_attempts2.jsonl').open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"argv": sys.argv, "args": [str(x) for x in args]}, ensure_ascii=False) + "\n")
    raise RuntimeError("independent acceptance network guard blocked access")
urllib.request.urlopen = blocked
socket.getaddrinfo = blocked
sys.argv = [str(Path('/Users/lexi/.codex/skills/wechat-research-intake/scripts/wechat_article_intake.py')), *args]
runpy.run_path(str(Path('/Users/lexi/.codex/skills/wechat-research-intake/scripts/wechat_article_intake.py')), run_name="__main__")
