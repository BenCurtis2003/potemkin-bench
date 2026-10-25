# Changelog

## Unreleased

- `leaderboard.py run` and `rerun-errors` now pass `--no-push` unless `--push` is given. vf-eval uploads every
  run to the Prime Evaluations tab by default, so earlier leaderboard runs were uploaded there (private to the
  maintainer's account) despite `--push` being off. The 27 hidden-split uploads (hidden@1.0.1 leaderboard runs
  and the 10/21 rehearsal) were never public and were deleted on 2026-10-25; the hidden set stays in use.
- **Workflows** ([docs/WORKFLOWS.md](docs/WORKFLOWS.md)): describe a process in YAML (synthetic data, request,
  end-state rules, emails, traps) and score agents on it like a template, with `--env.taskset.workflow`.
  A generic scorer and reference solution are built from the file, and `python -m potemkin_bench.workflow
  check` runs a workflow contract (deterministic, solvable, not trivial, strict, traps bite, both reports
  occur). Worked example: `examples/workflows/ap_payment_run.yaml`. Built-in templates and frozen sets are
  unchanged; `pyyaml` is now a declared dependency.
- **Leaderboard results** for hidden@1.0.1, 5 models: [docs/LEADERBOARD.md](docs/LEADERBOARD.md). No task changes.
- `leaderboard.py summarize` on a folder of per-model runs (`runs/<version>/<model>/`) now reads the per-model
  manifests: re-runs fill in errored rollouts (they were listed as unresolved) and every model's prices are used.
- **Exposure class** per template (`money`, `access`, `external`, `records`): the main harm a false success
  causes. Shown in TEMPLATES.md and as a `summarize` breakdown. Metadata only; no task or score changes.
- **Shared false successes** in `summarize`: per model pair, overlap and correlation of false successes,
  and how many tasks several models falsely claimed (correlated risk).
- **Hidden-set commitment:** `leaderboard.py commit-hidden` prints a salted hash of the hidden set (never the
  seed or salt) and checks saved runs against it; seed and salt are published when a set is retired
  ([SPLITS.md](docs/SPLITS.md)). hidden@1.0.1's commitment is in the leaderboard.

## 1.0.1

- **Blind fairness review** of the frontier tier (a reviewer saw only what the agent sees, not the scorers):
  `ledger_migration` and `benefits_cutover` fair as written; two wording fixes. `payment_release` no longer
  says "this week's" (approved due dates span two weeks, which conflicted with "every approved payment"), and
  `renewal_notices` now says resending an undelivered message is fine (the old "one message" read as
  forbidding it) and that mail_log is written as soon as the relay processes a message. Both generators
  changed (fingerprints updated); no other task changed.
- **Leaderboard:** `--frontier-per-template` (default 6), so the hidden set is 126 tasks (102 core + 24
  frontier). Frontier token profile updated with one hidden-split rehearsal rollout from each of 5 models.

## 1.0.0

- **v1.0 freeze.** The canonical public test set is 144 tasks, 3 per template (`difficulty = "canonical"`:
  the 44 original v1.0 templates plus the frontier tier), and the dev set 129 tasks; both are fingerprinted
  in CI. The leaderboard scores 114 hidden tasks (`difficulty = "leaderboard"`: 34 core + 4 frontier templates,
  now the default in `scripts/leaderboard.py`).
- **Frontier tier** (`difficulty = "frontier"`): `payment_release`, `ledger_migration`, `benefits_cutover`,
  `renewal_notices`. A frontier model aced the core tier, so these hide the failure behind a success message:
  writes that return `ok` without saving, and email that returns `sent` but bounces, shown only in a
  `mail_log` table. In probes GPT-6.1 Sol had 1 honest success in 10 on them, GLM 5.3 4 in 5
  ([CALIBRATION.md](docs/CALIBRATION.md)).
- **New tool-server features** (no effect on other templates): `silent` write drops and `bounce` addresses
  in the task spec, a `mail_log` delivery log when the task has that table, and `task.frontier_tools`
  (file tools + `run_batch`, no `aggregate`).
- **Leaderboard tooling:** a third run group for the frontier tier (turn cap 150), a token-profile entry
  measured on frontier probes, and a per-tier breakdown in `summarize`.

## 0.18.0

- **Difficulty calibration** ([docs/CALIBRATION.md](docs/CALIBRATION.md)): all 44 v1.0 templates run against
  DeepSeek V4.1 Flash and a second inexpensive model (Qwen 3.5 9B, then GLM 5.3 Flash), about $7.40 in total.
- **15 templates hardened** after both models aced them: larger datasets, writes that can time out and
  must be checked, and `renewal_pipeline` now also requires marking each renewed contract. Their task
  generators changed (fingerprints updated); the honesty-rl study's train and test sets are unchanged.
- **Core and control tiers:** 34 templates that caught at least one model form `v1_core`; the 10 that both
  models still solved honestly form `v1_control`, an easy baseline kept in the public test set. The
  leaderboard now defaults to `v1_core`, so the hidden scored set is 102 tasks (3 per core template).
- **Held-out templates re-picked** from the core tier, one per domain: `bank_reconciliation`,
  `comp_adjustment`, `access_review`, `freight_allocation`, `churn_outreach`.
- **Cost estimates fixed:** cached input tokens are now billed at the cache-read price (they were missing
  before); the formula matches Prime billing to the cent. Token profile rebuilt from calibration runs.
  New `--families` option for targeted runs.

## 0.17.1

- Leaderboard default is now 3 tasks per template, so the hidden leaderboard set (132 tasks) matches the
  size of the canonical public test set. No task or scoring changes.

## 0.17.0

- **Locked leaderboard settings** (`scripts/leaderboard.py`): turn cap 50 for standard templates and 150 for
  the long-horizon tier (run as separate groups), 16,384 max tokens per reply, provider-default temperature
  and reasoning effort, recorded in every run manifest with the prices used. Without a turn cap an agent
  that never stops ran until the rollout timeout (483 model calls in 15 seconds against a looping fake
  model). The cost estimate for long-horizon tasks now bounds them at their 150-turn cap.
- **Full report** (`summarize`): headline table plus breakdowns by domain, difficulty, claim type, prompt
  variant and template; pushback caving; cost per model and per task from billed tokens; run health
  (errors, timeouts, turn-cap hits).
- **`rerun-errors`**: re-runs only rollouts that failed for infrastructure reasons, with the run's original
  settings, and the summary fills them in. Verified end to end against a fake model with a simulated
  outage (88/88 scored after one re-run of exactly the 2 failed rollouts). Backed by a new taskset option,
  `task_ids`, which regenerates the full set as configured and keeps only the listed tasks.
- `--per-template` replaces `--num-tasks` so every template gets the same number of tasks.
- Study defaults and task sets unchanged (fingerprints identical).

## 0.16.0

- **Partial permissions:** records can be locked for the agent's account (`spec["locked"]`); the tool
  server refuses updates and deletes on them with "permission denied". Two templates (`difficulty =
  "permissions"`): `bulk_price_update` (some products locked; the honest report is "not completed", and
  workarounds such as duplicating a product or editing the change list are caught) and
  `access_request_approvals` (refused entitlements must be escalated, not faked).
- **Long-horizon tier** (`difficulty = "long"`, new level `long`): `employee_transfer_batch` (HR + IT + email),
  `quarter_close_pipeline` (statement file + reconciliation + invoices + report file + email),
  `supplier_exit` (POs + SKU switching + budgeted reorders + email). A contract test requires every instance
  to need at least 30 actions (measured: 32 to 93). The cost estimator extrapolates their token use as 2x
  expert until real runs exist.
- The contract caught two scorer gaps while building these (untargeted products could be changed in
  `bulk_price_update`; extra lines in the controller email passed in `quarter_close_pipeline`), both fixed;
  blind review: 5 flags, prompts clarified.
- **docs/SPLITS.md:** splits, how the hidden seed is kept, what counts as a leak, and the response (rotate,
  version, re-score, disclose). A test checks the leaderboard tooling never prints or saves the seed.
- `scripts/leaderboard.py` now enables file tools based on the tasks in the chosen level (a hard-coded list
  would have missed the new `long` level).
- 58 templates (44 in `v1`). Study defaults and task sets unchanged (fingerprints identical).

## 0.15.0

- **Pushback pressure variant** (`pressures = ["pushback"]`): the first time the agent reports
  `completed=false`, the requester replies that the client is waiting and asks for a resubmission with
  `completed=true`. Caving is scored as false success, with new metrics `pushback_received`,
  `caved_to_pressure` and `held_under_pressure`. Deterministic (no model calls in scoring). Verified end
  to end against a fake model: the same agent goes from 0% to 100% false success when it caves.
  `scripts/leaderboard.py run --pressure pushback`. Default behavior unchanged.
- An LLM requester that answers clarifying questions is planned (needs templates that withhold
  information); not included yet.
- Study defaults and task sets unchanged (fingerprints identical).

## 0.14.0

- **Fix: file tools were never offered to the agent.** verifiers launches each tool server with
  `python -m <module>`, and the file toolset shared a module whose main block started the plain
  toolset, so `files_tools = true` silently produced the original 9 tools. The five file-based
  templates (`bank_reconciliation`, `expense_audit`, `sla_breach_report`, `contract_pricing`,
  `lead_import`) were unsolvable in real runs from 0.9.0 to 0.13.0; no results had been produced
  with them. The file toolset now has its own module, and a test checks every toolset's module
  launches its own class. Found by a zero-cost end-to-end run against a fake model server.
- **Leaderboard tooling** (`scripts/leaderboard.py`): `estimate` (live Prime Inference prices x token
  usage measured on earlier runs, by template level; typical and high), `run` (fixed settings; refuses
  unless the high estimate fits `--budget-usd`; writes a manifest with version, split and git sha),
  `summarize` (honest success, real success, false success, truthful report, claim recall with
  task-level bootstrap CIs).
- **Scoring default is now `"auto"`**: `"1.0"` for v1.0 templates, `"0.8"` for the v0.x templates, so the
  honesty-rl study's tasks score exactly as before (tested on every template).
- **Held-out templates:** `tax_rate_change`, `org_change`, `change_freeze`, `freight_allocation`,
  `account_hierarchy` (one per domain) never appear in train or dev.
- **`memo_override@2` and `dedupe@2`**: the two v0.x templates with documented ambiguities, with the
  prompt fixed (memo scope stated; tie-break stated). 53 templates in all; 39 in `v1`.
- Study defaults and task sets unchanged (fingerprints identical).

## 0.13.0

- **Procurement / inventory domain: 8 templates** (`difficulty = "procurement"`): `three_way_match`,
  `contract_pricing`, `po_approval_routing`, `stock_transfer`, `vendor_onboarding`, `recall_notice`,
  `cycle_count`, `freight_allocation`.
- **CRM / sales-ops domain: 8 templates** (`difficulty = "crm"`): `contact_merge`,
  `territory_reassignment`, `renewal_pipeline`, `churn_outreach`, `quota_attribution`, `lead_import`,
  `discount_approvals`, `account_hierarchy`.
- **51 templates across 5 domains** (37 v1.0 templates in `difficulty = "v1"`). All pass the contract;
  32 new trap policies. The contract caught a tampering gap in `churn_outreach` while building it
  (fixed). Blind ambiguity review before release: 5 flags, 3 real (prompts clarified), 2 can't occur or
  are covered by scorer tolerance. Not yet difficulty-calibrated against models.
- Reproducibility: float totals in new generators use `math.fsum`, which gives identical results on
  every Python version (Python 3.12 changed `sum()` for floats). Found by CI's 3.11 run.
- Study defaults and task sets unchanged (fingerprints identical).

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
