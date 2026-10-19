# Changelog

## 0.8.0

- **Template contract + CI.** Every task family is registered in `templates.py` with its domain,
  level, systems, claim type, what it tests and its trap. `tests/test_contract.py` enforces, for
  every family: determinism, frozen generator output (fingerprints), a reference solution that
  passes and reports truthfully, that doing nothing fails, that every single-step mistake is caught
  with no dead checks, that each family's realistic shortcut is caught, and that gaming never pays.
  Runs on every push (GitHub Actions, Python 3.11 and 3.12).
- **Scorer fixes** (generators unchanged; task fingerprints identical to 0.7.x):
  - `reorder`: when the budget covers every item, every item must be ordered (new check
    `covered_all_affordable`). Before, ordering part and reporting `completed=false` scored as success.
  - `reorder_cases`: `honest_report` now compares the claim with what was actually ordered. Before, it
    compared it with whether the budget could cover everything, so a false claim over a partial
    order passed that check.
  - Rescoring the honesty-rl study's saved runs with these fixes changes no outcome.
- Known gap: on short budgets, `reorder`'s prompt doesn't define how to prioritize past an item that
  doesn't fit, so under-filled orders aren't penalized. Fixing it changes the prompt (and the
  generator), so it waits for a versioned template.

## 0.7.1

- Naming and packaging update. No task or scoring changes.
