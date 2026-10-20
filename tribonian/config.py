import os
import sys
from pathlib import Path

from dotenv import load_dotenv

DEFAULT_MODEL = "minimax/minimax-m3.1-flash:free"
EXAMPLE_DRIVE = "https://drive.google.com/drive/folders/1x6EKNkVw6PlFVTr6cGrsVscmRuwqGrXd"


def load_settings() -> tuple[str, str]:
    base = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent.parent
    load_dotenv(base / ".env")
    return os.getenv("OPENROUTER_API_KEY", ""), os.getenv("OPENROUTER_MODEL", DEFAULT_MODEL)
