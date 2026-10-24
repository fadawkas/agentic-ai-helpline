---
name: code-review
description: Review, refactor, clean up, or improve the quality of existing code. Use when the user asks to review code, find bugs or edge cases, reduce complexity, remove duplication, improve maintainability, or make code cleaner and more optimal — anything framed as evaluating or improving code that already exists rather than writing new behavior. For diagnosing a specific failure, use debugging instead.
---

# Code Review

Review existing code for material risks and the smallest high-impact
improvements. Preserve behavior unless the request asks to change it.

## Review priorities

Work in this order — do not polish style before correctness is settled:

1. Correctness
2. Safety
3. Simplicity
4. Maintainability
5. Performance
6. Style consistency

## What to look for

First establish the intended behavior and review boundary. Read relevant tests
and surrounding code, then trace changed contracts to callers, consumers,
exports, fixtures, and configuration. A defect may be outside the diff. Distinguish
observed problems from hypotheses that still need checking.

- Hidden bugs, broken edge cases, unhandled null/undefined.
- Race conditions and incorrect async handling.
- Overcomplicated or duplicated logic; unnecessary state or dependencies.
- Unclear boundaries or duplication that makes behavior unsafe to change.
- Unsafe input handling and security issues.
- Poor naming.
- Performance bottlenecks that actually matter (not hypothetical ones).

## Refactoring rules

- Keep behavior identical unless the user asked to change it. Preserve public
  APIs.
- Make small, safe, reviewable improvements. Don't rewrite whole files unless
  the current structure genuinely blocks the requested improvement.
- Extract only when it improves a concrete boundary, clarity, or testability.

## Output

When reviewing without editing, report only actionable findings, ordered by
severity. Each finding includes its location, impact, and evidence. If there are
no findings, say so and name remaining test gaps.

Use clear severity labels (critical, required, optional) and suggest the smallest
useful remedy. Prioritize correctness and security; do not bury them under style
preferences or report hypothetical performance problems as established facts.
Explain the failure condition and user impact, not just that code looks complex.

When asked to edit, implement the approved or clearly requested fixes only, then
verify the affected behavior with the project's existing checks.
