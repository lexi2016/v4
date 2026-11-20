#!/usr/bin/env bash
# Use a disposable Docker host and immutable python image SHA256. Keep evidence after teardown.
set -euo pipefail
if [[ $# != 2 ]]; then
  printf '%s\n' 'Usage: bash research/p515_recovery_v8/run_two_container_witness.sh EVIDENCE_DIR python@sha256:<digest>' >&2
  exit 2
fi
[[ "$2" =~ @sha256:[0-9a-f]{64}$ ]] || { printf '%s\n' 'Pass an immutable Python slim image reference.' >&2; exit 2; }
command -v docker >/dev/null || { printf '%s\n' 'BLOCKED: Docker CLI is unavailable.' >&2; exit 2; }
docker info >/dev/null
mkdir -p "$1"
out="$(cd "$1" && pwd -P)"
[[ ! -e "$out/topology.json" ]] || { printf '%s\n' 'Use a fresh evidence directory for each run.' >&2; exit 2; }
stamp="p515v8-$(date -u +%Y%m%d%H%M%S)-$$"
image="$stamp:synthetic"
authority="$stamp-authority"
first="$stamp-worker-a"
second="$stamp-worker-b"
volume="$stamp-authority-volume"
cleanup() {
  docker logs "$authority" >"$out/authority.stdout.log" 2>"$out/authority.stderr.log" || true
  for c in "$first" "$second" "$authority"; do
    docker rm -f "$c" >/dev/null 2>&1 || true
  done
  docker volume rm "$volume" >/dev/null 2>&1 || true
}
trap cleanup EXIT
docker build --build-arg "PYTHON_IMAGE=$2" -t "$image" -f research/p515_recovery_v8/Dockerfile research/p515_recovery_v8 >"$out/build.log" 2>&1
docker info --format '{{json .ID}}' >"$out/host_id.json"
docker version --format '{{json .Server}}' >"$out/host_runtime.json"
docker volume create "$volume" >"$out/volume_name.txt"
docker volume inspect "$volume" >"$out/volume_metadata.json"
docker run -d --network none --name "$authority" --mount "type=volume,source=$volume,target=/state" "$image" \
  python -m research.p515_recovery_v8.test_v8_container_boot >"$out/authority_id.txt"
for lap in $(seq 1 160); do
  if docker exec "$authority" test -S /state/authority/authority.sock; then
    break
  fi
  sleep 0.25
done
docker exec "$authority" test -S /state/authority/authority.sock
for worker in "$first" "$second"; do
  docker run -d --network none --name "$worker" -e P515_V8_CONTEST_GATE=/state/release \
    --mount "type=volume,source=$volume,target=/state,readonly" "$image" \
    python -m research.p515_recovery_v8.test_v8_fixtures /state/authority/anchor.json /state/request.json >"$out/$worker.id"
done
for lap in $(seq 1 120); do
  if docker logs "$first" 2>&1 | grep -q '^READY ' && docker logs "$second" 2>&1 | grep -q '^READY '; then
    break
  fi
  sleep 0.25
done
docker logs "$first" 2>&1 | grep -q '^READY '
docker logs "$second" 2>&1 | grep -q '^READY '
docker inspect "$authority" "$first" "$second" --format '{{json .}}' >"$out/container_metadata.jsonl"
docker exec "$authority" touch /state/release
for worker in "$first" "$second"; do
  [[ "$(docker wait "$worker")" == 0 ]]
  docker logs "$worker" >"$out/$worker.stdout.json" 2>"$out/$worker.stderr.log"
done
docker exec "$authority" python -c 'import json; from pathlib import Path; from research.p515_recovery_v8.authority import AuthorityClient; print(json.dumps(AuthorityClient(Path("/state/authority/anchor.json")).request("status")))' >"$out/authority_status.json"
docker exec "$authority" python -c 'from hashlib import sha256; from pathlib import Path; print({x.name:sha256(x.read_bytes()).hexdigest() for x in Path("/state/authority").glob("ledger.sqlite*")})' >"$out/ledger_sha.txt"
docker exec "$authority" sh -c 'for f in /state/authority/*audit*.jsonl /state/authority/*rpc*.jsonl /state/authority/requests.jsonl; do if [ -f "$f" ]; then cat "$f"; fi; done' >"$out/rpc_audit.jsonl"
python3 - "$out" "$volume" <<'PY'
import json,sys
from pathlib import Path
root=Path(sys.argv[1])
volume=sys.argv[2]
traces=[json.loads(p.read_bytes()) for p in sorted(root.glob('*worker-*.stdout.json'))]
containers=[json.loads(l) for l in (root/'container_metadata.jsonl').read_text().splitlines()]
st=json.loads((root/'authority_status.json').read_bytes())
host=json.loads((root/'host_id.json').read_bytes())
requests=[json.loads(line) for line in (root/'rpc_audit.jsonl').read_text().splitlines()]
reservations=[r for r in requests if r.get('op')=='reserve']
assert len(reservations)==2 and len({r['authorization_id'] for r in reservations})==1
assert sum(r['response'].get('state')=='RESERVED' for r in reservations)==1
assert all(sum(r.get('op')==op for r in requests)==2 for op in ('start','commit'))
assert host and len(traces)==2 and len({c['Id'] for c in containers})==3
assert all([m for m in c['Mounts'] if m.get('Name')==volume and m['Destination']=='/state'] for c in containers)
assert all(not m['RW'] for c in containers[1:] for m in c['Mounts'] if m.get('Name')==volume)
wins=[r for r in traces if r.get('execute',{}).get('state')=='COMMITTED']
assert len(wins)==1 and len(st['transactions'])==1 and len(st['starts'])==3
assert all('REMOTE_MUTATION_FORBIDDEN' in r['start'] and 'REMOTE_MUTATION_FORBIDDEN' in r['commit'] for r in traces)
assert not any(st['real_counts'].values())
report={'scope':'SYNTHETIC_TEST_ONLY','container_ids':[c['Id'] for c in containers[1:]],
        'authority_container_id':containers[0]['Id'],'host_id':host,'shared_volume':volume,
        'authority_id':st['authority_id'],'ledger_sha':(root/'ledger_sha.txt').read_text().strip(),
        'consumer_count':len(wins),'raw_traces':traces,'rpc_event_count':len(requests),'formal_fit':0}
(root/'topology.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report))
PY
