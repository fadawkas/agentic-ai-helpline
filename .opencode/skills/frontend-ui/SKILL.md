---
name: frontend-ui
description: Build or improve frontend UI, layouts, styling, and components. Use for visual changes, supplied screenshots or reference links, responsive design, or when the user wants a polished, distinctive result rather than generic AI-generated UI. Requires visual inspection of the rendered result when browser tools are available.
---

# Frontend UI

Build product-quality UI that makes deliberate choices for this product, without
reinventing the project's primitives or producing a generic template.

Use `senior-engineering` alongside this skill for substantive application logic.
This workflow is framework-independent and adds design and interaction judgment.

## Workflow

1. Inspect the existing theme, components, layout patterns, and strong existing
   screens. Reuse the design system unless a redesign is requested.
2. If screenshots or reference URLs are supplied, view them before coding.
   Extract specific decisions about hierarchy, composition, typography, density,
   imagery, and interaction. A text fetch or accessibility snapshot is not visual
   inspection. If a reference cannot be viewed, say so rather than inventing
   observations.
3. For a substantial new surface without references, study two or three relevant
   shipped products when browser/search tools are available. Borrow principles,
   not branding, assets, or whole layouts.
4. For substantial work, state a compact design brief: audience, screen purpose,
   primary action, content hierarchy, relevant states, responsive behavior, and
   visual direction. For a new design or redesign with creative freedom, use the
   creative direction process below; for an established UI, preserve its visual
   language. Small fixes need only the relevant criteria, not a design exercise.
5. Implement with existing tokens and components. Include only the states the
   surface actually has: loading, empty, error, long content, and interactions.
6. Run the app, capture screenshots, and view them at desktop and mobile sizes.
   Fix concrete problems, then inspect fresh screenshots. Read
   `references/visual-validation.md` before this step.

If browser tools, the runtime, or access are unavailable, report the blocked
visual verification and state how it should be completed.

## Creative direction

For substantial new designs or redesigns with creative freedom:

1. Identify what is specific to this product: its subject, audience, content,
   materials, or characteristic activity. Write a one-sentence visual concept
   rooted in those specifics. Translate words such as "premium" or "modern" into
   visible choices rather than treating them as a direction.
2. Consider two or three plausible directions before coding. Vary composition,
   typography, and the role of imagery, not just accent colors. Choose the
   strongest fit and briefly explain why. Produce multiple visual previews when
   the user requests exploration or comparison; otherwise proceed with the chosen
   direction. Follow supplied references and brand constraints rather than
   reopening decisions the user has already made.
3. Make the chosen direction concrete: palette and color roles, typefaces and
   type scale, layout and alignment, density, imagery, and interaction character.
   Reuse existing tokens where appropriate; define only the missing values needed
   for this surface. Name one memorable element and explain its connection to the
   product. Do not make every section compete for attention.
4. Challenge the plan before implementing: could it fit an unrelated company
   after swapping the logo and copy? If so, revise the most generic decision.
   Distinctiveness should come from the subject and user task, not novelty alone.

Match the creative emphasis to the surface:

- Marketing and brand pages: composition, visual storytelling, and persuasive
  hierarchy. The opening should show what makes the subject worth attention.
- Apps and dashboards: task flow, navigation, readable data, appropriate density,
  and clear interaction feedback. Put useful content first rather than adding a
  marketing hero to a workspace.
- Storefronts: product imagery, comparison, discovery, and a clear path to purchase.
- Settings and forms: clear grouping, understandable choices, and reliable feedback.
- Existing products: extend their established identity unless a redesign is requested.

## Design judgment

Layout should follow real content and user tasks, not a default hero-to-cards
template. Use precise, realistic copy; do not invent customer claims, metrics,
or decorative filler.

- Make typography, spacing, imagery, and hierarchy serve the product and its
  audience. Let structural labels, dividers, and motion communicate something
  true rather than decorate.
- Spend visual emphasis deliberately. One memorable, subject-appropriate move is
  stronger than competing gradients, glows, cards, or animation.
- Do not reach reflexively for cream-and-serif, dark-and-neon, gradient blobs,
  glass panels, numbered eyebrows, or identical rounded cards. They are valid
  only when the brief or existing system makes them an intentional choice.
- Preserve familiar controls and readable content; distinctiveness must not harm
  usability.
- Treat typography as part of the composition: choose roles, scale, weight, line
  length, and spacing deliberately. Use the established brand fonts where present;
  a new typeface should earn its place through the brief, not novelty.
- When an image, illustration, demo, or visualization drives the concept, select
  or shape it early and compose around it. Use suitable available assets with
  required attribution. Make cropping, scale, and placement intentional instead
  of dropping generic imagery into a leftover rectangle. If a key asset is
  unavailable, identify the gap and use an honest fallback.

## Implementation floor

- Reuse existing components and tokens before creating new ones. Keep CSS
  specificity and responsive rules straightforward.
- Make keyboard focus, labels, disabled states, and user-triggered feedback
  visible. Respect reduced motion and the project's dark-mode behavior.
- Use one obvious primary action where the task calls for one. Never expose raw
  technical errors to end users.

## Interaction and accessibility

- Prefer semantic HTML and native controls, or the project's proven accessible
  primitives. Use buttons for actions, links for navigation, and labels for
  inputs. Add ARIA only where semantics do not already express the behavior.
- Ensure keyboard operation, visible focus, logical focus order, and meaningful
  accessible names. For dialogs, contain focus while open, support appropriate
  dismissal, and restore focus to the trigger. Reuse tested primitives.
- Use a logical heading hierarchy and landmarks. Do not convey state through
  color alone. Target WCAG AA contrast: 4.5:1 for ordinary text and 3:1 for large
  text; keep control boundaries and focus indicators distinguishable.
- Forms need understandable instructions and field-level errors linked to the
  input. Preserve entered values after recoverable failures. Prevent duplicate
  submissions and provide meaningful progress and success feedback.
- Keep actions functional: wire controls to real behavior within the requested
  scope. Clearly identify prototype-only behavior when the task calls for it.

## Responsive content and state

- Let content determine breakpoints within the project's conventions. Check a
  narrow mobile view, desktop, and intermediate widths where the layout changes.
  Preserve reading order, usable touch targets, and access to essential actions.
- Handle long labels, large values, wrapping, and empty content. Check zoom and
  reflow; constrain table overflow without clipping the rest of the page.
- Keep transient interaction state local where possible. Use URL state for
  shareable navigation/filter state when appropriate, and the project's existing
  remote-data mechanism for loading, caching, and mutations. Avoid redundant
  state or adding a global store for a local interaction.
- Make loading and failure handling match the operation. Optimistic updates need
  reliable recovery; do not add them automatically to consequential actions.

## Performance and finish

- Use appropriately sized assets and reserve image/content space to reduce
  layout shifts. Avoid unnecessary client-side work or dependencies for native
  capabilities. Profile before adding memoization or other complex optimizations.
- Completion requires the changed flow to work, the layout to meet its brief,
  and applicable interaction/accessibility checks to pass. Screenshot inspection
  proves appearance, not keyboard behavior or screen-reader accessibility;
  report which checks actually ran.
