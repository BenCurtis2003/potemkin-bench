"""v0.5 offline checks: each common mistake is classified as itself; correct runs show no error types."""
import copy, random
from potemkin_bench.families_v3 import build_close, build_payroll, error_types
from potemkin_bench.taskset import HONEST


def _filled(db, spec, fam):
    db = copy.deepcopy(db)
    tbl, f = ("invoices", "balance_usd") if fam == "month_end_close" else ("employees", "gross_pay")
    truth = spec["expect"] if fam == "month_end_close" else spec["gross"]
    for k, v in truth.items():
        db[tbl][k][f] = v[0] if isinstance(v, tuple) else v
    return db, tbl, f


def test_error_types():
    for seed in range(5):
        for fam, build in [("month_end_close", build_close), ("payroll", build_payroll)]:
            _, db, spec = build(random.Random(seed))
            ok, tbl, f = _filled(db, spec, fam)
            assert not any(error_types(ok[tbl], f, spec, fam).values()), (fam, seed)
            for e, m in spec["alts"].items():
                bad, _, _ = _filled(db, spec, fam)
                k = sorted(m)[0]
                if not m[k]: continue
                bad[tbl][k][f] = m[k][0] if isinstance(m[k], list) else m[k]
                got = error_types(bad[tbl], f, spec, fam)
                assert got[f"err_{e}"] == 1.0, (fam, seed, e)


def test_honest_scale():
    assert HONEST[(True, True)] > HONEST[(True, False)] > HONEST[(False, False)] > HONEST[(False, True)] == 0.0


if __name__ == "__main__":
    test_error_types(); test_honest_scale(); print("ok")
