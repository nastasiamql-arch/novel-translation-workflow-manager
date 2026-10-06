# Palantir: Novel design system

## Product flow and structure

Windows desktop workspace for people translating novels themselves. Navigation sidebar: Library, Workspace, Statistics, Groups, Settings. MainShell owns navigation and update coordination. LibraryPage, WorkspacePage, StatisticsPage and SettingsPage own their surfaces; shared management actions remain in ManagementActionsMixin so working business services and data paths stay intact. library_page.py and settings_page.py own page construction; shell_components.py owns NavigationSidebar, NovelHeader, EditorToolbar and the adaptive page stack. EditorTabs/TxtExportTab own document interaction; ExportService owns verified accounting, translation_progress centralizes Context parsing, recovery owns file backups/rollback, update_bootstrap owns the detached updater.

Workflow is user-selected translation/review/custom steps. Vocabulary is a separate preparation tool. Never infer per-chapter semantic completion or add translation APIs.

## Visual language

macOS-inspired hierarchy and restrained chrome inside native Windows window controls. Neutral surfaces, one understated blue accent, subtle separators and rounded navigation states. Editor gets the largest practical area. Readability outranks effects. No embedded Apple fonts, custom traffic lights or decorative blur.

| Token | Light | Dark |
| --- | --- | --- |
| App | #F3F3F3 | #212121 |
| Editor surface | #FFFFFF | #242424 |
| Sidebar | #F9F9F9 | #282828 |
| Main text | #303030 | #E6E6E6 |
| Secondary | #555555 | #C2C2C2 |
| Muted/disabled | #606060 | #A0A0A0 |
| Accent | #3269A8 | #80B9EF |
| Keyboard focus | #155CA4 | #A5D2FF |
| Hover | #F0F0F0 | #343434 |
| Current line | #F6F6F6 | #2D2D2D |
| Selection | #BDD8F4 | #285582 |
| Selection text | #242424 | #F2F2F2 |

Normal text/selection target 4.5:1 contrast and focus 3:1 against adjacent surfaces. Navigation uses neutral selected background and weight without an accent edge. Workflow uses neutral selected background, weight and a subtle gray edge. Library cards use neutral selection and bold text; blue is reserved for text selection, focus and other semantic accents. Mouse focus rectangles are suppressed; keyboard-only indicators remain. The workspace cover rail is removed; profiles are selected in Library. Hover must not look active. theme.py is the palette source of truth.

## Typography and geometry

UI uses Windows Segoe UI with Leelawadee UI/Tahoma fallback. The application font configuration prefers available Segoe UI Variable Text; shared Qt styles use Segoe UI at 12 pt. Editor uses one Segoe UI primary family at 11 pt by default, adjustable independently, with Qt script fallback to installed Thai/CJK fonts. No monospace font promise.

Use layout size hints and minimums that accommodate Thai glyph height. Wrap explanatory text and elide names with full tooltips. Avoid fixed text-control heights. Sidebar widths are user-resizable; icon mode retains tooltips and accessible labels. Small windows reduce workflow sidebar width to preserve editing space. Frequent toolbar controls hide into More by available width; TXT Export basic fields reflow when narrow. Advanced is a separate settings dialog so it does not consume the editing canvas.

DPI matrix 1.0, 1.25, 1.5, 2.0 tests fresh Qt processes at 900x600 and 1440x860 in Light/Dark. Windows offscreen tests register installed system fonts without bundling them. Check geometry/behavior as well as rendered output.

## Workspace, documents and export

Novel Header shows latest recognized Context chapter, today's translation, chapter goal when configured, today's verified exports and active verified goal cycle. Document status belongs in the eliding bottom status bar: save, words, characters, Ln/Col, UTF-8.

Tabs remain one row with scrolling and middle elision. Files reorder and persist; TXT Export remains last and cannot close. Dirty files show a dot. Undo/Redo availability follows the active document stack and autosave leaves it intact. Native editing shortcuts operate on focus; COPY STEP is Ctrl+Shift+C and must not claim Ctrl+C. Ctrl+Tab/Shift+Tab cycle documents; Ctrl+H finds.

Basic TXT Export presents prefix, next number, daily exports, cycle progress, editor and Submit. Advanced contains destination, target and explicit sequence-range override. Reset cycle is available through More/Advanced. Reaching a target leaves the checkmark in place indefinitely; progress can exceed target. Manual reset archives the previous cycle without deleting daily events. Filename wrap is independent: 1..goal in basic mode; legacy/custom ranges retain start/end/current.

Submit stages UTF-8 TXT and Context, fsyncs, backs up existing destinations, replaces both and durably records the event/next sequence. Detected failures roll back replacements and do not count/advance. Backups are bounded at ten copies per destination, available through document More → History. This is runtime rollback with crash recovery copies, not power-loss atomicity across all destinations. Cosmetic migrations preserve saved theme/font preferences and additive schema 7 retains unknown legacy fields.

Statistics leads with today's/weekly translation and today's verified; chapter-goal management, seven-day history and archived verified cycles expand on demand. Status changes offer a reversible toast action.

## Update

Keep native installation identity B93AE24C-43D9-4D38-A880-93A607EA8D41 and the existing %LOCALAPPDATA%/NovelWorkflow namespace. Verify origin/size/SHA-256, save all document/draft/session/settings state, launch a detached helper outside install directory, close app, reverify bytes, wait for silent Inno Setup and inspect exit status. Use previous install directory/tasks/group and a PALANTIRUPDATE marker. The helper owns relaunch, so manual silent installs stay quiet. Preserve log/result for failure reporting and show the success version after restart.

## Design references reviewed

- [Apple HIG: Toolbars](https://developer.apple.com/design/human-interface-guidelines/toolbars): keep frequent actions visible and contextual, secondary commands in menus.
- [Apple HIG: Layout](https://developer.apple.com/design/human-interface-guidelines/layout): use clear hierarchy and adaptable content geometry.
- [Apple HIG: Menus](https://developer.apple.com/design/human-interface-guidelines/menus): succinct action labels and logical command groups.
- [Apple HIG: Tab views](https://developer.apple.com/design/human-interface-guidelines/tab-views): related document panes with clear labels and pane-local controls.
- [Inno Setup command line](https://jrsoftware.org/ishelp/topic_setupcmdline.htm) and [UsePreviousAppDir](https://jrsoftware.org/ishelp/topic_setup_usepreviousappdir.htm): official silent flags, log and existing installation handling.

## 3.4.1 refinements

Original 24-unit line navigation icons render at device scale with rounded 1.7-unit strokes. Light is the default for new settings; preserve saved appearance. Item selection: #E0E0E0 / #444444; primary action: #303030 with white text / #E6E6E6 with dark text. Hover, selected item, current line and text selection use distinct tokens. Scope local export panel styles to the panel so child button colors remain authoritative. The workspace splitter contains Workflow and Editor only; retain sidebar width and visibility without the cover rail.

## 3.4.2 update identity

Frozen executable version comes from an embedded app-version.txt generated from pyproject.toml, independent of stale dist-info directories. Installer cleans only novelworkflow-*.dist-info under the app root and _internal, before copying current files. The helper probes --check-runtime --expected-version after Setup. CI installs twice on a disposable runner, verifies previous directory reuse, metadata cleanup, executable replacement, stable shortcut and unchanged data. [Inno InstallDelete](https://jrsoftware.org/ishelp/topic_installdeletesection.htm) executes before file installation.
