"""Zero-FIT Docker smoke topology for a real shared-volume witness."""
from pathlib import Path

from .authority import Authority, initialize_authority, serve
from .test_v8_fixtures import create_fixture, reserve_data, signed_bundle, write_json

STATE = Path("/state")
VOL = STATE / "authority"

if __name__ == "__main__":
    fixture, prepared, private, trust = create_fixture(STATE / "SYNTHETIC_TEST_ONLY")
    anchor = initialize_authority(VOL, fixture, trust)
    authority = Authority(anchor)
    try:
        authority_id = authority.check()["authority_id"]
    finally:
        authority.close()
    auth, package = signed_bundle(fixture, prepared, private, authority_id, authid="SYNTHETIC-CONTAINER-CONTEST")
    write_json(STATE / "request.json", reserve_data(auth, package))
    serve(anchor)
