# Splits and the hidden test set

## Splits

| Split | Seed | Published | Use |
|---|---|---|---|
| `train` | public (`seed` + 0) | yes | RL training |
| `dev` | public (`seed` + 20,000) | yes | Model selection, debugging |
| `test` | public (`seed` + 10,000) | yes | Reproducible evaluation (the honesty-rl study used it) |
| `hidden` | secret (`POTEMKIN_HIDDEN_SEED` + 30,000) | **no** | Leaderboard scoring only |

All four use disjoint generator seeds, and a test checks that no generated task appears in two splits.
Five templates (one per domain: `tax_rate_change`, `org_change`, `change_freeze`, `freight_allocation`,
`account_hierarchy`) are **held out**: they never appear in `train` or `dev`. Their generator code is
public like every other template's, so held-out templates measure generalization beyond the training
distribution, not secrecy.

## Canonical public test set (v1.0)

At v1.0 the benchmark freezes a public test set of **132 tasks: 3 per v1.0 template** (`split = "test"`,
`difficulty = "v1"`, `num_tasks = 132`, default seed), fingerprinted so it never changes within a version.
Anyone can run it; the leaderboard scores a separate 88-task hidden set (2 per template).

## How the hidden seed is kept

- The seed is a random integer held by the maintainer outside the repository (and backed up separately).
  It is never committed, logged, printed, or written to run manifests; a test run checks the leaderboard
  tooling's output and manifest for it.
- Hidden-split scores are produced only by the maintainer with `scripts/leaderboard.py run --split hidden`.
  Results cite the benchmark version, which identifies the hidden set (`hidden@<version>`).

## What counts as a leak

1. The seed itself is disclosed.
2. Hidden-split tasks, prompts or reference answers are published or shared.
3. Evidence that a model was trained or tuned on hidden-split tasks (for example, hidden-split scores far
   above `test` scores on the same templates, with no comparable gain elsewhere).

## Response to a leak

1. **Rotate:** generate a new seed; the old hidden set is retired immediately.
2. **Version:** bump the minor version and record the rotation in the changelog (no task generator
   changes, so `test`, `dev` and `train` stay identical).
3. **Re-score:** re-run every leaderboard entry on the new hidden set. Old scores stay visible, labelled
   with their `hidden@<version>`, and are not compared with new ones.
4. **Disclose:** a short note in the changelog and on the leaderboard saying what leaked and when (no
   details that would recreate the leaked set).

Routine rotation: from v1.0 on, the hidden seed is also rotated whenever generator changes produce a new
benchmark version, so each version's hidden set is scored fresh. (Before v1.0 the hidden set isn't used
for scoring.)
