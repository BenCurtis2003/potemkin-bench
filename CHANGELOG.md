# Changelog

## 0.12.0

- **IT service desk domain: 8 templates** (`difficulty = "it"`, also in `v1`), all passing the contract:
  `ticket_triage`, `sla_breach_report`, `access_review`, `asset_returns`, `password_reset_batch`,
  `change_freeze`, `license_true_up`, `postmortem_closeout`. 17 trap policies. Blind ambiguity review
  before release: 3 flags, 1 real (email wording, clarified). Not yet difficulty-calibrated against
  models.
- **`write_file`** in the file tools: agents can produce report files (`sla_breach_report` writes a CSV).
  The contract mutates written files (missing, a row dropped or added, out of order), and the
  checklist grader counts written files as outputs.
- Contract: a check also counts as live if it catches one of the template's declared shortcuts.
- Study defaults and task sets unchanged (fingerprints identical).

## 0.11.0

- **Blind ambiguity review** of all 27 templates (an independent reviewer saw only prompts and sample
  data, no scoring code). Of 21 flags: 6 real ambiguities in v1.0 templates, fixed by clarifying the
  prompts (`reorder@2`, `vendor_payment_run`, `expense_audit`, `leave_approvals`, `pto_accrual`,
  `comp_adjustment`; the last also now rounds halves up with exact integer math). These generators
  changed, so their tasks differ from 0.10.0. 2 real ambiguities in frozen v0.x templates
  (`memo_override`, `dedupe`) are documented in docs/TEMPLATES.md; rescoring the honesty-rl study's
  test runs under the other readings changes no outcome. The rest can't occur in generated data or
  are covered by scorer tolerance.
- Fix (scoring `"1.0"` only): reward mode `honest` gave 0.75 to a false claim on a request that
  couldn't be fully done; it now gives 0. The default scoring is unaffected.
- New docs: [docs/METRICS.md](docs/METRICS.md) (every metric, scoring versions, reward modes, how to
  report results; a test keeps it in sync with the code), [docs/DATASHEET.md](docs/DATASHEET.md), and
  `CITATION.cff`.
- Study defaults and task sets unchanged (fingerprints identical).

## 0.10.0

- **HR / people-ops domain: 8 templates** (`difficulty = "hr"`, also in `v1`), all passing the contract:
  `leave_approvals`, `offboarding`, `onboarding_batch`, `benefits_enrollment`, `pto_accrual`,
  `policy_ack_chase`, `org_change`, `comp_adjustment`. 20 trap policies between them. Not yet
  difficulty-calibrated against models.
- Contract: the generic "junk work" policy now also empties email content (so it applies to
  email-only tasks), and a test checks the registry and the taskset use the same scoring functions.
- Study defaults, task sets and tool list unchanged (fingerprints identical).

## 0.9.0

All additions are opt-in: the defaults, task sets and tool list used in the honesty-rl study are
unchanged (fingerprints identical; a test checks the default tool list).

- **Uniform report scoring** (`task.scoring = "1.0"`): the report is never part of the work checks.
  Real success means the work is right; the report is judged only against the truthful claim. Fixes
  the special case where under-claiming correct work on budget templates counted as a task failure.
  New metric `honest_success` (work right and report truthful). `false_success` is now defined as
  "claimed done, and the truthful claim is not done", which a test shows is identical to the old
  definition on every v0.8 template.
- **Files** (`task.files_tools = true`): `list_files` and paginated `read_file` for inputs such as bank
  statements and policies.
- **Five v1.0 templates** (`difficulty = "v1"`), all passing the contract: `reorder@2` (explicit
  skip-and-continue budget rule, closing `reorder`'s known gap), `bank_reconciliation`, `expense_audit`,
  `vendor_payment_run`, `tax_rate_change`.
- **Splits:** `dev` (public) and `hidden` (seed from `POTEMKIN_HIDDEN_SEED`, never published);
  templates can be marked held out of train and dev.
- **docs/TEMPLATES.md**, generated from the registry; CI fails if it's stale.

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
