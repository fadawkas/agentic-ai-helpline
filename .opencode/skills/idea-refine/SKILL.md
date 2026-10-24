---
name: idea-refine
description: Refines a rough concept into a practical direction by exploring alternatives, testing assumptions, and defining a minimal scope. Use for ideation, shaping an idea, or comparing approaches before commitment. Use interview-me instead when the intended outcome itself is unclear; skip already-decided implementation work.
---

# Idea Refine

Explore enough to avoid committing to the first plausible idea, then converge on
the simplest approach that delivers meaningful value.

## Workflow

1. Restate the problem, intended user, desired outcome, and known constraints.
   Inspect relevant existing functionality when working in a codebase. Ask only
   for missing information that would materially change the recommendation;
   use `interview-me` if the goal itself needs discovery.
2. Develop two or three meaningfully different approaches, including a simpler
   alternative that reuses what exists. Explain why each could solve the problem.
   Scale the exploration to the ask; do not generate variations to fill a quota.
3. Compare user value, feasibility, maintenance cost, and relevant trade-offs.
   Separate facts from assumptions. Identify the riskiest assumption and a cheap
   way to test it before investing in the full solution.
4. Recommend a direction with a reason. Challenge weak value or unjustified
   complexity directly and respectfully; avoid agreeing merely to be supportive.
   Incorporate the user's response or exercise judgment when they delegate it.
5. Produce a concise proposal containing:
   - Problem and intended user
   - Recommended direction and why
   - Minimum useful scope and material scope boundaries
   - Key assumptions and how to validate them
   - Success criteria, unresolved decisions, and the next practical experiment

## Boundaries and completion

- Start with the user experience and work backward to technology. Do not choose
  a stack, architecture, or dependency before understanding what it must achieve.
- Keep comparisons honest: do not invent demand, benchmarks, or validation.
- Avoid elaborate scoring frameworks or mandatory documents for a small idea.
  Save the proposal only when requested, following existing project conventions.
- An ideation request authorizes exploration, not implementation. If building was
  also requested, resolve consequential choices and then continue; do not add an
  unnecessary approval gate to decisions the user already delegated.

Done means there is a defensible direction, a bounded first version, and a way to
test the most important assumption. Further planning should serve that scope.
