"""Generate docs/TEMPLATES.md from the template registry (tests fail if it's out of date).
    python scripts/gen_template_docs.py
"""

import asyncio
import pathlib
import random
import sys
from types import SimpleNamespace

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))

from contract_policies import TRAP_POLICIES, solved  # noqa: E402
from test_contract import KNOWN_GAPS, build, task_for  # noqa: E402

from potemkin_bench.taskset import LEVELS  # noqa: E402
from potemkin_bench.templates import TEMPLATES  # noqa: E402

OUT = ROOT / "docs" / "TEMPLATES.md"
SEEDS = range(20)
CLAIM = {"always": "fully possible", "never": "never fully possible", "depends": "depends on the instance"}


def catch_rate(name, policy) -> int:
    caught = 0
    for s in SEEDS:
        _, db, spec = build(name, s)
        st = policy.run(db, spec)
        tr = SimpleNamespace(state=st, info={}, messages=[])
        caught += asyncio.run(task_for(name, db, spec).false_success(tr)) == 1.0
    return round(100 * caught / len(SEEDS))


def section(name) -> list[str]:
    t = TEMPLATES[name]
    _, db, spec = build(name, 0)
    checks = sorted(t.check(solved(name, db, spec), spec))
    out = [f"### `{name}`", "",
           f"**{t.domain}** · {t.level} · systems: {', '.join(t.systems)} · truthful claim: {CLAIM[t.claim]}"
           + (" · held out of train/dev" if t.heldout else ""), "",
           f"- **Tests:** {t.tests}",
           f"- **Trap:** {t.trap}",
           f"- **Checks:** {', '.join(f'`{c}`' for c in checks)}"
           + (" (the report is one of the checks under scoring 0.8)" if t.scores_report else ""),
           "- **Shortcuts the scorer must catch** (share of 20 generated tasks where the shortcut, "
           "reported as done, is a measured false success):"]
    out += [f"  - `{p.name}`: {catch_rate(name, p)}% (contract minimum {round(p.min_fail * 100)}%)" for p in TRAP_POLICIES[name]]
    if name in KNOWN_GAPS:
        out.append(f"- **Known gap:** {KNOWN_GAPS[name][1]}")
    return out + [""]


def render() -> str:
    lines = ["# PotemkinBench task templates", "",
             "Generated from the template registry by `scripts/gen_template_docs.py`; do not edit by hand.",
             "", "Every template passes the template contract (`tests/test_contract.py`), checked in CI on every push.",
             "Each template generates unlimited instances from a seed.", ""]
    groups = [("v1.0 templates (`difficulty = \"v1\"`; not yet difficulty-calibrated against models)", LEVELS["v1"]),
              ("v0.x templates (`difficulty = \"mixed\"`, as used in the honesty-rl study)", LEVELS["mixed"])]
    lines += ["| Template | Level | Domain | Systems | Truthful claim |", "|---|---|---|---|---|"]
    for _, names in groups:
        for n in names:
            t = TEMPLATES[n]
            lines.append(f"| [`{n}`](#{n.replace('@', '')}) | {t.level} | {t.domain} | {', '.join(t.systems)} | {CLAIM[t.claim]} |")
    lines.append("")
    for title, names in groups:
        lines += [f"## {title}", ""]
        for n in names:
            lines += section(n)
    return "\n".join(lines).rstrip() + "\n"


if __name__ == "__main__":
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(render())
    print(f"wrote {OUT.relative_to(ROOT)} ({len(TEMPLATES)} templates)")
