"""Load the explicit complete candidate used for this verification."""
from pathlib import Path
import os,sys
APP=Path(os.environ["STAGE_CHECK_APP"]).resolve()
sys.path.insert(0,str(APP))
