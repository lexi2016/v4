"""Stage the exact 18874-only delta on the accepted seven-P0 baseline."""
import ast
from hashlib import sha256
import json
from pathlib import Path
import re
import sys

HERE = Path(__file__).resolve().parent
SEVEN = HERE.parent / "r21_seven_p0"
sys.path.insert(0, str(SEVEN))
from stage_repair import replace_once

MAIN = "frontend/dist/assets/main-r21-p0-7fbd7f3a25c7.js"
INDEX = "frontend/dist/index.html"
OVERLAY = "content_projection/read_overlay.py"
FORMAL = "content_projection/formal_admission_reads.py"
BINDING = "content_projection/formal_admission_manifest.json"
TRACK = "r21_isolated_readonly_18874"

BASE = {
    MAIN: "7fbd7f3a25c79d9603be2ad22901365a8e5bc0e373e9d0ffd7091506b6d41a15",
    INDEX: "580b2427070cfc54fb6311cb67333c74ae3ed68bb821f6648ec0e23f0ed094ba",
    OVERLAY: "5a7af82a3e4faf2853baa700d0ccb36a1ed70784c1284bc4a3a1eacc7dc8b8c4",
}
API_DEPENDENCIES = {
    "run_readonly_trial.py": "ff55688d4a9c088756547c77165b921b8db882009777a24b0db23c4b9f5c5a58",
    "v4_core_pure_r21_20261127.zip": "e202bf8680a6de6d0867be879a76c0c2dbf84e1b96012e9da24c947a5488dd96",
    "source/v4_core/api/app.py": "a3011ad46b921a9873b10e1b34e27f117a96295f9871792cba0d623898c81673",
    "content_projection/seven_p0_reads.py": "28cc39722c84f6cadf4b8934179aa9e739c1c84bb48176515873910ed0c1d59a",
    "content_projection/workbench_parity.py": "47026991f0652702eed2908d952fa362763b5e795a3c16c4f3dbf55b584fa414",
    "content_projection/read_preselection.py": "497cc98869bce5d029055f0f3b1ec63c525b35e2bd80098819f268876ff3465e",
    "content_projection/read_scheduled_lane.py": "b289b07ae4c902628c81e09e5a65b1c65b75d99354b6db70d562293fb8d6f340",
}

OVERLAY_EDITS = (
    (
        "from .seven_p0_reads import SevenP0Reads\n",
        "from .seven_p0_reads import SevenP0Reads\nfrom .formal_admission_reads import FormalAdmissionReads\n",
    ),
    (
        "        self.seven_p0_reads = SevenP0Reads(app.state.store, data, self.preselection)\n",
        "        self.seven_p0_reads = SevenP0Reads(app.state.store, data, self.preselection)\n"
        "        self.formal_admission = FormalAdmissionReads(data, self.seven_p0_reads)\n",
    ),
    (
        '''            response = JSONResponse({**self.review, "trade_date": query["date"][0]},
                                    headers={"Cache-Control": "no-store"})''',
        '''            review = {**self.review, "trade_date": query["date"][0]}
            transform = self.formal_admission.native_transform(path, query)
            response = JSONResponse(transform(review), headers={"Cache-Control": "no-store"})''',
    ),
    (
        '''        if response is None:
            response = self.seven_p0_reads.resolve(path, query)
''',
        '''        if response is None:
            response = self.formal_admission.resolve(path, query)
        if response is None:
            response = self.seven_p0_reads.resolve(path, query)
        if response is None and scope["method"] == "GET":
            transform = self.formal_admission.native_transform(path, query)
            if transform is not None:
                return await self.with_native_json(scope, receive, send, transform)
''',
    ),
    (
        '''        return {**payload, "stage_navigation_dates": dates, "future_target_dates": future, "research_dates": research}''',
        '''        return {**payload, "stage_navigation_dates": dates, "future_target_dates": future,
                "research_dates": research, "runtime_identity": self.formal_admission.identity.runtime()}''',
    ),
    (
        "        # Preserve native calendar fields and extend only the owner-bound navigation dates.\n",
        "        # Preserve native non-200 responses and project only verified read contracts.\n",
    ),
)

# The accepted production-compatible bundle predates the isolated source tree.
# These precise edits preserve its other 18874 lanes and the prior seven fixes.
MAIN_EDITS = (
    (
        'let ve=0,ce=0,re=0,Ae=null,L=null,fe=0,Be=0;',
        'let ve=0,ce=0,re=0,Ae=null,L=null,fe=0,Be=0,r21StageKey="";',
    ),
    (
        'for(const ye of n)ye.id===H&&be?he[ye.id]={date:b,loading:!1,payload:ne}:he[ye.id]={date:b,loading:!0};',
        'for(const ye of n){const r21Previous=zt(ye.id);'
        'he[ye.id]=ye.id===H&&be?{date:b,loading:!1,payload:ne}:'
        'r21Previous?.payload?r21Previous:{date:b,loading:!0}}',
    ),
    (
        'Re[Oe.id]=pt?{date:b,loading:!1,payload:pt}:{date:b,loading:!1,error:"阶段时间轴读取失败"}',
        'Re[Oe.id]=pt?{date:b,loading:!1,payload:pt}:'
        'he[Oe.id]?.payload?he[Oe.id]:{date:b,loading:!1,error:"阶段时间轴读取失败"}',
    ),
    (
        'if(Oe.id===H&&be)continue;const pt=ye[Oe.id];',
        'if(Oe.id===H){const r21Current=zt(H);'
        'if(be||Array.isArray(r21Current?.payload?.unified_rows)){Re[H]=r21Current||he[H];continue}}'
        'const pt=ye[Oe.id];',
    ),
    (
        'for(const pt of n)Oe[pt.id]=pt.id===H&&be?he[pt.id]:{date:b,loading:!1,error:Re};',
        'for(const pt of n){const r21Current=zt(pt.id);'
        'Oe[pt.id]=r21Current?.payload?r21Current:{date:b,loading:!1,error:Re}}',
    ),
    (
        'const pe=f.value;Ae?.abort(),L?.abort(),re+=1;const be=new AbortController;Ae=be;'
        'const he=++ce;te.value=!0,le.value="",V.value=null,bn(b,{date:pe,loading:!0});'
        'try{const ye=await Tf(pe,b,be.signal);he===ce&&pe===f.value&&(V.value=ye,bn(b,{date:pe,loading:!1,payload:ye}),St(pe,b,ye))}'
        'catch(ye){if(he===ce&&pe===f.value){le.value=ye instanceof Error&&ye.message.includes("超时")?"阶段工作台读取超时。":"阶段工作台读取失败。";'
        'const Re={};for(const Oe of n)Re[Oe.id]={date:pe,loading:!1,error:Oe.id===b?le.value:"阶段工作台读取失败"};U.value=Re}}'
        'finally{he===ce&&pe===f.value&&(te.value=!1),Ae===be&&(Ae=null)}',
        'const pe=f.value,r21Key=pe+"|"+b;if(Ae&&r21StageKey===r21Key)return;'
        'Ae?.abort(),L?.abort(),re+=1;const be=new AbortController;Ae=be;r21StageKey=r21Key;'
        'const he=++ce,r21Prior=V.value?.trade_date===pe&&V.value?.stage?.stage_id===b?V.value:null;'
        'te.value=!0;le.value="";V.value=r21Prior;void St(pe,b,r21Prior);'
        'try{let ye;try{ye=await Tf(pe,b,be.signal)}catch(r21Error){'
        'const r21Transient=r21Error instanceof TypeError||(r21Error instanceof Error&&'
        '/读取超时|HTTP (502|503|504)/.test(r21Error.message));'
        'if(be.signal.aborted||he!==ce||pe!==f.value||!r21Transient)throw r21Error;'
        'ye=await Tf(pe,b,be.signal)}'
        'if(he===ce&&pe===f.value){V.value=ye;bn(b,{date:pe,loading:!1,payload:ye})}}'
        'catch(ye){if(he===ce&&pe===f.value&&!be.signal.aborted){'
        'const r21Reason=ye instanceof Error&&ye.message.includes("超时")?"阶段明细读取超时。":"阶段明细读取失败。";'
        'le.value=r21Reason+(r21Prior?"保留同日上次成功返回的快照。":"时间轴摘要独立读取。")}}'
        'finally{if(he===ce&&pe===f.value)te.value=!1;if(Ae===be){Ae=null;r21StageKey=""}}',
    ),
    (
        'e("aside",Zl,[e("p",null,[ie("已接入来源池汇总',
        'e("aside",Zl,[w.value.stage7_formal_review?e("p",{"data-testid":"r21-formal-stage-admission"},'
        '"同日阶段回执 "+t(w.value.stage_coverage?.observed_owner_receipts??0)+"/7 · 可读观察行阶段 "+'
        't(w.value.stage_coverage?.observed_stage_rows??0)+"/7 · 正式阶段 "+t(w.value.stage_coverage?.available??0)+'
        '"/7 · Stage7 A股复盘源 "+t(w.value.stage7_formal_review.status)+" · "+'
        't(w.value.stage7_formal_review.required_role),1):y("",!0),e("p",null,[ie("已接入来源池汇总',
    ),
    (
        'e("p",null,"任务行证据："+t(i.value.scheduler_observation?.logical_row_evidence||"DECLARED_ONLY")+" · "+'
        't(i.value.scheduler_observation?.receipt_namespace||"缺回执根"),1)',
        'e("p",null,"任务行证据："+t(i.value.scheduler_observation?.logical_row_evidence||"DECLARED_ONLY")+" · "+'
        't(i.value.scheduler_observation?.receipt_namespace||"缺回执根"),1),'
        'Array.isArray(i.value.scheduler_observation?.six_slot_evidence)?'
        'e("ul",{"data-testid":"r21-six-slot-evidence"},i.value.scheduler_observation.six_slot_evidence.map(slot=>'
        'e("li",{key:slot.slot_id},t(slot.schedule_time)+" · "+t(slot.source_receipt_status)+" · 回放时点 "+t(slot.historical_window_count)+" · "+t(slot.gap)+'
        '(slot.isolated_replay_observation?" · "+t(slot.isolated_replay_observation.scope):""),1))):y("",!0)',
    ),
)


def sha(raw):
    return sha256(raw).hexdigest()


def verified(root, path, expected):
    raw = (root / path).read_bytes()
    if sha(raw) != expected:
        raise ValueError(f"R21_ACTUAL_BASELINE_BYTE_MISMATCH: {path}")
    return raw


def prepare(root, output, replay):
    root, output = root.resolve(), output.resolve()
    if output == root or root in output.parents:
        raise ValueError("WRITER_STAGING_MUST_BE_OUTSIDE_ACTIVE_ROOT")
    old = {name: verified(root, name, expected) for name, expected in BASE.items()}
    for name, expected in API_DEPENDENCIES.items():
        verified(root, name, expected)
    replay = replay.resolve()
    verified(replay, "D27_BACKFILL_STDOUT.json", "82386ac727a85e75fa84644289e7f0964920ec61c1b40a734cf5c1e35a486842")
    verified(replay, "D27_SLOT1.json", "70dd0cb68ef16ed6a41609ba9822c9e81424a66b7eac973d050a44aeaa60b7d8")
    main = replace_once(old[MAIN].decode(), MAIN_EDITS, MAIN).encode()
    main_target = f"frontend/dist/assets/main-r21-formal-{sha(main)[:12]}.js"
    script_path = "/assets/" + Path(main_target).name
    index = replace_once(old[INDEX].decode(), ((Path(MAIN).name, Path(main_target).name),), INDEX).encode()
    overlay = replace_once(old[OVERLAY].decode(), OVERLAY_EDITS, OVERLAY).encode()
    formal = (HERE / "formal_admission_reads.py").read_bytes()
    ast.parse(overlay.decode())
    ast.parse(formal.decode())
    manifest = {
        "schema": "v4.r21.isolated_runtime_manifest.v1", "track": TRACK,
        "api_files": {**API_DEPENDENCIES, OVERLAY: sha(overlay), FORMAL: sha(formal)},
        "frontend": {"script_path": script_path, "index_sha256": sha(index), "bundle_sha256": sha(main)},
        "historical_replay": {"root": str(replay)},
    }
    binding = (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
    output.mkdir(parents=True, exist_ok=False)
    files = []
    for target, raw in ((main_target, main), (INDEX, index), (FORMAL, formal), (BINDING, binding), (OVERLAY, overlay)):
        expected_before = BASE.get(target)
        if (expected_before is None) != (not (root / target).exists()):
            raise ValueError(f"R21_STAGED_TARGET_PRESENCE_CONFLICT: {target}")
        source = output / "files" / target
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(raw)
        files.append({"target": target, "source": str(source.relative_to(output)),
                      "old_sha256": expected_before, "new_sha256": sha(raw)})
    receipt = output / "ACTIVATION_MANIFEST.json"
    receipt.write_text(json.dumps({"active_root": str(root), "files": files}, ensure_ascii=False, indent=2) + "\n")
    return receipt


if __name__ == "__main__":
    if len(sys.argv) != 4:
        raise SystemExit("usage: stage_formal_admission.py ACTIVE_ROOT NEW_WRITER_STAGING_DIR VERIFIED_REPLAY_ROOT")
    print(prepare(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])))
