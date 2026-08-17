# Agenda Ask no longer overlays chrome

Ask is `position: fixed; top: 56px`. Terminal never scrolls the
document, so the panel stays under the 56px nav. Agenda's schedule
is a real scrollport; wheel-up at the top rubber-bands the visual
viewport and the fixed panel rides over the in-flow chrome.

## Fix

- Agenda body is a 56px + 1fr grid. Open Ask adds a second column;
  the panel is `position: relative` in that cell, not viewport-fixed.
- `.agenda-main`, `.agenda-rail`, `.ask-log`: `overscroll-behavior: none`.
- Chrome is `position: sticky; z-index: 50` so it paints above Ask.
- Jump-to-today sets `.agenda-main.scrollTop` instead of
  `scrollIntoView` (which walks ancestors).

Asset `0.2.8-agenda-ask-stack`. UI recycle only.
