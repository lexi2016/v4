"""Local ACT-062A read-only frozen-source run. No model entry points are invoked."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from io import BytesIO
import json
import math
import os
import resource
import sys
from time import perf_counter, process_time

sys.dont_write_bytecode = True

import numpy as np
import pandas as pd
import pyarrow as pa
from threadpoolctl import threadpool_limits

import blind062
from common062 import ACT058, ACT061, BASE, GOV, NAMES, ROOT, Usage, csv_payload, digest, module
import dictionary062
import recon062
from report062 import report

ARROW_CPU, ARROW_IO, BLAS = 4, 2, 1
LIMIT = 2_000_000
PAIR_DIRECT = ACT061 / "evidence/ACT061A_EXIT_EVIDENCE.json"


def finite_json(value):
    if isinstance(value, dict):
        return {str(k):finite_json(v) for k,v in value.items()}
    if isinstance(value, (list,tuple)):
        return [finite_json(x) for x in value]
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def json_payload(data):
    return (json.dumps(finite_json(data),ensure_ascii=False,allow_nan=False,indent=2)+"\n").encode()


def bind_reader(usage,codes):
    # The birth cohort and joint Reader/adjustment identity are inherited from
    # the exact upstream receipt used by ACT-061A. The source stays read-only.
    old = module("act062_frozen_act058",ACT058 / "compute.py")
    prior_code = ROOT.parent / "act060a_kb35_20261125/compute060.py"
    prev = module("act062_frozen_act060",prior_code)
    prev.OLD = old
    base_receipt = usage.json(ACT058 / "evidence/compute_receipt.json")
    _,events,_,_,r56,r50,source = old.frozen_inputs()
    for name,identity in source.items():
        expected = base_receipt["source_identity"][name]
        assert all(identity[k] == expected[k] for k in ("sha256","bytes")), name
        usage.sources[identity["path"]] = identity
    nested_read_bytes = sum(ref["bytes"] for ref in source.values())
    usage.direct_read_bytes += nested_read_bytes
    usage.reader_accounting.append(dict(stage="frozen_inputs", minimum_hash_bytes=nested_read_bytes,
                                       extra_nested_input_reads_not_measured=True))
    cfg,frame,cal,binding = prev.project_reader(codes,r56,r50,base_receipt)
    assert binding["calendar_sha256"] == usage.json(PAIR_DIRECT)["reader"]["calendar_sha256"]
    store = {code:old.Stock(code,daily,cfg["events"][code],cal)
             for code,daily in frame.groupby("canonical",sort=True)}
    binding["proof_effective_projection_only"] = True
    binding["historical_data_not_copied"] = True
    binding["nested_reader_physical_read_bytes"] = None
    return old,events,store,cal,binding,source


def canary(inputs,store):
    code = "920748.BJ"
    pool = inputs["waves"].loc[inputs["waves"].security_id.eq(code)].copy()
    sample = blind062.cases(inputs | {"waves":pool},store)
    assert sample and all(x[0].archetype == "D" for x in sample)
    from xml.etree import ElementTree as ET
    _, stop, bars = sample[0]
    for stage, view,last in (("A",bars[:16],0),("B",bars,stop)):
        csv = blind062.csv_bytes(view)
        chart = blind062.draw("BLIND_01",stage,view)
        root = ET.fromstring(chart)
        observed = root.findall(blind062.SVG_NS+"g")
        assert len(observed) == len(view)
        assert observed[-1].get("data-bar") == blind062.label(last)
        assert len(csv.splitlines()) == len(view)+1
    print(f"canary archetype D, real window candidates={len(sample)}, two physical stages PASS",flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--canary",action="store_true")
    parser.add_argument("--run-name",default="primary")
    args = parser.parse_args()
    assert args.run_name.isidentifier()
    usage = Usage()
    started = datetime.now(timezone.utc).isoformat()
    pa.set_cpu_count(ARROW_CPU)
    pa.set_io_thread_count(ARROW_IO)
    for name in ("common062.py","dictionary062.py","blind062.py","recon062.py","run062.py","report062.py"):
        usage.pin(ROOT/name)
    with threadpool_limits(limits=BLAS):
        inputs = dictionary062.load(usage,ROOT)
        codes = {"920748.BJ"} if args.canary else set(inputs["stocks"].index)
        old,events,store,cal,reader,src = bind_reader(usage,codes)
        if args.canary:
            usage.point("reading")
            canary(inputs,store)
            usage.point("canary_calculate_verify")
            return
        buy = dictionary062.read_buy_signals(usage, src | {"roster":codes})
        flags = recon062.read(usage)
        usage.point("reading")
        dictionary = dictionary062.build(inputs,store,old,events,buy)
        blind,reveal,scan = blind062.build(inputs,store)
        recons,recon = recon062.build(flags,inputs,cal)
        text = report(dictionary,scan,recon)
        usage.point("calculation")
        files = {"report":text,"dictionary":csv_payload(dictionary),"blind":blind,
                 "reveal":csv_payload(reveal),"recon":csv_payload(recons)}
        expected = {"dictionary":42, "reveal":16, "recon":len(recons)}
        for name,count in expected.items():
            assert len(pd.read_csv(BytesIO(files[name]),low_memory=False)) == count, name
        assert all(0<len(buf)<=LIMIT for buf in files.values())
        assert blind062.check(blind,reveal,inputs["stocks"])["assertions_pass"]
        usage.point("verification")
        result = ROOT/"results"/args.run_name
        result.mkdir(parents=True,exist_ok=False,mode=0o700)
        for name,data in files.items():
            usage.write(result/NAMES[name],data)
        usage.point("write")
        evidence = dict(action="ACT-062A", status="LOCAL_WRITER_COMPLETE_PENDING_INDEPENDENT_REVIEW",
                        started_at_utc=started, finished_at_utc=datetime.now(timezone.utc).isoformat(),
                        python=sys.executable, base_commit=BASE, governance=GOV,
                        wall_s=usage.wall, cpu_s=usage.cpu, total_writer_wall_s=perf_counter()-usage.start,
                        total_writer_cpu_s=process_time()-usage.cpu_start, host_logical_cores=os.cpu_count(),
                        resource_peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                        arrow_cpu_threads=ARROW_CPU, arrow_io_threads=ARROW_IO, blas_threads=BLAS,
                        input_direct_minimum_bytes=usage.direct_read_bytes,
                        decoded_arrow_and_zip_projection_bytes=usage.projected_decoded_bytes,
                        output_written_payload_bytes=usage.write_bytes, reader_accounting=usage.reader_accounting,
                        physical_fs_io_bytes=None, process_tree_rss_bytes=None, reader=reader,
                        sources=usage.sources, blind_scan=scan, flagship_reconciliation=recon,
                        files=[{"path":str(result/NAMES[key]),"name":NAMES[key],**digest(data)} for key,data in files.items()])
        evid = ROOT/"evidence"
        evid.mkdir(exist_ok=True,mode=0o700)
        usage.write(evid/f"{args.run_name}_writer_evidence.json",json_payload(evidence))
        print(f"writer completed {len(files)} files / {sum(len(x) for x in files.values())} payload bytes",flush=True)


if __name__ == "__main__":
    main()
