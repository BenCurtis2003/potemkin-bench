# PotemkinBench

A [verifiers](https://github.com/PrimeIntellect-ai/verifiers) v1 RL environment that asks:
**does the agent actually do the job, or just say it did?** Multi-step back-office tasks (finance: collections,
refunds, restocking, month-end close, payroll; HR: leave, offboarding, benefits, PTO, comp; IT: triage, SLA reports, access reviews, licenses) run against a mock database, email and files, scored on
the true end state, with false success (claimed done, wasn't) measured directly.

- Environment, options and benchmark results: [environments/potemkin_bench/README.md](environments/potemkin_bench/README.md)
- Every task template, its trap, and what its scorer must catch: [docs/TEMPLATES.md](docs/TEMPLATES.md)
- Metric definitions and how to report results: [docs/METRICS.md](docs/METRICS.md) · datasheet: [docs/DATASHEET.md](docs/DATASHEET.md) · cite: [CITATION.cff](CITATION.cff)
- Changes by version: [CHANGELOG.md](CHANGELOG.md)
- On the Prime Intellect Hub: `bencurtis2003/potemkin-bench`
- Used in a three-arm RL study: [honesty-rl](https://github.com/BenCurtis2003/honesty-rl)

```bash
uv pip install -e environments/potemkin_bench pytest
pytest -q tests   # template contract + offline checks, no model needed
```

All data is synthetic. MIT license.
