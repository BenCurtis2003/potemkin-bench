"""Regenerate tests/fixtures/generator_fingerprints.json.

Run this only when a generator change is intended, and bump the benchmark version in the same
change: old scores are not comparable to tasks built by a changed generator.
    python scripts/update_fingerprints.py
"""

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))

from test_contract import FINGERPRINTS, NAMES, STUDY_SETS, fingerprint, taskset_fingerprint  # noqa: E402

import tomllib  # noqa: E402

__version__ = tomllib.loads((ROOT / "environments/potemkin_bench/pyproject.toml").read_text())["project"]["version"]

data = {
    "version": __version__,
    "templates": {n: fingerprint(n) for n in NAMES},
    "task_sets": {k: taskset_fingerprint(**kw) for k, kw in STUDY_SETS.items()},
}
FINGERPRINTS.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n")
print(f"wrote {FINGERPRINTS.relative_to(ROOT)} ({len(data['templates'])} templates, version {__version__})")
