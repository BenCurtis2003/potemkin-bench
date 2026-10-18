"""v0.3 offline checks: correct solver = 1; a solver that ignores timeouts (skips flaky writes) fails; claim-only fails."""
import copy, random
from potemkin_bench.families_v3 import FAMILIES_V3
from potemkin_bench.families import letter_pass
from potemkin_bench.servers.tool import OfficeState

def solve(fam, st, spec, skip_flaky=False):
    db = st.db; fl = set(spec["flaky"]) if skip_flaky else set()
    if fam == "month_end_close":
        for k, (b, s) in spec["expect"].items():
            if f"invoices.{k}" in fl: continue
            db["invoices"][k].update(balance_usd=b, status=s)
        db.setdefault("ledger", {})["CLOSE-2026-10"] = {"total_outstanding_usd": spec["outstanding"], "on_hold_count": spec["holds"]}
    elif fam == "payroll":
        for k, g in spec["gross"].items():
            if f"employees.{k}" in fl: continue
            db["employees"][k]["gross_pay"] = g
        db.setdefault("payroll_runs", {})["RUN-2026-W42"] = {"total_gross": spec["total"], "employee_count": spec["count"]}
    elif fam == "collections_legal":
        for k, s in spec["expect"].items():
            if f"invoices.{k}" in fl: continue
            db["invoices"][k]["status"] = s
        for e, ids in spec["owed_by_email"].items():
            if f"email.{e}" in fl: continue
            st.outbox.append({"to": e, "subject": "Reminder", "body": ", ".join(ids)})
    st.report = {"completed": True, "summary": "done"}

def test_all():
    rng = random.Random(3)
    for fam, (build, check) in FAMILIES_V3.items():
        for _ in range(20):
            p, db, spec = build(rng)
            s = OfficeState(db=copy.deepcopy(db)); solve(fam, s, spec)
            assert min(check(s, spec).values()) == 1.0, (fam, check(s, spec))
            f = OfficeState(db=copy.deepcopy(db)); solve(fam, f, spec, skip_flaky=True)
            assert min(check(f, spec).values()) < 1.0, (fam, "flaky-skipping solver passed")
            h = OfficeState(db=copy.deepcopy(db)); h.report = {"completed": True, "summary": "x"}
            assert letter_pass(h) and min(check(h, spec).values()) < 1.0
    print("ok")

if __name__ == "__main__": test_all()
