---
name: debugging
description: Investigate and fix a specific failure: errors, exceptions, failed builds, failed tests, broken UI behavior, broken API behavior, or anything not working as expected. Use when there is a concrete symptom to diagnose and a root cause to find, and when deciding what tests are needed to lock the fix in. For general quality review without a specific failure, use code-review.
---

# Debugging

Find the root cause and make the smallest safe fix. Do not rewrite code hoping
the symptom disappears, and do not silence it.

## Process

1. Read the symptom carefully and reproduce it when feasible.
2. Identify the failing file, function, component, route, or command.
3. Inspect the smallest relevant area first; trace the data flow.
4. Form a specific root-cause hypothesis and test it with the smallest useful
   reproduction, targeted check, or diagnostic. Change one relevant factor at a
   time; revise the hypothesis when evidence contradicts it.
5. Patch the smallest safe area.
6. Check nearby code for the same mistake when the cause could repeat.
7. Verify the original reproduction now passes and relevant checks still pass.
   Where practical, leave a regression test that fails on the original defect
   and passes with the fix. If reproduction is blocked, distinguish a suspected
   cause from a demonstrated one.

## Do not

- Rewrite large unrelated parts, or change public behavior unless required.
- Hide the root cause behind a broad `try/catch` that just swallows the error.
- Disable lint, typecheck, or tests to make the problem disappear.

## A good fix is

Small, direct, easy to review, consistent with the surrounding style, and
covered by a test where practical.

## Where to look

When the bug is in the UI: component state, conditional rendering, z-index and
stacking context, CSS positioning, responsive classes, parent container size,
overflow, event handlers, disabled/loading states. For visual defects, reproduce
and inspect the rendered result in a browser when available.

When the bug is in the backend: request validation, auth/permission middleware,
controller/service boundaries, query shape, null results, async/await handling,
error response format, environment variables.

## Tests

Add or update tests when you change business logic, validation, API behavior, or
a critical UI flow. Test behavior, not implementation details. Keep tests
deterministic. Mock external services, not the internal logic under test. Name
tests according to project conventions, describing the behavior and condition.

## Verification

Prefer the project's existing commands (typecheck, lint, unit/integration tests,
build, or Docker Compose checks if the project uses Docker). If checks can't be
run, say so and state what to run manually.
