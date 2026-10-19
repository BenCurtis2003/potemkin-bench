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
    tok = {"prompt": 1_000_000, "new_input": 200_000, "output": 500_000}
    assert lb.rollout_cost(tok, PRICES["m-cheap"], cache=False) == pytest.approx(1.0 + 1.0)
    assert lb.rollout_cost(tok, PRICES["m-cheap"], cache=True) == pytest.approx(0.2 + 0.08 + 1.0)
    assert lb.rollout_cost(tok, PRICES["m-nocache"], cache=True) == pytest.approx(2.0)  # no cache price: full input


def test_level_mix_and_estimate_scale_with_tasks_and_attempts():
    mix = lb.level_mix("v1", 78)
    assert sum(mix.values()) == 78 and set(mix) <= {"easy", "hard", "expert", "long"}
    one = lb.estimate(["m-cheap"], PRICES, mix, attempts=1)
    two = lb.estimate(["m-cheap"], PRICES, mix, attempts=2)
    assert two["high_usd"] == pytest.approx(2 * one["high_usd"], rel=0.01)
    assert one["typical_usd"] < one["high_usd"] and one["rollouts"] == 78


def _args(**kw):
    base = dict(model=["m-cheap"], difficulty="v1", num_tasks=10, attempts=1, split="test", budget_usd=0.0,
                out="/tmp/unused", base_url=None, api_key_var="PRIME_API_KEY", files_tools=False, push=False,
                dry_run=True, prices=None, pressure=None)
    return SimpleNamespace(**{**base, **kw})


def test_run_refuses_over_budget(tmp_path):
    prices = tmp_path / "p.json"
    prices.write_text(json.dumps(PRICES))
    with pytest.raises(SystemExit, match="REFUSING"):
        lb.run(_args(prices=str(prices), budget_usd=0.0001, out=str(tmp_path / "o")))


def test_eval_command_flags(tmp_path):
    cmd = lb.eval_command("m-cheap", _args(base_url="http://x/v1", api_key_var="K"), tmp_path)
    s = " ".join(cmd)
    for flag in ("--env.taskset.task.scoring 1.0", "--env.taskset.task.files-tools true", "--env.taskset.split test",
                 "--env.taskset.difficulty v1", "--client.base-url http://x/v1", "--client.api-key-var K", "-n 10", "-r 1"):
        assert flag in s, flag
    assert "--env.taskset.task.files-tools false" in " ".join(lb.eval_command("m", _args(difficulty="hr"), tmp_path))
    for lvl in ("long", "it", "procurement", "crm", "finance_v1", "v1"):  # every level containing a file task
        assert "--env.taskset.task.files-tools true" in " ".join(lb.eval_command("m", _args(difficulty=lvl), tmp_path)), lvl


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


def test_hidden_seed_never_printed_or_saved(tmp_path, monkeypatch, capsys):
    secret = "8675309421"
    monkeypatch.setenv("POTEMKIN_HIDDEN_SEED", secret)
    prices = tmp_path / "p.json"
    prices.write_text(json.dumps(PRICES))
    lb.run(_args(prices=str(prices), budget_usd=1e9, split="hidden", out=str(tmp_path / "o")))
    out = capsys.readouterr()
    assert secret not in out.out + out.err
    assert secret not in (tmp_path / "o" / "manifest.json").read_text()
