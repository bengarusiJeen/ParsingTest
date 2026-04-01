import runpy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "ParsingTest"))
runpy.run_path(str(Path(__file__).parent / "ParsingTest" / "main.py"), run_name="__main__")
