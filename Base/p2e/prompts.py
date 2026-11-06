"""Prompt text shared by the LLM workflow versions (SingleAgent, Multiagent/*)."""

# When may a run's setup be changed after seeing a result? Both workflows get the same rules, so that the
# single agent's free-form loop and the multi-agent Result Reviewer are held to one standard.
SETUP_CHECK_RULES = """Setup check (compare first results with the values the paper reports):
- A large gap often means the run does not follow the paper: a wrong dataset, split, metric or unit; a
  flag left at a repository default that no table uses; or training cut shorter than the paper's (or the
  official script's) budget without need. Fix such setup errors, citing the paper section or the code
  location that justifies every change.
- Paper text vs official command: when the authors' own command or script for reproducing this table (README,
  scripts/...) disagrees with the paper's text (epochs, batch size, ...), use the official command for the
  measurement, run the paper-text setting once as a diagnostic, and report both and the conflict. A plain
  code *default* that no reproduction command sets is not such a command: there the paper's text wins.
- Never change a setting the paper or the official script states, and never search hyperparameters or seeds
  to hit the paper's number. A gap that remains under a faithful setup is a result to be diagnosed, not
  something to fix."""

# Long runs: hangs (e.g. DataLoader workers on macOS) cost whole timeouts; scaling down costs fidelity.
RUNTIME_RULES = """Runtime:
- The first time you run a command that might hang, give it a short timeout (120-300 s) and check that it
  makes progress before starting long runs.
- Before scaling an experiment down, time a short run and extrapolate. Scale down only if the full
  setting would exceed the time limit, and write the estimate down."""
