---
name: interview-me
description: Clarifies intended outcomes through a focused, one-question-at-a-time interview. Use when the user asks to be interviewed or when consequential uncertainty about users, goals, success criteria, or constraints would otherwise require guessing. Skip clear requests and routine implementation choices.
---

# Interview Me

Find the actual problem before committing to a solution. Ask only questions whose
answers could materially change what gets built.

## Workflow

1. Read the request and available project context. State your current understanding
   in one sentence and identify the most important unresolved decision. Do not
   ask the user to repeat information already provided or discoverable in code.
2. Ask one focused question at a time. Where helpful, attach a tentative guess
   and its reason so the user can correct it easily. Avoid leading questions that
   assume the requested solution is already the right one.
3. Use each answer to choose the next question. Establish the intended user,
   actual problem, desired outcome, success criteria, and binding constraints
   only to the depth the task needs. Translate terms such as "fast" or "scalable"
   into concrete expectations when they affect the solution.
4. When enough is known, summarize the intended outcome, relevant constraints,
   acceptance criteria, and material scope boundaries. Ask for confirmation only
   if consequential uncertainty remains or the user requested a formal interview.
5. Accept ordinary confirmation and explicit delegation. If the user says to use
   your judgment, choose a reasonable approach, state material assumptions, and
   proceed within the authorized scope. Do not demand a particular confirmation
   phrase or keep interviewing after understanding is sufficient.

## Stack selection

Use the stack explicitly specified in the prompt or established by the existing
project. Ask about the user's preferred stack only when the task requires choosing
one and the prompt and project context do not resolve that choice. If only part
is unresolved, ask only about that part, and only if it materially affects the
solution. Do not turn every unspecified library into a question.

If the user delegates the choice, recommend a suitable stack, briefly explain why,
and proceed. Include the specified, existing, or chosen stack in the final shared
understanding when relevant to implementation.

- "Build this using Next.js and Supabase": use those choices without asking again.
- "Add filtering to this Vue app": follow the existing stack and conventions.
- "Build a new booking application" with no project context: ask about stack
  preference when selecting the implementation approach.
- "Choose whatever stack fits best": choose, explain briefly, and proceed.

## Boundaries and completion

- Use existing conventions for reversible, low-impact details; do not turn every
  missing detail into a blocking question.
- If several exchanges do not resolve the uncertainty, explain the remaining
  decision plainly and offer a concrete choice rather than repeating questions.
- In non-interactive work, continue independent work where possible and report
  consequential blockers instead of inventing answers.
- The deliverable is a concise shared understanding, not automatically a PRD or
  saved document. Save it only when requested.
- If only an interview was requested, finish with the summary. If implementation
  was already requested, continue once the relevant ambiguity is resolved.
- Use `idea-refine` when the outcome is understood but possible approaches still
  need exploration. Clear implementation work goes to `senior-engineering`.

Done means the next action can be chosen without guessing about a consequential
requirement. Do not manufacture numerical confidence scores.
