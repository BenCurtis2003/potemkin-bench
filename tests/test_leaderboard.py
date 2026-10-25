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


def test_summarize_a_folder_of_per_model_runs_uses_their_manifests(tmp_path):
    """Combined summary over runs/<version>/<model>/: an error that a re-run fixed is not reported as unresolved."""
    def trace(model, task, met=None, err=None):
        tr = {"task": {"data": {"id": task}}, "agent": {"config": {"model": model}}, "metrics": met or {}}
        if err:
            tr["errors"] = [{"type": err}]
        return {"traces": [tr]}
    met = {"task_success": 1.0, "false_success": 0.0, "calib_honest": 1.0, "calib_should_claim": 1.0,
           "calib_under_claim": 0.0, "honest_success": 1.0}
    for model in ("m-a", "m-b"):
        d = tmp_path / model
        (d / "orig").mkdir(parents=True)
        (d / "manifest.json").write_text(json.dumps({
            "benchmark_version": "9.9", "split": "hidden", "difficulty": "leaderboard", "num_tasks": 2, "attempts": 1,
            "settings": {"scoring": "1.0"}, "git_sha": "abcdef0",
            "prices": {model: {"input_usd_per_mtok": 1.0, "output_usd_per_mtok": 1.0}}}))
        (d / "orig" / "traces.jsonl").write_text(json.dumps(trace(model, "t1", err="ProviderError")) + "\n"
                                                 + json.dumps(trace(model, "t2", met)) + "\n")
        (d / "reruns_1" / "x").mkdir(parents=True)
        (d / "reruns_1" / "x" / "traces.jsonl").write_text(json.dumps(trace(model, "t1", met)) + "\n")
    out = lb.summarize(str(tmp_path))
    assert out.startswith("PotemkinBench ")
    assert "| m-a | 100% [100–100] |" in out and "| m-b | 100% [100–100] |" in out
    cost = out.split("### Cost")[1].split("### Run health")[0]
    assert "| m-a | $" in cost and "| m-b | $" in cost   # prices from every model's manifest
    assert "| m-a | 2 | 1 | 0 | 0 | 0 |" in out and "Unresolved errors (re-run" not in out


def test_shared_false_successes():
    """Overlap and correlation of per-task false success across models (correlated risk)."""
    def rows(fs):
        return [{"task": f"t{i}", "false_success": float(v)} for i, v in enumerate(fs)]
    runs = {"a": rows([1, 1, 0, 0]), "b": rows([1, 0, 0, 0]), "c": rows([0, 0, 0, 0])}
    out = "\n".join(lb.shared_failures(runs))
    assert "Over the 4 tasks every model ran" in out
    assert "| a | n=2 | 50% (r=0.58) | 0% (r=n/a) |" in out    # half of a's false claims are b's too; c never varies
    assert "| b | 100% (r=0.58) | n=1 | 0% (r=n/a) |" in out
    assert "| Tasks | 2 | 1 | 1 | 0 |" in out                     # t2,t3: none; t1: a only; t0: a and b
    assert lb.shared_failures({"a": runs["a"]}) == []


def test_rollout_carries_the_templates_exposure_class():
    r = lb._rollout({"task": {"data": {"id": "x", "family": "payment_release"}}, "metrics": {}}, "m")
    assert r["exposure"] == "money"


def test_commit_hidden_prints_neither_seed_nor_salt(tmp_path, capsys):
    seed, salt = tmp_path / "seed", tmp_path / "salt"
    seed.write_text("918273645\n")
    salt.write_text("c0ffee" * 10 + "\n")
    lb.main(["commit-hidden", "--seed-file", str(seed), "--salt-file", str(salt), "--per-template", "1",
             "--frontier-per-template", "1"])
    out = capsys.readouterr().out
    assert "918273645" not in out and "c0ffee" not in out
    digest, ids = lb.hidden_digest("leaderboard", 1, 1, "918273645")
    assert f"commitment: {lb.commitment('c0ffee' * 10, digest)}" in out and f"· {len(ids)} tasks" in out
    assert lb.hidden_digest("leaderboard", 1, 1, "918273646")[0] != digest   # a different seed, a different set
    assert lb.commitment("other", digest) != lb.commitment("c0ffee" * 10, digest)
