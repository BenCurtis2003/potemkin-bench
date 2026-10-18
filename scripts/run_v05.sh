#!/bin/zsh
# Official v0.5 benchmark: held-out test split, 24 expert tasks x 3 rollouts per model.
cd "$(dirname $0)/.."
for m in "$@"; do
  .venv/bin/vf-eval potemkin-bench -m "$m" -n 24 -r 3 -c 4 --push -o outputs_v5 \
    --env.agent.harness.id null --env.agent.runtime.type subprocess --env.agent.timeout.rollout 2400 \
    --env.taskset.split test --env.taskset.num-tasks 24 > "outputs_v5/log_${m//\//_}.txt" 2>&1
done
