# NovelWorkflow Persistent Workspace UX

## Goals
- Give core destinations stable locations in one desktop window.
- Keep novel workflow operations and copy-step behavior intact.
- Reduce dependence on dialogs for routine browsing and editing.
- Use the existing PySide6 stack and existing repository/data services.

## Approved direction
Use a compact, original dark productivity interface with persistent navigation and closable workspace tabs. The sidebar exposes Home, Novels, Groups, Files, Progress, and Settings. Home resumes the selected novel and shows concise progress. A novel workspace exposes overview, workflow, files, and launcher context without opening a separate management window.

## Interaction model
- Sidebar items open or activate one workspace tab per destination/resource.
- Resource tabs are keyed by stable profile/group identifiers to avoid duplicates.
- Home is fixed; other tabs can be closed.
- Files use a persistent list and inline text editor for TXT/MD/JSON, with Save and dirty state.
- Preview is read-only in a workspace and reuses AssemblyService.
- Groups, progress, settings, and launcher management are in-window pages.
- Dialogs remain for confirmation, OS pickers, and short focused inputs.

## Visual system
Keep the existing compact neutral theme and single accent. Strengthen hierarchy with a narrow navigation rail, selected state, practical list density, visible keyboard focus, and consistent page headings. Avoid gradients, decorative cards, and Discord branding.

## Preserved behavior
Keep profile ordering, Context synchronization, workflow step and file behavior, dynamic files, assembly, copy-to-clipboard and next-step cycling, group goals, translation statistics, launcher target behavior, chapter filename formatting, settings persistence, and existing data formats.

## Risks and safeguards
- Tab-local state can become stale after profile changes; refresh data on activation and retain editor text while dirty.
- File rename/delete must preserve reference update semantics and confirmation preference.
- Keep existing services as the source of business logic; limit changes to presentation and event wiring.
- Do not include executable builds, user novels, secrets, or API credentials in source commits.
