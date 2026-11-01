"""One fixed, short-lived Stage evidence consumer. No service or scheduler."""
import argparse
from infrastructure.report_evidence_index import canonical
from infrastructure.report_evidence_sidecar import consume_sidecar_job

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--job-id',required=True)
    args=parser.parse_args()
    result=consume_sidecar_job(args.job_id)
    print(canonical(result))
    return 0 if result['status'] in {'COMPLETED','REUSED','BUSY'} else 1

if __name__=='__main__':raise SystemExit(main())
