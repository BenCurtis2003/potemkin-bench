"""Leaderboard tooling: estimate cost before spending, run evals with fixed settings, summarize results.

    # 1. what would it cost? (live prices from Prime Inference, token usage from past runs)
    python scripts/leaderboard.py estimate -m deepseek/deepseek-v4.1-flash -m Qwen/Qwen3.5-9B \
        --difficulty v1 --num-tasks 78 --attempts 2

    # 2. run it (refuses unless the HIGH estimate fits under --budget-usd)
    python scripts/leaderboard.py run -m deepseek/deepseek-v4.1-flash --difficulty v1 --num-tasks 78 \
        --attempts 2 --split test --budget-usd 25 --out leaderboard_runs/2026-10

    # 3. summarize every run in a folder into a table with task-level bootstrap CIs
    python scripts/leaderboard.py summarize leaderboard_runs/2026-10

Estimates use per-rollout token counts measured on earlier PotemkinBench runs (scripts/token_profile.json),
by template level. "typical" uses the median rollout; "high" uses the heaviest model's 90th percentile,
billed at full input price (no cache discount). New templates have no runs yet, so their level is the proxy.
"""

from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import os
import pathlib
import random
import shlex
import subprocess
import sys
import tomllib

ROOT = pathlib.Path(__file__).resolve().parents[1]
PROFILE = ROOT / "scripts" / "token_profile.json"
HIDDEN_SEED_FILE = pathlib.Path.home() / ".config" / "potemkin-bench" / "hidden_seed"  # never in the repo
SETTINGS = {"harness": "null", "runtime": "subprocess", "rollout_timeout_s": 2400, "concurrency": 4, "scoring": "1.0"}


def version() -> str:
    return tomllib.loads((ROOT / "environments/potemkin_bench/pyproject.toml").read_text())["project"]["version"]


# --- cost estimate ----------------------------------------------------------------------------

def level_mix(difficulty: str, num_tasks: int, families: list[str] | None = None) -> dict[str, int]:
    """How many generated tasks fall in each template level (tasks cycle through the families)."""
    from potemkin_bench.taskset import LEVELS
    from potemkin_bench.templates import TEMPLATES
    fams = families or LEVELS[difficulty]
    mix: dict[str, int] = {}
    for i in range(num_tasks):
        lvl = TEMPLATES[fams[i % len(fams)]].level
        mix[lvl] = mix.get(lvl, 0) + 1
    return mix


def live_prices(models: list[str]) -> dict[str, dict]:
    out = subprocess.run(["prime", "inference", "models", "--output", "json"], capture_output=True, text=True, timeout=60,
                         env={**os.environ, "PRIME_DISABLE_VERSION_CHECK": "1"})
    data = json.loads(out.stdout)
    data = data.get("data", data) if isinstance(data, dict) else data
    by_id = {m["id"]: m.get("pricing") or {} for m in data}
    missing = [m for m in models if m not in by_id]
    if missing:
        raise SystemExit(f"no Prime Inference price for: {missing} (check `prime inference models -q <name>`)")
    return {m: by_id[m] for m in models}


def rollout_cost(tokens: dict, price: dict, cache: bool) -> float:
    pin, pout = price.get("input_usd_per_mtok") or 0.0, price.get("output_usd_per_mtok") or 0.0
    pcache = price.get("cache_read_usd_per_mtok")
    if cache and pcache is not None:
        cost_in = tokens["new_input"] * pin + max(0, tokens["prompt"] - tokens["new_input"]) * pcache
    else:
        cost_in = tokens["prompt"] * pin
    return (cost_in + tokens["output"] * pout) / 1e6


def estimate(models: list[str], prices: dict[str, dict], mix: dict[str, int], attempts: int) -> dict:
    prof = json.loads(PROFILE.read_text())["levels"]
    rows = {}
    for m in models:
        typ = sum(n * attempts * rollout_cost(prof[lvl]["typical"], prices[m], cache=True) for lvl, n in mix.items())
        high = sum(n * attempts * rollout_cost(prof[lvl]["high"], prices[m], cache=False) for lvl, n in mix.items())
        rows[m] = {"typical_usd": round(typ, 2), "high_usd": round(high, 2)}
    return {"rows": rows, "typical_usd": round(sum(r["typical_usd"] for r in rows.values()), 2),
            "high_usd": round(sum(r["high_usd"] for r in rows.values()), 2),
            "rollouts": sum(mix.values()) * attempts * len(models)}


def print_estimate(est: dict, mix: dict[str, int], attempts: int) -> None:
    print(f"tasks by level: {mix}; attempts per task: {attempts}; rollouts: {est['rollouts']}")
    print(f"{'model':45s} {'typical':>9s} {'high':>9s}")
    for m, r in est["rows"].items():
        print(f"{m:45s} ${r['typical_usd']:8.2f} ${r['high_usd']:8.2f}")
    print(f"{'TOTAL':45s} ${est['typical_usd']:8.2f} ${est['high_usd']:8.2f}")
    print("typical = median measured rollout with cache discounts; high = heaviest model's p90, no cache discount.")


# --- run --------------------------------------------------------------------------------------

def eval_command(model: str, a, out_dir: pathlib.Path) -> list[str]:
    files = "true" if a.difficulty in ("v1", "finance_v1", "it", "procurement", "crm") or a.files_tools else "false"
    cmd = [str(ROOT / ".venv/bin/vf-eval"), "potemkin-bench", "-m", model, "-n", str(a.num_tasks), "-r", str(a.attempts),
           "-c", str(SETTINGS["concurrency"]), "-o", str(out_dir),
           "--env.agent.harness.id", SETTINGS["harness"], "--env.agent.runtime.type", SETTINGS["runtime"],
           "--env.agent.timeout.rollout", str(SETTINGS["rollout_timeout_s"]),
           "--env.taskset.split", a.split, "--env.taskset.difficulty", a.difficulty,
           "--env.taskset.num-tasks", str(a.num_tasks), "--env.taskset.task.scoring", SETTINGS["scoring"],
           "--env.taskset.task.files-tools", files]
    if a.base_url:
        cmd += ["--client.base-url", a.base_url, "--client.api-key-var", a.api_key_var]
    if a.push:
        cmd.append("--push")
    return cmd


def run(a) -> None:
    mix = level_mix(a.difficulty, a.num_tasks)
    prices = json.loads(pathlib.Path(a.prices).read_text()) if a.prices else live_prices(a.model)
    est = estimate(a.model, prices, mix, a.attempts)
    print_estimate(est, mix, a.attempts)
    if est["high_usd"] > a.budget_usd:
        raise SystemExit(f"REFUSING: high estimate ${est['high_usd']} exceeds --budget-usd {a.budget_usd}")
    if a.split == "hidden" and not os.environ.get("POTEMKIN_HIDDEN_SEED"):
        if not HIDDEN_SEED_FILE.exists():
            raise SystemExit(f"split 'hidden' needs POTEMKIN_HIDDEN_SEED or {HIDDEN_SEED_FILE}")
        os.environ["POTEMKIN_HIDDEN_SEED"] = HIDDEN_SEED_FILE.read_text().strip()  # passed to vf-eval, never printed
    out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    sha = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    manifest = {"benchmark_version": version(), "git_sha": sha, "date": dt.date.today().isoformat(),
                "split": a.split, "difficulty": a.difficulty, "num_tasks": a.num_tasks, "attempts": a.attempts,
                "settings": SETTINGS, "models": a.model, "estimate": est}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1))
    for m in a.model:
        cmd = eval_command(m, a, out)
        print("$", shlex.join(cmd))
        if not a.dry_run:
            subprocess.run(cmd, check=True)


# --- summarize --------------------------------------------------------------------------------

def load_runs(folder: str) -> dict[str, list[dict]]:
    """model -> list of {task, success, false_success, truthful, should_claim, claimed} rollouts."""
    runs: dict[str, list[dict]] = {}
    for f in sorted(glob.glob(os.path.join(folder, "**", "traces.jsonl"), recursive=True)):
        for line in open(f):
            row = json.loads(line)
            for tr in row.get("traces", []):
                met = tr.get("metrics") or {}
                model = ((tr.get("agent") or {}).get("config") or {}).get("model") or pathlib.Path(f).parent.name
                if "task_success" not in met:
                    continue
                runs.setdefault(model, []).append({
                    "task": (tr.get("task") or {}).get("data", {}).get("id"),
                    "success": met["task_success"], "false_success": met.get("false_success", 0.0),
                    "truthful": met.get("calib_honest", 0.0), "should_claim": met.get("calib_should_claim"),
                    "under_claim": met.get("calib_under_claim", 0.0),
                    "honest_success": met.get("honest_success", float(met["task_success"] and met.get("calib_honest", 0.0)))})
    return runs


def bootstrap(rows: list[dict], key: str, n: int = 2000, seed: int = 0) -> tuple[float, float, float]:
    """Mean and 95% CI, resampling tasks (all attempts of a task stay together)."""
    by_task: dict[str, list[float]] = {}
    for r in rows:
        by_task.setdefault(r["task"], []).append(float(r[key]))
    tasks = sorted(by_task)
    mean = sum(sum(v) for v in by_task.values()) / sum(len(v) for v in by_task.values())
    rng = random.Random(seed)
    stats = []
    for _ in range(n):
        pick = [by_task[rng.choice(tasks)] for _ in tasks]
        stats.append(sum(sum(v) for v in pick) / sum(len(v) for v in pick))
    stats.sort()
    return mean, stats[int(0.025 * n)], stats[int(0.975 * n) - 1]


def claim_recall(rows: list[dict]) -> float | None:
    eligible = [r for r in rows if r["should_claim"]]
    return None if not eligible else 1 - sum(r["under_claim"] for r in eligible) / len(eligible)


def summarize(folder: str) -> str:
    runs = load_runs(folder)
    if not runs:
        raise SystemExit(f"no scored traces under {folder}")
    lines = ["| Model | Honest success | Real success | False success | Truthful report | Claim recall | Rollouts |",
             "|---|---|---|---|---|---|---|"]
    fmt = lambda t: f"{100 * t[0]:.0f}% [{100 * t[1]:.0f}–{100 * t[2]:.0f}]"  # noqa: E731
    for model in sorted(runs, key=lambda m: -bootstrap(runs[m], "honest_success", 200)[0]):
        rows = runs[model]
        cr = claim_recall(rows)
        lines.append(f"| {model} | {fmt(bootstrap(rows, 'honest_success'))} | {fmt(bootstrap(rows, 'success'))} | "
                     f"{fmt(bootstrap(rows, 'false_success'))} | {fmt(bootstrap(rows, 'truthful'))} | "
                     f"{'n/a' if cr is None else f'{100 * cr:.0f}%'} | {len(rows)} |")
    man = pathlib.Path(folder) / "manifest.json"
    head = ""
    if man.exists():
        m = json.loads(man.read_text())
        head = (f"PotemkinBench {m['benchmark_version']} · split {m['split']} · {m['difficulty']} · "
                f"{m['num_tasks']} tasks × {m['attempts']} attempts · scoring {m['settings']['scoring']}\n\n")
    return head + "\n".join(lines) + "\n\n95% CIs: task-level bootstrap (2,000 resamples).\n"


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("estimate", "run"):
        p = sub.add_parser(name)
        p.add_argument("-m", "--model", action="append", required=True)
        p.add_argument("--difficulty", default="v1")
        p.add_argument("--num-tasks", type=int, default=78)
        p.add_argument("--attempts", type=int, default=2)
        p.add_argument("--prices", help="JSON file {model: {input_usd_per_mtok, output_usd_per_mtok, cache_read_usd_per_mtok}} instead of live prices")
        if name == "run":
            p.add_argument("--split", default="test", choices=["test", "hidden", "dev"])
            p.add_argument("--budget-usd", type=float, required=True)
            p.add_argument("--out", required=True)
            p.add_argument("--base-url")
            p.add_argument("--api-key-var", default="PRIME_API_KEY")
            p.add_argument("--files-tools", action="store_true")
            p.add_argument("--push", action="store_true")
            p.add_argument("--dry-run", action="store_true")
    s = sub.add_parser("summarize")
    s.add_argument("folder")
    a = ap.parse_args(argv)
    if a.cmd == "estimate":
        mix = level_mix(a.difficulty, a.num_tasks)
        prices = json.loads(pathlib.Path(a.prices).read_text()) if a.prices else live_prices(a.model)
        print_estimate(estimate(a.model, prices, mix, a.attempts), mix, a.attempts)
    elif a.cmd == "run":
        run(a)
    else:
        print(summarize(a.folder))


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT / "environments" / "potemkin_bench"))
    main()
