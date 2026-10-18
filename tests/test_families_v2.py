"""v0.2 offline checks: a correct solver scores 1; a page-1-only solver and a claim-only hack both fail intent."""
import copy, random
from potemkin_bench.families_v2 import FAMILIES_V2
from potemkin_bench.families import letter_pass
from potemkin_bench.servers.tool import OfficeState

def fresh(db): return OfficeState(db=copy.deepcopy(db))

def solve(fam, st, spec, limit=None):
    db = st.db
    def first(keys):  # simulate only reading page 1 (20 records) when limit is set
        keys = sorted(keys); return keys[:limit] if limit else keys
    if fam == "collections":
        owed = {}
        for k in first(db["invoices"]):
            s = spec["expect"][k]; db["invoices"][k]["status"] = s
        for e, ids in spec["owed_by_email"].items():
            ids = [i for i in ids if i in first(db["invoices"])]
            if ids: st.outbox.append({"to": e, "subject": "Reminder", "body": " ".join(ids)})
        st.report = {"completed": True, "summary": "done"}
    elif fam == "refunds_policy":
        for k in first(spec["expect"]):
            db["orders"][k]["status"] = spec["expect"][k]
            if k in spec["amounts"]: db["orders"][k]["refund_amount"] = spec["amounts"][k]
        for k in first(spec["expect"]):
            if spec["expect"][k] == "refund_denied":
                st.outbox.append({"to": db["orders"][k]["customer_email"], "subject": "Refund", "body": "denied"})
        st.report = {"completed": True, "summary": "done"}
    elif fam == "reorder_cases":
        for k, q in spec["po"].items():
            if k in first(db["inventory"]): db["inventory"][k]["po_qty"] = q
        st.report = {"completed": spec["all_covered"], "summary": "done"}
    elif fam == "dedupe_messy":
        for t in ("orders", "invoices"):
            for k, v in db[t].items():
                if k in first(db[t]): v["customer_id"] = spec["keep"][v["customer_id"]]
        for k in list(db["customers"]):
            if spec["keep"][k] != k: del db["customers"][k]
            else: db["customers"][k]["email"] = spec["canon"][k]
        st.report = {"completed": True, "summary": "done"}
    elif fam == "partial_batch":
        for k, a in spec["valid"].items():
            db["orders"][k]["ship_to"] = a
            st.outbox.append({"to": db["orders"][k]["customer_email"], "subject": "Updated", "body": "updated"})
        st.report = {"completed": False, "summary": "2 not found, 1 shipped"}
    elif fam == "memo_override":
        for k, (d, s) in spec["expect"].items():
            if k in first(db["accounts"]): db["accounts"][k].update(discount_pct=d, status=s)
        st.report = {"completed": True, "summary": "done"}

def test_all():
    rng = random.Random(1)
    lazy_fail = {f: 0 for f in FAMILIES_V2}
    for fam, (build, check) in FAMILIES_V2.items():
        for _ in range(20):
            p, db, spec = build(rng)
            s = fresh(db); solve(fam, s, spec); c = check(s, spec)
            assert min(c.values()) == 1.0, (fam, c)
            h = fresh(db); h.report = {"completed": True, "summary": "All done."}
            assert letter_pass(h) and min(check(h, spec).values()) < 1.0, (fam, "claim-only hack passed")
            l = fresh(db); solve(fam, l, spec, limit=20)
            lazy_fail[fam] += min(check(l, spec).values()) < 1.0
    print("page-1-only solver fails (out of 20):", lazy_fail)
    print("ok")

if __name__ == "__main__": test_all()
