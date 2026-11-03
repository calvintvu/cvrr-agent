import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

DATA_DIR = Path(os.environ.get("CVRR_DATA_DIR") or ".").expanduser()
