# Visual Validation

Read this after implementing a visual UI change and before declaring it complete.

1. Start the app with its existing command and open the changed route or flow.
2. Capture and view screenshots at a desktop viewport and a narrow mobile
   viewport. Include relevant below-the-fold content.
3. Compare the render against the brief, viewed references, and existing design
   system. Inspect hierarchy, type wrapping, spacing, alignment, clipping,
   contrast, imagery, and whether the primary task is obvious.
   For a new design or redesign, critique aesthetic quality as well as defects:
   - Could this screen belong to almost any company after swapping its logo and
     copy? Identify which visible decisions connect it to this product.
   - Is the chosen visual concept and memorable element actually evident in the
     rendered result? Does the rest of the screen support that focal point?
   - Do typography, imagery, density, and composition work together at actual
     reading size? Check the rhythm of the whole page, not just the first screen.
   - Name up to three concrete weaknesses that most reduce quality, then fix the
     meaningful ones and inspect fresh screenshots. Do not invent defects or
     redesign a successful result to satisfy an iteration count.
4. Exercise changed controls with keyboard and pointer input. Check the relevant
    responsive, loading, empty, error, disabled, and long-content states.
   Inspect focus visibility and order, accessible names, and semantic structure.
   Check intermediate layout transitions and zoom/reflow where affected. Use
   accessibility tooling or screen-reader checks when available and relevant;
   do not infer accessibility solely from a screenshot or automated scan.
5. Inspect browser console errors and failed requests relevant to the change.
6. Fix observed defects, then recheck affected behavior and inspect fresh
   screenshots when appearance changed. Stop when the criteria are met; report
   blocked checks and the actual viewports/flows inspected.

Use component-specific checks only when applicable:

- Forms: visible label or accessible name, field-level validation, and duplicate
  submission prevention.
- Dialogs: initial focus, focus containment and restoration, clear dismissal,
  Escape behavior where appropriate, and a usable small-screen layout.
- Tables and lists: readable density, controlled overflow, consistent actions,
  and a useful empty state.
- Data mutations: loading feedback, understandable recovery from failure, and no
  surprising layout shift.
