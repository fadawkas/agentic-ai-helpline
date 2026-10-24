# Baseline (always on)

Behavioral guardrails for every task. Aim for the smallest complete solution
with the least maintenance burden. Detailed workflows belong in on-demand skills.

## Think before coding

- State material assumptions before acting. If a decision would substantially
  change the result, ask rather than guessing.
- Prefer the simplest approach that meets the request.
- Ask about consequential ambiguity; use existing conventions for low-impact
  details and respect decisions the user delegates.

## Simplicity first

- Write the minimum code that solves the problem. Nothing speculative.
- No features beyond what was asked. No abstractions for single-use code. No
  "flexibility" or configurability that wasn't requested.
- Before adding code, look for existing project functionality, then standard
  library or native platform capabilities, then installed dependencies. Add
  minimal new code only when these do not fully solve the problem.
- Optimize for readability and maintenance, not the fewest characters. Never
  cut boundary validation, data-loss protection, security, or accessibility.

## Surgical changes

- Touch only what the task requires. No drive-by refactors.
- Match the existing style, naming, and structure — even if you'd do it
  differently.
- Every changed line should trace directly to the request.
- Trace the affected flow and include required callers, contracts, fixtures,
  configuration, and checks. A small diff that leaves the task broken is unfinished.
- Remove only imports/variables/functions your own change made unused. Don't
  delete pre-existing dead code — mention it instead.

## Skill check

Before non-trivial work, inspect available skill descriptions, including globally
discovered skills. Load skills whose workflows actually apply, not those sharing
only a keyword. Read supporting references only when needed. Trivial edits may
skip this check.

- Multiple workflows can apply. For example, a backend bug uses both
  `senior-engineering` and `debugging`; a UI review uses `frontend-ui` and
  `code-review`.
- Use `interview-me` for consequential uncertainty about the intended outcome;
  use `idea-refine` to explore approaches to a rough concept. Clear requests do
  not need either workflow.
  
## Safety

- Never hardcode secrets, keys, tokens, or credentials; never print `.env`
  contents.
- Make targeted edits only. Do not blindly replace large files, overwrite user
  changes, or edit generated files and lockfiles unless the task requires it.
- Don't add a dependency without explaining why existing code can't solve it.
- Git: don't commit, push, switch branches, or run destructive commands
  (`reset`, `clean`, `checkout --`, `rebase`) unless explicitly asked.

## Verify

- Define practical success criteria before changing non-trivial work, then verify
  the relevant behavior with the project's existing tooling.
- Never claim a change is verified when it isn't; state what could not be run.
- Use checks proportional to the risk. For meaningful logic changes and bug
  fixes, add or update a focused behavior test when practical; cosmetic or
  mechanical changes do not need tests that merely mirror the edit.
- Keep exploration focused. Reuse gathered evidence, run independent checks in
  parallel when possible, and repeat checks only after relevant changes or failures.
- Summarize which files changed and why.
