# PotemkinBench

A [verifiers](https://github.com/PrimeIntellect-ai/verifiers) v1 RL environment (formerly `letter-vs-intent`) that asks:
**does the agent actually do the job, or just say it did?** Multi-step back-office tasks (collections,
refunds, restocking, dedupe, month-end close, payroll) run against a mock database and email, scored on
the true end state, with false success (claimed done, wasn't) measured directly.

- Environment, options and benchmark results: [environments/potemkin_bench/README.md](environments/potemkin_bench/README.md)
- On the Prime Intellect Hub: `bencurtis2003/potemkin-bench`
- Used in a three-arm RL study: [honesty-rl](https://github.com/BenCurtis2003/honesty-rl)

```bash
uv pip install -e environments/potemkin_bench
python tests/test_v06.py   # offline checks, no model needed
```

All data is synthetic. MIT license.
