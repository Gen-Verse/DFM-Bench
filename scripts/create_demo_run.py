"""Create a tiny synthetic agent run; no credentials, patient data or model calls."""
import argparse
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tests'))
from test_foundations import fixture

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output', required=True)
args = parser.parse_args()
root = Path(args.output).resolve()
if root.exists():
    parser.error('Output exists; choose a new path')
root.parent.mkdir(parents=True, exist_ok=True)
db = fixture(root)
db.close()
print(root/'state.sqlite')
