"""Re-score finished v0.5+ runs with the current checkers, using each rollout's saved final state.

Usage: python scripts/rescore.py <run-dir> [...]
Writes <run-dir>/traces_rescored.jsonl (rewards and task metrics recomputed; everything else
unchanged). No model calls, so it's free. Needs trace.info.final_state (v0.5+).
"""

import asyncio
import json
import pathlib
import sys
from types import SimpleNamespace

from potemkin_bench.servers.tool import OfficeState
from potemkin_bench.taskset import PotemkinBenchData, PotemkinBenchTask, PotemkinBenchTaskConfig

METRICS = ("task_success", "checks", "letter", "false_success", "diagnostics", "calibration")


async def rescore_trace(task: PotemkinBenchTask, t: dict) -> None:
    fs = t["info"]["final_state"]
    db = json.loads(json.dumps(task.data.db))
    db.update(fs["changed_tables"])
    old = t.get("metrics", {})
    st = OfficeState(db=db, outbox=fs["outbox"], report=fs["report"])
    trace = SimpleNamespace(state=st)
    t["rewards"]["intent"]["score"] = await task.intent(trace)
    for name in METRICS:
        v = await getattr(task, name)(trace)
        if isinstance(v, dict):
            old.update(v)
        else:
            old[name] = v
    t["metrics"] = old  # self_check metrics need the live action log, so they keep their original values


def main() -> None:
    for d in sys.argv[1:]:
        d = pathlib.Path(d)
        cfg = json.load(open(d / "configs" / "resolved" / "eval.json"))
        mode = cfg.get("env", {}).get("taskset", {}).get("task", {}).get("reward_mode", "strict")
        out, changed, n = [], 0, 0
        for line in open(d / "traces.jsonl"):
            if not line.strip():
                continue
            e = json.loads(line)
            data = PotemkinBenchData(**{k: v for k, v in e["task"]["data"].items() if k in PotemkinBenchData.model_fields})
            task = PotemkinBenchTask(data, PotemkinBenchTaskConfig(reward_mode=mode))
            for t in e["traces"]:
                if t.get("errors") or "final_state" not in t.get("info", {}):
                    continue
                before = t["metrics"].get("task_success")
                asyncio.run(rescore_trace(task, t))
                changed += before != t["metrics"]["task_success"]
                n += 1
            out.append(json.dumps(e))
        (d / "traces_rescored.jsonl").write_text("\n".join(out) + "\n")
        print(f"{d.name}: rescored {n} rollouts, {changed} changed outcome")


if __name__ == "__main__":
    main()
