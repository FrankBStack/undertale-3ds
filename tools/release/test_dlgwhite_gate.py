"""Run the shipping helper and compiler routing checks in the release suite."""
from pathlib import Path
import subprocess
import sys
import unittest

class DlgwhiteGate(unittest.TestCase):
    def test_recorded_fill(self):
        root=Path(__file__).resolve().parents[2]
        subprocess.run([sys.executable,'-I',str(root/'tools/analysis/test_dlgwhite.py')],
                       stdin=subprocess.DEVNULL,check=True,timeout=90)

if __name__=='__main__':unittest.main()
