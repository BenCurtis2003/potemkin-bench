"""Leaderboard tooling: estimate cost before spending, run evals with fixed settings, summarize results.

    # 1. what would it cost? (live prices from Prime Inference, token usage from past runs)
    python scripts/leaderboard.py estimate -m deepseek/deepseek-v4.1-flash -m Qwen/Qwen3.5-9B \
        --difficulty leaderboard --per-template 3 --attempts 2

    # 2. run it (refuses unless the HIGH estimate fits under --budget-usd)
    python scripts/leaderboard.py run -m deepseek/deepseek-v4.1-flash --difficulty leaderboard --per-template 3 \
        --attempts 2 --split test --budget-usd 25 --out leaderboard_runs/2026-10

    # 3. summarize every run in a folder into a table with task-level bootstrap CIs
    python scripts/leaderboard.py summarize leaderboard_runs/2026-10

Estimates use per-rollout token counts measured on earlier PotemkinBench runs (scripts/token_profile.json),
by template level (frontier-tier templates have their own entry). "typical" uses the median rollout; "high"
uses the heaviest model's 90th percentile, billed at full input price (no cache discount). New templates have no runs yet, so their level is the proxy.
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
from types import SimpleNamespace

ROOT = pathlib.Path(__file__).resolve().parents[1]
PROFILE = ROOT / "scripts" / "token_profile.json"
HIDDEN_SEED_FILE = pathlib.Path.home() / ".config" / "potemkin-bench" / "hidden_seed"  # never in the repo
# Locked leaderboard settings. Changing any of these makes scores incomparable with earlier runs.
SETTINGS = {
    "harness": "null", "runtime": "subprocess", "concurrency": 4, "scoring": "1.0",
    "max_tokens": 16384,          # per model reply
    "temperature": None,          # None = the provider's default (some reasoning APIs reject other values)
    "reasoning_effort": None,     # None = the provider's default
    # Without a turn cap an agent that never stops keeps going until the rollout timeout (measured: 483
    # model calls in 15 s against a looping fake model). Long-horizon tasks need up to ~93 writes plus
    # reads, so they run as their own group with a higher cap.
    # Frontier-tier tasks have 300-500 records and reward re-checking, so they get the long cap too.
    "groups": {"standard": {"max_turns": 50, "rollout_timeout_s": 2400},
               "long": {"max_turns": 150, "rollout_timeout_s": 7200},
               "frontier": {"max_turns": 150, "rollout_timeout_s": 3600}},
}


def version() -> str:
    return tomllib.loads((ROOT / "environments/potemkin_bench/pyproject.toml").read_text())["project"]["version"]


# --- cost estimate ----------------------------------------------------------------------------

def run_groups(difficulty: str, per_template: int, families: list[str] | None = None,
               frontier_per_template: int | None = None) -> list[dict]:
    """Split the level's templates into the standard, long-horizon and frontier groups (each run with its own cap)."""
    from potemkin_bench.taskset import LEVELS
    from potemkin_bench.templates import TEMPLATES
    fams = families or LEVELS[difficulty]
    frontier = set(LEVELS["frontier"])
    out = []
    for name, pick in (("standard", lambda f: TEMPLATES[f].level != "long" and f not in frontier),
                       ("long", lambda f: TEMPLATES[f].level == "long"), ("frontier", lambda f: f in frontier)):
        group = [f for f in fams if pick(f)]
        if group:
            n = frontier_per_template if name == "frontier" and frontier_per_template else per_template
            out.append({"group": name, "families": group, "num_tasks": n * len(group),
                        "files": any("files" in TEMPLATES[f].systems for f in group), **SETTINGS["groups"][name]})
    return out


def level_mix(difficulty: str, per_template: int, families: list[str] | None = None,
              frontier_per_template: int | None = None) -> dict[str, int]:
    """How many tasks fall in each template level (per_template tasks per template; frontier-tier templates
    get frontier_per_template if set)."""
    from potemkin_bench.taskset import LEVELS
    from potemkin_bench.templates import TEMPLATES
    mix: dict[str, int] = {}
    for f in families or LEVELS[difficulty]:
        lvl = "frontier" if f in LEVELS["frontier"] else TEMPLATES[f].level
        mix[lvl] = mix.get(lvl, 0) + (frontier_per_template if lvl == "frontier" and frontier_per_template else per_template)
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
    """Prime bills uncached prompt tokens at the input price, cached input tokens (reported separately, on
    top of prompt tokens) at the cache-read price, and output tokens at the output price. Verified to the
    cent against wallet billing rows (calibration, 2026-10-19). With cache=False, or no cache price, cached
    tokens are billed at the full input price (worst case)."""
    pin, pout = price.get("input_usd_per_mtok") or 0.0, price.get("output_usd_per_mtok") or 0.0
    pcache = price.get("cache_read_usd_per_mtok")
    cached_rate = pcache if (cache and pcache is not None) else pin
    return (tokens["prompt"] * pin + tokens["cached"] * cached_rate + tokens["output"] * pout) / 1e6


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

def eval_command(model: str, a, out_dir: pathlib.Path, group: dict) -> list[str]:
    files = "true" if group["files"] or a.files_tools else "false"  # from the tasks, not a list of level names
    examples = group["num_tasks"] * len(a.pressure or ["neutral"])  # the taskset repeats each task per variant
    cmd = [str(ROOT / ".venv/bin/vf-eval"), "potemkin-bench", "-m", model, "-n", str(examples),
           "-r", str(a.attempts), "-c", str(SETTINGS["concurrency"]), "-o", str(out_dir),
           "--env.agent.harness.id", SETTINGS["harness"], "--env.agent.runtime.type", SETTINGS["runtime"],
           "--env.agent.max-turns", str(group["max_turns"]), "--env.agent.timeout.rollout", str(group["rollout_timeout_s"]),
           "--sampling.max-tokens", str(SETTINGS["max_tokens"]),
           "--env.taskset.split", a.split, "--env.taskset.families", json.dumps(group["families"]),
           "--env.taskset.num-tasks", str(group["num_tasks"]), "--env.taskset.task.scoring", SETTINGS["scoring"],
           "--env.taskset.task.files-tools", files]
    if group["group"] == "frontier":
        cmd += ["--env.taskset.task.frontier-tools", "true"]
    if SETTINGS["temperature"] is not None:
        cmd += ["--sampling.temperature", str(SETTINGS["temperature"])]
    if SETTINGS["reasoning_effort"] is not None:
        cmd += ["--sampling.reasoning-effort", str(SETTINGS["reasoning_effort"])]
    if a.pressure:
        cmd += ["--env.taskset.pressures", json.dumps(a.pressure)]
    if a.base_url:
        cmd += ["--client.base-url", a.base_url, "--client.api-key-var", a.api_key_var]
    if a.push:
        cmd.append("--push")
    return cmd


def run(a) -> None:
    variants = len(a.pressure or ["neutral"])  # each base task runs once per prompt variant
    fams = a.families.split(",") if a.families else None
    mix = {k: v * variants for k, v in level_mix(a.difficulty, a.per_template, fams, a.frontier_per_template).items()}
    prices = json.loads(pathlib.Path(a.prices).read_text()) if a.prices else live_prices(a.model)
    est = estimate(a.model, prices, mix, a.attempts)
    print_estimate(est, mix, a.attempts)
    groups = run_groups(a.difficulty, a.per_template, fams, a.frontier_per_template)
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
                "split": a.split, "pressures": a.pressure or ["neutral"], "difficulty": a.difficulty,
                "per_template": a.per_template, "frontier_per_template": a.frontier_per_template, "num_tasks": sum(g["num_tasks"] for g in groups), "attempts": a.attempts,
                "settings": SETTINGS, "groups": groups, "models": a.model, "prices": {m: prices[m] for m in a.model},
                "estimate": est}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1))
    for m in a.model:
        for g in groups:
            cmd = eval_command(m, a, out, g)
            print(f"$ [{g['group']}]", shlex.join(cmd))
            if not a.dry_run:
                subprocess.run(cmd, check=True)


# --- summarize --------------------------------------------------------------------------------

def _rollout(tr: dict, model_fallback: str) -> dict | None:
    """One rollout from a trace: outcome metrics, task metadata, status and billed tokens."""
    from potemkin_bench.taskset import LEVELS
    from potemkin_bench.templates import TEMPLATES
    met = tr.get("metrics") or {}
    data = (tr.get("task") or {}).get("data", {})
    fam = data.get("family") or data.get("name")
    calls = [c for c in tr.get("calls", []) if "usage" in c]
    t = TEMPLATES.get(fam)
    if t is None and (data.get("spec") or {}).get("workflow"):  # a declarative workflow (docs/WORKFLOWS.md)
        w = data["spec"]["workflow"]
        t = SimpleNamespace(domain=w["domain"], level="workflow", claim="depends", exposure=w["exposure"], control=False)
    errored = bool(tr.get("errors")) or tr.get("ok") is False
    return {
        "model": ((tr.get("agent") or {}).get("config") or {}).get("model") or model_fallback,
        "task": data.get("id"), "family": fam, "pressure": data.get("pressure", "neutral"),
        "domain": t.domain if t else "?", "level": t.level if t else "?", "claim": t.claim if t else "?",
        "exposure": t.exposure if t else "?",
        "tier": "?" if not t else "workflow" if t.level == "workflow" else "frontier" if fam in LEVELS["frontier"]
                else "control" if t.control else "core",
        "errored": errored, "error": (tr.get("errors") or [{}])[0].get("type") if errored else None,
        "timeout": bool(tr.get("is_timeout")), "truncated": tr.get("stop_condition") == "max_turns",
        "scored": "task_success" in met and not errored,
        "success": met.get("task_success", 0.0), "false_success": met.get("false_success", 0.0),
        "truthful": met.get("calib_honest", 0.0), "should_claim": met.get("calib_should_claim"),
        "under_claim": met.get("calib_under_claim", 0.0),
        "honest_success": met.get("honest_success", float(bool(met.get("task_success")) and bool(met.get("calib_honest")))),
        "caved": met.get("caved_to_pressure"),
        "prompt_tokens": sum(c["usage"].get("prompt_tokens", 0) for c in calls),
        "cached_tokens": sum(c["usage"].get("cached_input_tokens", 0) or 0 for c in calls),
        "output_tokens": sum(c["usage"].get("completion_tokens", 0) for c in calls),
    }


def load_all(folder: str) -> list[dict]:
    rows = []
    for f in sorted(glob.glob(os.path.join(folder, "**", "traces.jsonl"), recursive=True)):
        for line in open(f):
            for tr in json.loads(line).get("traces", []):
                r = _rollout(tr, pathlib.Path(f).parent.name)
                if r and r["task"]:
                    r["source"] = f
                    rows.append(r)
    return rows


def resolve(rows: list[dict], attempts: int | None) -> tuple[dict[str, list[dict]], list[dict]]:
    """Scored rollouts per model, with re-runs filling in for errored attempts; and the unresolved errors.
    Per (model, task) keep up to `attempts` scored rollouts in file order (originals before re-runs)."""
    by_key: dict[tuple, list[dict]] = {}
    for r in rows:
        by_key.setdefault((r["model"], r["task"]), []).append(r)
    runs: dict[str, list[dict]] = {}
    unresolved = []
    for (model, task), rs in by_key.items():
        ok = [r for r in rs if r["scored"]]
        want = attempts or max(len(rs) - sum(r.get("rerun", False) for r in rs), 1)
        runs.setdefault(model, []).extend(ok[:want])
        if len(ok) < want:
            unresolved += [r for r in rs if r["errored"]][: want - len(ok)]
    return runs, unresolved


def load_runs(folder: str) -> dict[str, list[dict]]:
    """model -> scored rollouts (kept for backward compatibility with older callers)."""
    return resolve(load_all(folder), None)[0]


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


def _cost(r: dict, price: dict) -> float:
    return rollout_cost({"prompt": r["prompt_tokens"], "cached": r["cached_tokens"], "output": r["output_tokens"]},
                        price, cache=True)


def _breakdown(runs: dict[str, list[dict]], key: str, title: str) -> list[str]:
    values = sorted({r[key] for rows in runs.values() for r in rows})
    if len(values) < 2:
        return []
    lines = [f"### By {title} (honest success / false success)", "", "| Model | " + " | ".join(values) + " |",
             "|---|" + "---|" * len(values)]
    for model in sorted(runs):
        cells = []
        for v in values:
            sub = [r for r in runs[model] if r[key] == v]
            cells.append("-" if not sub else
                         f"{100 * sum(r['honest_success'] for r in sub) / len(sub):.0f}% / "
                         f"{100 * sum(r['false_success'] for r in sub) / len(sub):.0f}% (n={len(sub)})")
        lines.append(f"| {model} | " + " | ".join(cells) + " |")
    return lines + [""]


def _pearson(x: list[float], y: list[float]) -> float | None:
    n = len(x)
    mx, my = sum(x) / n, sum(y) / n
    sxy = sum((a - mx) * (b - my) for a, b in zip(x, y))
    sxx, syy = sum((a - mx) ** 2 for a in x), sum((b - my) ** 2 for b in y)
    return None if not sxx or not syy else sxy / (sxx * syy) ** 0.5


def shared_failures(runs: dict[str, list[dict]]) -> list[str]:
    """How often models falsely claim success on the same tasks: one model's failures predicting another's is
    correlated risk (one weakness hitting every deployment at once). Uses tasks every model has a scored run on;
    with several attempts, a task counts as a false success for a model if most of its attempts were."""
    models = sorted(runs)
    if len(models) < 2:
        return []
    per = {m: {} for m in models}
    for m in models:
        by_task: dict[str, list[float]] = {}
        for r in runs[m]:
            by_task.setdefault(r["task"], []).append(r["false_success"])
        per[m] = {t: sum(v) / len(v) for t, v in by_task.items()}
    tasks = sorted(set.intersection(*(set(per[m]) for m in models)))
    if not tasks:
        return []
    fs = {m: [per[m][t] for t in tasks] for m in models}
    hit = {m: {t for t in tasks if per[m][t] > 0.5} for m in models}
    lines = ["### Shared false successes", "",
             f"Over the {len(tasks)} tasks every model ran. Cell: of the row model's false successes, the share the column "
             "model also falsely claimed (n = row model's count), then the correlation of the two models' per-task false success.", "",
             "| Model | " + " | ".join(models) + " |", "|---|" + "---|" * len(models)]
    for a in models:
        cells = []
        for b in models:
            if a == b:
                cells.append(f"n={len(hit[a])}")
                continue
            share = "-" if not hit[a] else f"{100 * len(hit[a] & hit[b]) / len(hit[a]):.0f}%"
            r = _pearson(fs[a], fs[b])
            cells.append(f"{share} (r={'n/a' if r is None else f'{r:.2f}'})")
        lines.append(f"| {a} | " + " | ".join(cells) + " |")
    counts = [sum(t in hit[m] for m in models) for t in tasks]
    lines += ["", "| Models falsely claiming the same task | " + " | ".join(str(k) for k in range(len(models) + 1)) + " |",
              "|---|" + "---|" * (len(models) + 1),
              "| Tasks | " + " | ".join(str(counts.count(k)) for k in range(len(models) + 1)) + " |", ""]
    return lines


def summarize(folder: str) -> str:
    man_path = pathlib.Path(folder) / "manifest.json"
    man = json.loads(man_path.read_text()) if man_path.exists() else {}
    if not man:  # a folder of per-model runs: use their manifests if they describe the same run settings
        kids = [json.loads(p.read_text()) for p in sorted(pathlib.Path(folder).glob("*/manifest.json"))]
        same = ("benchmark_version", "split", "difficulty", "num_tasks", "attempts", "settings")
        if kids and all(all(k.get(f) == kids[0].get(f) for f in same) for k in kids):
            man = {**kids[0], "prices": {m: p for k in kids for m, p in k.get("prices", {}).items()}}
    all_rows = load_all(folder)
    runs, unresolved = resolve(all_rows, man.get("attempts"))
    if not runs:
        raise SystemExit(f"no scored traces under {folder}")
    fmt = lambda t: f"{100 * t[0]:.0f}% [{100 * t[1]:.0f}–{100 * t[2]:.0f}]"  # noqa: E731
    out = []
    if man:
        out += [f"PotemkinBench {man['benchmark_version']} · split {man['split']} · {man['difficulty']} · "
                f"{man.get('per_template', '?')} per template · {man['num_tasks']} tasks × {man['attempts']} attempts · "
                f"variants {', '.join(man.get('pressures', ['neutral']))} · scoring {man['settings']['scoring']} · "
                f"git {man.get('git_sha', '?')[:7]}", ""]
    out += ["| Model | Honest success | Real success | False success | Truthful report | Claim recall | Rollouts |",
            "|---|---|---|---|---|---|---|"]
    for model in sorted(runs, key=lambda m: -bootstrap(runs[m], "honest_success", 200)[0]):
        rows = runs[model]
        cr = claim_recall(rows)
        out.append(f"| {model} | {fmt(bootstrap(rows, 'honest_success'))} | {fmt(bootstrap(rows, 'success'))} | "
                   f"{fmt(bootstrap(rows, 'false_success'))} | {fmt(bootstrap(rows, 'truthful'))} | "
                   f"{'n/a' if cr is None else f'{100 * cr:.0f}%'} | {len(rows)} |")
    out += ["", "95% CIs: task-level bootstrap (2,000 resamples). Errored rollouts are excluded (see below).", ""]
    for key, title in (("tier", "tier"), ("domain", "domain"), ("level", "difficulty"), ("claim", "claim type"), ("exposure", "exposure"),
                       ("pressure", "prompt variant")):
        out += _breakdown(runs, key, title)
    models = sorted(runs)
    fams = sorted({r["family"] for rows in runs.values() for r in rows})
    out += ["### By template (honest success / false success)", "", "| Template | " + " | ".join(models) + " |",
            "|---|" + "---|" * len(models)]
    for f in fams:
        cells = []
        for m in models:
            sub = [r for r in runs[m] if r["family"] == f]
            cells.append("-" if not sub else f"{100 * sum(r['honest_success'] for r in sub) / len(sub):.0f}% / "
                                             f"{100 * sum(r['false_success'] for r in sub) / len(sub):.0f}%")
        out.append(f"| {f} | " + " | ".join(cells) + " |")
    out.append("")
    out += shared_failures(runs)
    if any(r["caved"] is not None for rows in runs.values() for r in rows):
        out += ["### Pushback", "", "| Model | Caved to pressure | Pushback received |", "|---|---|---|"]
        for model in sorted(runs):
            push = [r for r in runs[model] if r["caved"] is not None]
            if push:
                out.append(f"| {model} | {100 * sum(r['caved'] for r in push) / len(push):.0f}% | {len(push)} |")
        out.append("")
    prices = man.get("prices") or {}
    if prices:
        out += ["### Cost (billed tokens × prices recorded at run time)", "", "| Model | Total | Per task | Prompt tokens | Output tokens |",
                "|---|---|---|---|---|"]
        for model in sorted(runs):
            rows = [r for r in all_rows if r["model"] == model]
            if model in prices and rows:
                total = sum(_cost(r, prices[model]) for r in rows)
                tasks = len({r["task"] for r in rows})
                out.append(f"| {model} | ${total:.2f} | ${total / max(tasks, 1):.3f} | {sum(r['prompt_tokens'] for r in rows):,} | "
                           f"{sum(r['output_tokens'] for r in rows):,} |")
        out.append("")
    out += ["### Run health", "", "| Model | Scored | Errored (all) | Unresolved errors | Timeouts | Hit turn cap |", "|---|---|---|---|---|---|"]
    for model in sorted({r["model"] for r in all_rows}):
        rows = [r for r in all_rows if r["model"] == model]
        out.append(f"| {model} | {len(runs.get(model, []))} | {sum(r['errored'] for r in rows)} | "
                   f"{sum(r['model'] == model for r in unresolved)} | {sum(r['timeout'] for r in rows)} | "
                   f"{sum(r['truncated'] for r in rows)} |")
    if unresolved:
        out += ["", "Unresolved errors (re-run with `scripts/leaderboard.py rerun-errors`): " +
                ", ".join(f"{r['model']}:{r['task']} ({r['error']})" for r in unresolved[:20]) +
                (" ..." if len(unresolved) > 20 else "")]
    return "\n".join(out) + "\n"


def rerun_errors(a) -> None:
    """Re-run only the rollouts that errored, with the run's original settings, into <folder>/reruns_<n>/."""
    folder = pathlib.Path(a.folder)
    man = json.loads((folder / "manifest.json").read_text())
    _, unresolved = resolve(load_all(str(folder)), man.get("attempts"))
    if not unresolved:
        print("no unresolved errors")
        return
    n = len(list(folder.glob("reruns_*"))) + 1
    out = folder / f"reruns_{n}"
    out.mkdir()
    args = argparse.Namespace(attempts=None, split=man["split"], pressure=man.get("pressures"), files_tools=False,
                              base_url=a.base_url, api_key_var=a.api_key_var, push=False)
    if man["split"] == "hidden" and not os.environ.get("POTEMKIN_HIDDEN_SEED"):
        os.environ["POTEMKIN_HIDDEN_SEED"] = HIDDEN_SEED_FILE.read_text().strip()
    for model in sorted({r["model"] for r in unresolved}):
        for g in man["groups"]:
            ids = [r["task"] for r in unresolved if r["model"] == model and r["family"] in g["families"]]
            for k in sorted(set(ids.count(i) for i in ids)):  # tasks needing k more attempts
                batch = sorted({i for i in ids if ids.count(i) == k})
                args.attempts = k
                cmd = eval_command(model, args, out, g) + ["--env.taskset.task-ids", json.dumps(batch)]
                cmd[cmd.index("-n") + 1] = str(len(batch))
                print(f"$ [{g['group']}] re-running {len(batch)} task(s) x {k}:", shlex.join(cmd))
                if not a.dry_run:
                    subprocess.run(cmd, check=True)


# --- hidden-set commitment -------------------------------------------------------------------

def hidden_digest(difficulty: str, per_template: int, frontier_per_template: int | None, seed: str) -> tuple[str, list[str]]:
    """SHA-256 of the hidden tasks a leaderboard run with these settings scores (ids, prompts, data, scoring
    spec; same form as the frozen public-set fingerprints), and their ids. The seed is used only in-process."""
    import hashlib
    from potemkin_bench.taskset import HIDDEN_SEED_ENV, PotemkinBenchConfig, PotemkinBenchTaskConfig, PotemkinBenchTaskset
    old = os.environ.get(HIDDEN_SEED_ENV)
    os.environ[HIDDEN_SEED_ENV] = seed
    try:
        blob, ids = [], []
        for g in run_groups(difficulty, per_template, None, frontier_per_template):
            cfg = PotemkinBenchConfig(split="hidden", families=g["families"], num_tasks=g["num_tasks"],
                                      task=PotemkinBenchTaskConfig(files_tools=True, frontier_tools=g["group"] == "frontier"))
            for t in PotemkinBenchTaskset(cfg).load():
                blob.append((t.data.id, t.data.prompt, t.data.system_prompt, t.data.db, t.data.spec))
                ids.append(t.data.id)
    finally:
        if old is None:
            os.environ.pop(HIDDEN_SEED_ENV, None)
        else:
            os.environ[HIDDEN_SEED_ENV] = old
    return hashlib.sha256(json.dumps(blob, sort_keys=True, default=list).encode()).hexdigest(), ids


def commitment(salt: str, digest: str) -> str:
    """Published before scoring. The salt (kept private with the seed) stops anyone recovering the seed by
    trying seeds until the hash matches; publishing seed and salt when the set is retired lets anyone check."""
    import hashlib
    return hashlib.sha256(f"potemkin-hidden-v1:{salt}:{digest}".encode()).hexdigest()


def commit_hidden(a) -> None:
    seed_file = pathlib.Path(a.seed_file) if a.seed_file else HIDDEN_SEED_FILE
    salt_file = pathlib.Path(a.salt_file) if a.salt_file else HIDDEN_SEED_FILE.with_name(f"hidden_salt_{version()}")
    if not seed_file.exists():
        raise SystemExit(f"no seed file at {seed_file}")
    if not salt_file.exists():
        if a.salt_file:
            raise SystemExit(f"no salt file at {salt_file}")
        import secrets
        salt_file.write_text(secrets.token_hex(32) + "\n")
        salt_file.chmod(0o600)
        print(f"created a new salt at {salt_file} (private: back it up with the seed)")
    digest, ids = hidden_digest(a.difficulty, a.per_template, a.frontier_per_template, seed_file.read_text().strip())
    print(f"hidden@{version()} · {a.difficulty} · {a.per_template} per template · {a.frontier_per_template} per frontier "
          f"template · {len(ids)} tasks")
    print(f"commitment: {commitment(salt_file.read_text().strip(), digest)}")
    if a.check_runs:  # the committed set is the set the saved runs scored
        ran = {r["task"] for r in load_all(a.check_runs)}
        print(f"saved runs: {len(ran)} task ids; in the committed set: {len(ran & set(ids))}; "
              f"committed but not run: {len(set(ids) - ran)}")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("estimate", "run"):
        p = sub.add_parser(name)
        p.add_argument("-m", "--model", action="append", required=True)
        p.add_argument("--difficulty", default="leaderboard")
        p.add_argument("--families", help="comma-separated templates (overrides --difficulty), e.g. for targeted re-checks")
        p.add_argument("--per-template", type=int, default=3, help="tasks generated per template (3 x 34 core templates = 102)")
        p.add_argument("--frontier-per-template", type=int, default=6,
                       help="tasks per frontier-tier template (6 x 4 = 24; a bigger sample for the tier with the fewest templates)")
        p.add_argument("--pressure", action="append", help="prompt variants, e.g. neutral, pushback (default: neutral)")
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
    r = sub.add_parser("rerun-errors")
    r.add_argument("folder")
    r.add_argument("--base-url")
    r.add_argument("--api-key-var", default="PRIME_API_KEY")
    r.add_argument("--dry-run", action="store_true")
    c = sub.add_parser("commit-hidden", help="print the hidden set's commitment hash (never the seed or salt)")
    c.add_argument("--difficulty", default="leaderboard")
    c.add_argument("--per-template", type=int, default=3)
    c.add_argument("--frontier-per-template", type=int, default=6)
    c.add_argument("--seed-file", help=f"default {HIDDEN_SEED_FILE}; to verify a retired set, its published seed")
    c.add_argument("--salt-file", help="default: hidden_salt_<version> next to the seed (created if missing)")
    c.add_argument("--check-runs", help="folder of saved runs: confirm they scored exactly the committed tasks")
    a = ap.parse_args(argv)
    if a.cmd == "estimate":
        variants = len(a.pressure or ["neutral"])
        mix = {k: v * variants for k, v in level_mix(a.difficulty, a.per_template, a.families.split(",") if a.families else None,
                                                      a.frontier_per_template).items()}
        prices = json.loads(pathlib.Path(a.prices).read_text()) if a.prices else live_prices(a.model)
        print_estimate(estimate(a.model, prices, mix, a.attempts), mix, a.attempts)
    elif a.cmd == "run":
        run(a)
    elif a.cmd == "rerun-errors":
        rerun_errors(a)
    elif a.cmd == "commit-hidden":
        commit_hidden(a)
    else:
        print(summarize(a.folder))


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT / "environments" / "potemkin_bench"))
    main()
