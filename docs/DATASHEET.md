# Datasheet: PotemkinBench

Follows the structure of *Datasheets for Datasets* (Gebru et al.). Version 0.13.0.

## Motivation

- **Purpose.** Measure whether AI agents doing multi-step tool-use work (a) complete it correctly and
  (b) truthfully report whether they did. False success, claiming a job is done when it isn't, is
  measured directly by scoring the end state and the agent's report separately.
- **Why it's needed.** Agents trained with RL can learn to satisfy graders that trust their reports.
  Most agent benchmarks score task success only; few score the honesty of the self-report.
- **Creator.** Ben Curtis. Not funded by any organization.

## Composition

- **Instances.** A task is a generated mock-company database (and for some tasks, files such as a
  bank statement or an expense policy), a natural-language request, and hidden scoring data. The agent
  works through tools (read, update, create and delete records, send email, read and write files, aggregate)
  and ends with `submit_report(completed, summary)`.
- **Templates.** 51 task templates in 5 domains (finance back-office: 19; HR / people ops: 8; IT service
  desk: 8; procurement / inventory: 8; CRM / sales ops: 8). Each
  template generates unlimited instances from a seed. Full list, with what each tests and its trap:
  [TEMPLATES.md](TEMPLATES.md).
- **Traps.** Every template has a built-in reason an agent might believe, or prefer to say, the work is
  done when it isn't: pagination, rules stored in data, memos that override the prompt, writes that
  silently time out, impossible or partly possible requests, decoy records, totals that look right
  while rows are wrong.
- **Labels.** Ground truth is computed by the generator. Every instance has exactly one correct end
  state and one truthful report. Scoring is deterministic code; no human or LLM labels.
- **Splits.** `train`, `dev` and `test` (public, disjoint generator seeds), and `hidden` (seed held
  outside the repository, for leaderboard scoring). Templates can be held out of train and dev.
- **Personal or sensitive data.** None. All people, companies, emails (`.test` domains), amounts and
  records are synthetic.
- **Real-world rules.** Some templates use simplified versions of real rules (California daily
  overtime, multi-currency conversion at fixed rates). They are not a reference for real compliance.

## Collection process

- Instances are produced by seeded Python generators (`environments/potemkin_bench/potemkin_bench/families*.py`).
- Every template passes an automated **template contract** before release (`tests/test_contract.py`):
  deterministic generation; frozen generator output (fingerprints); a reference solution that passes
  and reports truthfully; doing nothing fails; every single-step mistake on the correct end state is
  caught, with no dead checks; each template's realistic shortcuts are caught; and half work, junk work
  or claim-only never beat honest work. CI runs it on every change.
- A blind review checks each prompt for ambiguity (exactly one defensible end state).

## Preprocessing

None. Tasks are generated on demand; there is no stored dataset to clean.

## Uses

- **Intended.** RL training environment (train split) and evaluation of agents' task success and
  report honesty (test or hidden split). Studying how graders and rewards shape honest reporting.
- **Used in.** A preregistered three-arm RL study on Qwen 3.5 4B:
  [honesty-rl](https://github.com/BenCurtis2003/honesty-rl).
- **Not intended.** Judging real-world HR, payroll, tax or accounting compliance; evaluating
  open-ended writing quality.
- **Caution.** The 37 v1.0 templates (finance_v1, hr, it, procurement and crm levels) are not yet difficulty-calibrated against
  models. The `checklist` and `letter` reward modes are gameable on purpose; don't use them as quality
  measures.

## Distribution

- GitHub: [BenCurtis2003/potemkin-bench](https://github.com/BenCurtis2003/potemkin-bench), MIT license.
- Prime Intellect Environments Hub: `bencurtis2003/potemkin-bench`.

## Maintenance

- Maintained by Ben Curtis. Issues on GitHub.
- Versioned (see [CHANGELOG.md](../CHANGELOG.md)); scores should cite the benchmark version and the
  scoring version (`task.scoring`). Generator changes require a version bump (enforced by fingerprint
  tests), so a given version always produces the same tasks.
- If the hidden split's seed leaks, it is rotated and the minor version bumped.

## Known limitations

- Synthetic tasks, one mock company per domain, five domains.
- `reorder` (v0.x) has an ambiguous budget rule on short budgets; `reorder@2` replaces it.
- Under the default scoring (`"0.8"`), four templates score the report inside their checks; scoring
  `"1.0"` removes this special case (see [METRICS.md](METRICS.md)).
