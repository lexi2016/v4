"""Generate a synthetic integration fixture via the real store/consumer path."""
from pathlib import Path
import json
import sys
from pytest import MonkeyPatch
from conftest import runtime

destination=Path(sys.argv[1]).resolve()
destination.mkdir(exist_ok=False,parents=True)
with MonkeyPatch.context() as patch:
    app=runtime.__wrapped__(patch,destination/"synthetic_store")
    selected=app.publish()
    app.write({"HK_CONNECT":selected},execution_origin="CURRENT_DAY_RESEARCH_REPLAY")
    response=app.get()
    (destination/"consumer_response.json").write_text(json.dumps(response,ensure_ascii=False,indent=2)+"\n")
    assert len(response["markets"]["HK_CONNECT"]["rows"])==10
    print(json.dumps({"fixture":"SYNTHETIC_REAL_SELECTION_STORE_AND_CONSUMER_NOT_LIVE_MARKET", "path":str(destination/"consumer_response.json"),
                      "selected_rows":10,"selection_status":response["markets"]["HK_CONNECT"]["status"],
                      "selection_trio_status":response["execution_evidence"]["selection_artifact_bindings"]["HK_CONNECT"]["status"]}))
