"""Leaderboard tooling: cost estimate math, the budget guard, eval command flags, and the summary table."""
import importlib.util
import json
import pathlib
from types import SimpleNamespace

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("leaderboard", ROOT / "scripts" / "leaderboard.py")
lb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lb)

PRICES = {"m-cheap": {"input_usd_per_mtok": 1.0, "output_usd_per_mtok": 2.0, "cache_read_usd_per_mtok": 0.1},
          "m-nocache": {"input_usd_per_mtok": 1.0, "output_usd_per_mtok": 2.0, "cache_read_usd_per_mtok": None}}


def test_rollout_cost_math():
    tok = {"prompt": 1_000_000, "cached": 2_000_000, "output": 500_000}
    assert lb.rollout_cost(tok, PRICES["m-cheap"], cache=True) == pytest.approx(1.0 + 0.2 + 1.0)
    assert lb.rollout_cost(tok, PRICES["m-cheap"], cache=False) == pytest.approx(1.0 + 2.0 + 1.0)   # worst case
    assert lb.rollout_cost(tok, PRICES["m-nocache"], cache=True) == pytest.approx(1.0 + 2.0 + 1.0)  # no cache price


def test_cost_formula_matches_real_billing():
    """Calibration 2026-10-19: Prime billed these exact amounts for these token totals."""
    qwen = {"input_usd_per_mtok": 0.18, "output_usd_per_mtok": 0.54, "cache_read_usd_per_mtok": 0.018}
    ds = {"input_usd_per_mtok": 0.30, "output_usd_per_mtok": 1.20, "cache_read_usd_per_mtok": 0.03}
    assert lb.rollout_cost({"prompt": 2_204_310, "cached": 37_126_848, "output": 2_782_233}, qwen, True) == pytest.approx(2.57, abs=0.01)
    assert lb.rollout_cost({"prompt": 1_714_831, "cached": 10_332_928, "output": 1_047_183}, ds, True) == pytest.approx(2.08, abs=0.01)


def test_level_mix_and_estimate_scale_with_tasks_and_attempts():
    mix = lb.level_mix("v1", 2)
    from potemkin_bench.taskset import LEVELS
    assert sum(mix.values()) == 2 * len(LEVELS["v1"]) and set(mix) <= {"easy", "hard", "expert", "long"}
    one = lb.estimate(["m-cheap"], PRICES, mix, attempts=1)
    two = lb.estimate(["m-cheap"], PRICES, mix, attempts=2)
    assert two["high_usd"] == pytest.approx(2 * one["high_usd"], rel=0.01)
    assert one["typical_usd"] < one["high_usd"] and one["rollouts"] == sum(mix.values())


def _args(**kw):
    base = dict(model=["m-cheap"], difficulty="v1", per_template=1, attempts=1, split="test", budget_usd=0.0,
                out="/tmp/unused", base_url=None, api_key_var="PRIME_API_KEY", files_tools=False, push=False,
                dry_run=True, prices=None, pressure=None, families=None, frontier_per_template=None)
    return SimpleNamespace(**{**base, **kw})


def test_leaderboard_level_runs_frontier_as_its_own_group_with_a_bigger_sample():
    groups = {g["group"]: g for g in lb.run_groups("leaderboard", 3, frontier_per_template=6)}
    assert set(groups) == {"standard", "long", "frontier"}
    assert groups["frontier"]["num_tasks"] == 24 and groups["frontier"]["max_turns"] == 150
    assert groups["standard"]["num_tasks"] + groups["long"]["num_tasks"] == 102
    assert lb.level_mix("leaderboard", 3, frontier_per_template=6)["frontier"] == 24
    a = _args()
    cmd = lb.eval_command("m", a, pathlib.Path("/tmp/x"), groups["frontier"])
    assert cmd[cmd.index("--env.taskset.task.frontier-tools") + 1] == "true"


def test_run_refuses_over_budget(tmp_path):
    prices = tmp_path / "p.json"
    prices.write_text(json.dumps(PRICES))
    with pytest.raises(SystemExit, match="REFUSING"):
        lb.run(_args(prices=str(prices), budget_usd=0.0001, out=str(tmp_path / "o")))


def test_eval_command_flags(tmp_path):
    a = _args(base_url="http://x/v1", api_key_var="K")
    groups = lb.run_groups("v1", 1)
    assert [g["group"] for g in groups] == ["standard", "long"]
    std, long_ = groups
    s = " ".join(lb.eval_command("m-cheap", a, tmp_path, std))
    for flag in ("--env.taskset.task.scoring 1.0", "--env.taskset.split test", "--env.agent.max-turns 50",
                 "--sampling.max-tokens 16384", "--client.base-url http://x/v1", "--client.api-key-var K",
                 f"-n {std['num_tasks']}", "-r 1"):
        assert flag in s, flag
    assert "--env.agent.max-turns 150" in " ".join(lb.eval_command("m", a, tmp_path, long_))
    assert "--sampling.temperature" not in s and "--sampling.reasoning-effort" not in s  # provider defaults
    # file tools follow the tasks in each group
    assert std["files"] and long_["files"]
    assert not lb.run_groups("hr", 1)[0]["files"] and lb.run_groups("long", 1)[0]["files"]
    # prompt variants multiply the examples
    assert f"-n {2 * std['num_tasks']}" in " ".join(lb.eval_command("m", _args(pressure=["neutral", "pushback"]), tmp_path, std))


def test_dry_run_writes_manifest(tmp_path):
    prices = tmp_path / "p.json"
    prices.write_text(json.dumps(PRICES))
    lb.run(_args(prices=str(prices), budget_usd=1e9, out=str(tmp_path / "o")))
    m = json.loads((tmp_path / "o" / "manifest.json").read_text())
    assert m["benchmark_version"] == lb.version() and m["settings"]["scoring"] == "1.0" and m["split"] == "test"


def test_summarize_table(tmp_path):
    d = tmp_path / "run" / "potemkin-bench--m--x"
    d.mkdir(parents=True)
    rows = []
    for t in range(6):
        for ok, claimed in ((1.0, True), (0.0, True)):
            met = {"task_success": ok, "false_success": float(claimed and not ok), "calib_honest": float(claimed == bool(ok)),
                   "calib_should_claim": ok, "calib_under_claim": 0.0, "honest_success": float(ok)}
            rows.append({"traces": [{"task": {"data": {"id": f"t{t}"}}, "agent": {"config": {"model": "m-x"}}, "metrics": met}]})
    (d / "traces.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    out = lb.summarize(str(tmp_path / "run"))
    assert "| m-x | 50% [50–50] | 50% [50–50] | 50% [50–50] | 50% [50–50] | 100% | 12 |" in out
    assert "### Run health" in out and "### By template" in out


def test_resolve_prefers_scored_and_fills_errors():
    ok = lambda t, src: {"model": "m", "task": t, "scored": True, "errored": False, "source": src}  # noqa: E731
    bad = lambda t, src: {"model": "m", "task": t, "scored": False, "errored": True, "error": "ProviderError", "source": src}  # noqa: E731
    rows = [ok("a", 1), bad("a", 1), ok("b", 1), ok("b", 1), ok("a", 2), ok("b", 2)]  # last two are re-runs
    runs, unresolved = lb.resolve(rows, attempts=2)
    assert len([r for r in runs["m"] if r["task"] == "a"]) == 2   # the error was filled by the re-run
    assert len([r for r in runs["m"] if r["task"] == "b"]) == 2   # never more than `attempts`
    assert unresolved == []
    runs, unresolved = lb.resolve([ok("a", 1), bad("a", 1)], attempts=2)
    assert len(unresolved) == 1 and unresolved[0]["error"] == "ProviderError"


def test_hidden_seed_never_printed_or_saved(tmp_path, monkeypatch, capsys):
    secret = "8675309421"
    monkeypatch.setenv("POTEMKIN_HIDDEN_SEED", secret)
    prices = tmp_path / "p.json"
    prices.write_text(json.dumps(PRICES))
    lb.run(_args(prices=str(prices), budget_usd=1e9, split="hidden", out=str(tmp_path / "o")))
    out = capsys.readouterr()
    assert secret not in out.out + out.err
    assert secret not in (tmp_path / "o" / "manifest.json").read_text()
