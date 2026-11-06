---
name: run-protocol
description: 'Use before planning the runs that produce reported numbers: how many
  repetitions, seeds or splits one result needs, and how to check they are independent.'
version: 2
evidence:
- 20261017-143741_v4-itransformer_planner_workers_haiku55
---

When: you are about to run the experiments whose numbers will be reported.

Steps
1. Find the protocol: the task text, the paper's setup section, the authors' script. Write down what ONE result
   is: e.g. the mean over N splits, the mean over K seeds, one deterministic run.
2. One submitted run must follow that whole protocol. If the script's default does fewer repetitions than the
   protocol (one split instead of ten), set the argument or loop over the repetitions yourself, calling the
   authors' code.
3. Seeds: check in the code that the seed you pass reaches every random source (data split, initialisation,
   sampling, library RNGs). If it does not, wire it through with a minimal change and record it.
4. Each run prints its own trace (split/seed number and its result) and the final aggregate, unfiltered.
5. One run that prints several of the requested numbers (e.g. two metrics of the same model) is the run for all
   of them: cite the same log for each, never run the identical command again per metric.
6. After two runs with different seeds, compare their numbers. Identical values to all printed digits mean the
   seed is not used (unless the method is deterministic and the data split is fixed: then say so in notes).

Checks
- Number of repetitions per run = the protocol's number; no two runs with the identical command and seed.
- Different seeds give different values wherever randomness exists.
