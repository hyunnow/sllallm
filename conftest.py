"""Make `src/` importable for tests without an editable install (works on Colab)."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent / "src"))
