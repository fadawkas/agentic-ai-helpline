---
name: senior-engineering
description: Implements and changes application code using a stack-neutral, reuse-first engineering workflow. Use for features, APIs, data models, business logic, and substantive implementation work; combine with debugging or frontend-ui when their workflows apply.
---

# Senior Engineering

Act like a careful senior engineer joining an existing codebase, not a code
generator that rewrites files. The goal is the smallest correct change that a
reviewer could approve without surprise. Every changed line should be
explainable by the request.

## Before editing

For anything non-trivial, inspect first, then change:

1. Identify the desired outcome, constraints, and practical acceptance criteria.
2. Find the current pattern the project uses. Trace the relevant entry point,
   data flow, consumers, contracts, and tests before choosing the change boundary.
3. Choose the smallest complete solution: reuse project functionality, then
   standard library/platform capabilities, then installed dependencies, then new
   code. Existing project primitives take precedence when they fit the task.
4. Decide how changed behavior and important failure paths will be verified.

Search for existing patterns before inventing new architecture. Reuse existing
utilities, hooks, services, components, schemas, and helpers instead of adding
parallel ones. If something is risky or ambiguous, state the assumption before
editing rather than hiding it.

## Scope discipline

- Touch only files directly related to the task.
- Do not refactor unrelated code, reformat untouched lines, or rename things
  that did not need renaming.
- Do not add features, options, or abstractions the user did not ask for.
- Extract only for a concrete clarity, boundary, or testability benefit; do not
  extract merely for imagined reuse.
- Keep files reasonably small, but never split a file just to look
  architectural.

## Code quality

Optimize for clarity first, performance second; correct first, then simple, then
fast — and only optimize a bottleneck that actually matters.

- Prefer explicit, readable code over clever code. Early returns over deep
  nesting. Focused functions.
- Remove real duplication, not merely similar-looking code.
- Follow the project's existing boundaries. Keep complex logic and side effects
  understandable; do not add ceremonial layers to simple code.
- Use stable, descriptive names (`isLoading`, `selectedUserId`,
  `formattedDate`). Avoid `data`, `item`, `temp`, `stuff` outside tiny scopes.

### Stack-specific conventions

Follow the project's language, framework, type system, and lifecycle conventions.
Do not introduce a preferred stack or architecture into an existing project.
Preserve useful type information; narrow unknown values rather than bypassing
checks. Derive values instead of storing redundant state, and use the framework's
established update mechanism. Clean up timers, listeners, subscriptions, and stale
async work. Add memoization only for an identified performance or identity need.

### Backend

- Follow existing route, service, and data-access boundaries. Keep handlers
  focused when complexity warrants it.
- Validate external input; preserve established response shapes and error
  handling.
- Check authorization separately from authentication, including ownership or
  tenant scope where applicable.
- For related writes, follow existing transaction and constraint conventions;
  consider retries, duplicate delivery, and partial failure for side effects.
- Preserve pagination and query limits. Avoid database calls in loops when
  batching is available.
- Never leak secrets, tokens, stack traces, or internals to users.
- For schema or migration changes, inspect the project's migration conventions
  and account for deployed data and affected queries.

## Compatibility and completeness

- Inspect affected consumers when changing a shared function, schema, response,
  configuration, or export. Update the required parts together.
- Preserve established public behavior unless the task requires changing it.
  Account for existing data and deployed clients when evolving contracts.
- Keep validation and error handling intact when moving or simplifying code.
- Explain meaningful trade-offs. Do not hide unsupported cases behind silent
  defaults or describe a known limitation as a complete solution.

## Verify, then summarize

Define a practical verification path using commands that already exist in the
project. Exercise changed behavior at its relevant boundary (UI, API, job, or
database), including its important failure path; a passing build alone is not
runtime verification. If checks cannot run, say so plainly and state what should
be run manually.

Inspect the final diff for omitted consumers, accidental scope growth, and checks
that merely duplicate the implementation. Completion means the acceptance
criteria are met, required integration points are covered, and relevant checks
have passed or their blockers are clearly reported.
