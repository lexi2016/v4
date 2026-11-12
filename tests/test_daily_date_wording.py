from pathlib import Path
import subprocess


def test_quote_coverage_and_candidate_source_date_are_distinct():
    path=Path(__file__).resolve().parents[1]/'apps/web/public/research-panel/workbench-host/dot/shell/workbench.local.mjs'
    source=path.read_text();source=source[source.index('const candidateSourceNote='):source.index('import {sortDisplayStocks')]
    run=subprocess.run(['/Users/lexi/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node','-e',
        "const day={source_date:'2026-11-10'},document={getElementById:()=>({})};"+source+";console.log(observationHeader({capture_kind:'OFFICIAL_DAILY_ARCHIVE',observation_date:'2026-11-11',recorded_at:'now',rows:[{status:'DATED_DAILY_ARCHIVE'}]}));"],text=True,capture_output=True,check=True)
    assert '行情覆盖 1/1' in run.stdout and '行情日 2026-11-11' in run.stdout and '候选来源日 2026-11-10' in run.stdout
    assert '数值' not in run.stdout and '未发布' not in run.stdout
