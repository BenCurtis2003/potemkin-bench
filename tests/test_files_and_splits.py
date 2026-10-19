"""File tools and taskset wiring for file-based templates."""
import asyncio
import json
from types import SimpleNamespace

import pytest
import verifiers.v1 as vf
from verifiers.v1.mcp.server import _call_state
from verifiers.v1.utils.decorators import discover_decorated

from potemkin_bench.servers.files_tool import PotemkinBenchFilesToolset
from potemkin_bench.servers.tool import FILE_PAGE_LINES, FILES_KEY, OfficeState, PotemkinBenchToolset
from potemkin_bench.taskset import (PotemkinBenchConfig, PotemkinBenchTask, PotemkinBenchTaskConfig,
                                    PotemkinBenchTaskset)


def call(toolset, state, fn, **kw):
    token = _call_state.set(state)
    try:
        return getattr(toolset, fn)(**kw)
    finally:
        _call_state.reset(token)


def test_file_tools_page_and_log():
    ts = PotemkinBenchFilesToolset(vf.ToolsetConfig())
    text = "\n".join(f"row {i}" for i in range(1, 121))
    st = OfficeState(files={"a/b.csv": text})
    assert json.loads(call(ts, st, "list_files")) == {"a/b.csv": 120}
    p1 = json.loads(call(ts, st, "read_file", path="a/b.csv"))
    p3 = json.loads(call(ts, st, "read_file", path="a/b.csv", page=3))
    assert p1["lines"][0] == "row 1" and len(p1["lines"]) == FILE_PAGE_LINES and p1["has_more"]
    assert p3["first_line_number"] == 101 and p3["lines"][-1] == "row 120" and not p3["has_more"]
    assert call(ts, st, "read_file", path="nope").startswith("error")
    assert st.file_reads == ["a/b.csv#1", "a/b.csv#3"]


def test_write_file_creates_and_overwrites():
    ts = PotemkinBenchFilesToolset(vf.ToolsetConfig())
    st = OfficeState(files={"in.csv": "a"})
    assert call(ts, st, "write_file", path="out/report.csv", content="x,y\n1,2\n") == "ok"
    call(ts, st, "write_file", path="out/report.csv", content="x,y\n3,4\n")
    assert st.files == {"in.csv": "a", "out/report.csv": "x,y\n3,4\n"}
    assert st.actions == ["write out/report.csv", "write out/report.csv"]
    assert json.loads(call(ts, st, "read_file", path="out/report.csv"))["lines"] == ["x,y", "3,4"]


def test_study_tool_list_unchanged():
    """Without files_tools, tasks get exactly the original tool server (no file tools)."""
    assert [type(t) for t in PotemkinBenchTask.toolsets(PotemkinBenchTaskConfig())] == [PotemkinBenchToolset]
    assert [type(t) for t in PotemkinBenchTask.toolsets(PotemkinBenchTaskConfig(files_tools=True))] == [PotemkinBenchFilesToolset]
    tools = lambda cls: {fn.__name__ for fn in discover_decorated(cls(vf.ToolsetConfig()), "tool")}  # noqa: E731
    base = tools(PotemkinBenchToolset)
    assert base == {"list_tables", "list_records", "get_record", "update_record", "delete_record",
                    "create_record", "send_email", "aggregate", "submit_report"}
    assert tools(PotemkinBenchFilesToolset) == base | {"list_files", "read_file", "write_file"}


def test_file_templates_need_files_tools():
    with pytest.raises(ValueError, match="files_tools"):
        PotemkinBenchTaskset(PotemkinBenchConfig(difficulty="v1", num_tasks=5)).load()
    cfg = PotemkinBenchConfig(difficulty="v1", num_tasks=5, split="test", task=PotemkinBenchTaskConfig(files_tools=True, scoring="1.0"))
    tasks = PotemkinBenchTaskset(cfg).load()
    assert {t.data.family for t in tasks} == {"reorder@2", "bank_reconciliation", "expense_audit",
                                              "vendor_payment_run", "tax_rate_change"}


def test_setup_moves_files_out_of_the_database():
    cfg = PotemkinBenchConfig(families=["bank_reconciliation"], num_tasks=1, task=PotemkinBenchTaskConfig(files_tools=True))
    task = PotemkinBenchTaskset(cfg).load()[0]
    trace = SimpleNamespace(state=OfficeState())
    asyncio.run(task.setup(trace, None))
    assert FILES_KEY not in trace.state.db and "payments" in trace.state.db
    assert list(trace.state.files) == ["bank/statement_2026-10.csv"]
    assert FILES_KEY in task.data.db  # the task data itself is untouched


# --- splits ----------------------------------------------------------------------------------

def _load(split, **kw):
    cfg = PotemkinBenchConfig(split=split, difficulty="mixed", scale="small", num_tasks=28,
                              task=PotemkinBenchTaskConfig(files_tools=True), **kw)
    return PotemkinBenchTaskset(cfg).load()


def _fp(task):
    return json.dumps([task.data.prompt, task.data.db], sort_keys=True, default=list)


def test_splits_are_disjoint(monkeypatch):
    monkeypatch.setenv("POTEMKIN_HIDDEN_SEED", "424242")
    sets = {s: {_fp(t) for t in _load(s)} for s in ("train", "dev", "test", "hidden")}
    for a in sets:
        for b in sets:
            if a < b:
                assert not sets[a] & sets[b], (a, b)
    assert all(t.data.id.startswith("hidden-") for t in _load("hidden"))


def test_hidden_split_needs_the_secret(monkeypatch):
    monkeypatch.delenv("POTEMKIN_HIDDEN_SEED", raising=False)
    with pytest.raises(ValueError, match="POTEMKIN_HIDDEN_SEED"):
        _load("hidden")
    monkeypatch.setenv("POTEMKIN_HIDDEN_SEED", "1")
    a = {_fp(t) for t in _load("hidden")}
    monkeypatch.setenv("POTEMKIN_HIDDEN_SEED", "2")
    assert a != {_fp(t) for t in _load("hidden")}  # rotating the secret gives a new hidden set


def test_heldout_templates_never_reach_train_or_dev(monkeypatch):
    import dataclasses

    import potemkin_bench.templates as T
    monkeypatch.setitem(T.TEMPLATES, "payroll", dataclasses.replace(T.TEMPLATES["payroll"], heldout=True))
    for split in ("train", "dev"):
        assert "payroll" not in {t.data.family for t in _load(split)}
    assert "payroll" in {t.data.family for t in _load("test")}
    with pytest.raises(ValueError, match="held out"):
        PotemkinBenchTaskset(PotemkinBenchConfig(split="train", families=["payroll"], num_tasks=2)).load()


def test_unknown_split_rejected():
    with pytest.raises(ValueError, match="unknown split"):
        _load("validation")


def test_each_toolset_module_launches_its_own_class():
    """verifiers starts tool servers with `python -m <module>`, so each toolset class's module must run
    that exact class in its __main__ block (a shared module once served the wrong tool list)."""
    import importlib
    import inspect as _inspect
    for cfg in (PotemkinBenchTaskConfig(), PotemkinBenchTaskConfig(files_tools=True)):
        for ts in PotemkinBenchTask.toolsets(cfg):
            src = _inspect.getsource(importlib.import_module(type(ts).__module__))
            main = src.split('if __name__ == "__main__":', 1)[1]
            assert f"{type(ts).__name__}.run()" in main, type(ts).__name__


def test_task_ids_filter_regenerates_identical_tasks():
    full = PotemkinBenchTaskset(PotemkinBenchConfig(difficulty="hr", num_tasks=16, split="test")).load()
    pick = [full[3].data.id, full[11].data.id]
    sub = PotemkinBenchTaskset(PotemkinBenchConfig(difficulty="hr", num_tasks=16, split="test", task_ids=pick)).load()
    assert [t.data.id for t in sub] == pick
    by_id = {t.data.id: t for t in full}
    assert all(_fp(t) == _fp(by_id[t.data.id]) for t in sub)  # same content as in the full run
