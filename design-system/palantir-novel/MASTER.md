# Palantir: Novel UI system

## Product and primary flow

Palantir: Novel is a Windows desktop workspace for translating and reviewing long-form novels. Keep the reading/editor canvas central, make navigation predictable, and keep frequent actions readable while the user works for long sessions.

Primary flow: **Novel Library → open a novel → choose a workflow step and file → read/edit → save or export**. Global progress, settings, groups, and other utility pages remain reachable from the main toolbar. Context, find, font size, and novel status actions stay next to the editor they affect.

## Visual direction

Use a restrained **Minimalism & Swiss Style** direction for a desktop writing tool: neutral grayscale surfaces, clear type hierarchy, deliberate spacing, no decorative cards or rounded chrome. Keep accent and focus grayscale so chrome does not compete with novel text. Preserve distinct semantic colors for success, warning, and error states. Check foreground/background pairs against WCAG contrast targets.

### Semantic palette

| Role | Light | Dark |
| --- | --- | --- |
| App background | `#F5F5F5` | `#1E1E1E` |
| Editor / surface | `#FFFFFF` | `#252526` |
| Sidebar | `#F0F0F0` | `#252526` |
| Secondary surface | `#E8E8E8` | `#303030` |
| Main text | `#242424` | `#E6E6E6` |
| Secondary text | `#555555` | `#C2C2C2` |
| Muted / disabled text | `#606060` | `#A0A0A0` |
| Accent / primary action | `#686868` | `#A6A6A6` |
| Keyboard focus | `#5C5C5C` | `#B8B8B8` |
| Selection | `#E2E2E2` | `#414141` |
| Status strip | `#E8E8E8` | `#252526` |

All semantic foreground/background pairs for normal, secondary, muted, disabled, primary-button, selection, status, and focus states must be checked in both appearances. Normal text targets at least 4.5:1 contrast; focus indicators target at least 3:1 against adjacent surfaces.

## Typography and spacing

- Use the system Segoe UI family with Thai fallbacks (Leelawadee UI, Tahoma).
- Set application body text to 12pt (16 CSS px at 96 DPI); use a consistent 12/14/16/18/24/32pt hierarchy for labels through display headings.
- Keep editor typography independently adjustable and preserve its monospace/code-oriented choices.
- Use a 4/8px spacing rhythm; prefer 8px between related controls and larger gaps between sections.
- Prefer wrapping for descriptive text. Preserve the editor toolbar's horizontal scroll affordance instead of shrinking labels when the available width is limited.

## Interaction and accessibility

- Keep every main action keyboard-operable and in visual tab order; show a clear grayscale focus marker on buttons, tabs, fields, lists, and menus.
- Disabled actions remain legible and are distinguished by a quiet surface as well as text; do not use opacity alone to communicate state.
- Use hover and pressed surfaces consistently. State is not communicated by color alone; preserve labels, selected indicators, and status copy.
- Use visible labels/help for complex controls, retain cancel/back routes in dialogs, and show progress feedback for long work.
- Avoid ornamental borders/cards. Keep separators only where they clarify hierarchy or editing boundaries.

## Layout and responsive behavior

- Keep the library → workflow → editor hierarchy stable across screens.
- Let users resize or hide the workflow sidebar. Avoid fixed widths for main content.
- When the editor toolbar cannot fit, keep it vertically stable and horizontally scrollable so every action stays reachable.
- Dialogs and progress surfaces use the same typography, color, spacing, focus, and disabled tokens as the main window.

## Implementation source of truth

`src/novel_workflow/theme.py` owns semantic color tokens, Qt palette roles, and shared widget styles. Editor-only styles map through `editor_colors()` in that module. Do not add independent palette literals to page/widget code; add a semantic token and use it in all relevant surfaces.
