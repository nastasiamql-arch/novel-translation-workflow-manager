# Changelog

All notable changes to Palantir: Novel are documented here.

## 3.0.1 - 2026-10-04

- Improve readability across light and dark themes with clearer text, stronger control borders, solid surfaces, and larger interface text.
- Keep progress values beside their bars and make update progress text remain legible.
- Make editor text wrap to the available width and change search matches to subtle underlines with a distinct active result.

## 3.0.0 - 2026-10-03

- Remove the standalone web novel Downloader and its adapters, library, configuration, installer, updater path, and related workflow integration.
- Keep Palantir: Novel focused on translation workflows and existing source, translated, and reviewed chapter references.

## 2.4.0 - 2026-10-03

- Migrate old profile documents additively and preserve unrecognized legacy fields.

## 2.3.2

- Add a confirmed **ยกเลิกเป้าหมายทั้งหมด** action to clear goal targets across every novel while keeping chapter history and daily activity.

## 2.3.1

- Refresh an open Context editor tab immediately after Submit and cancel stale Auto Save for the replaced text.
- Show an on-screen completion notification after a successful Submit.
- Rename the export number label to **เลขถัดไป** to clarify which number will be used next.

## 2.3.0

- Add a **กำลังเช็กกับเว็บ** novel status and library category, with a count and a card label.
- Add a workspace action to move a novel into this category; use **กลับไปแปล** to move it back.

## 2.2.2

- Show a clear Submit success message with the exported filename and next export number.

## 2.2.1

- Combine TXT export and Context overwrite into a single **Submit** button.
- Stage both output files before replacing either destination, preserving existing files if staging fails.

## 2.2.0

- Add one-step **ส่งออก + อัปเดต Context** to write TXT Export text to the numbered TXT file and overwrite the current novel's Context file. The export number advances only when both writes succeed.

## 2.1.0

- Keep TXT Export filename, destination folder, number range, and current number independently for each novel profile. Existing profiles inherit the previous shared settings once when migrating.
- Remember editor tab order, including TXT Export, and restore the active tab when reopening the application.

## 2.0.0

- Restore vocabulary handling to the v1.12.0 file-based workflow step; remove AI vocabulary processing, provider/API settings, and the separate **เกลาศัพท์** mode. Legacy per-profile configuration is retained as inactive data, and source files are not deleted.

## 1.14.0

- Add a permanent TXT Export editor tab with UTF-8 export, rotating chapter numbers, copy actions, overwrite-on-export, and application-wide settings.
- Add a separate **เกลาศัพท์** workflow tool with independent files, profile migration, and workflow-template support.
- Stabilize CJK editor rendering by using one editor font family and default hinting; clarify active editor tabs in light and dark themes.
- Show the last chapter heading found in Context directly in the status bar, including ranges and Thai, Chinese, and English headings.
- Streamline verified in-app updates: after the user chooses **อัปเดตเลย**, save editor and application state and launch the installer without another prompt.

## 1.13.5

- Read headerless SEGGlossary text files without imposing a fixed field count or meaning; follow the selected prompts and preserve each row as provided. Use exact before/after row pairs to safely update repeated source terms in different contexts.

## 1.13.4

- Identify which vocabulary input failed during snapshot reading (source, VOCAB, Extract prompt, or Polish prompt) and explain common missing-file, encoding, DOCX, TSV, and JSON issues without showing file contents or credentials.

## 1.13.3

- Continue checking supported MaxPlus pool endpoints when one returns a temporary 5xx response, and report a temporary provider outage clearly if none responds.
- Show a readable connection hint for HTTP 401/403 and temporary HTTP 5xx responses; the saved-key placeholder remains explicit.

## 1.13.2

- Report which vocabulary pipeline phase failed, with safe guidance for API HTTP statuses and common file/validation failures. Never display prompt, source, model response or API key contents.
- Accept the MaxPlus API root URL and auto-resolve the pool route allowed by the entered key while fetching model IDs; store the resolved endpoint on Save.

## 1.13.1

- Add a background **Connect and fetch model list** action to provider settings. It requests `/models` using the entered or Windows-protected API key, lets the user select a returned model or type one manually, and never saves a key until Save is pressed.
- Keep API errors sanitized and provider settings usable while model discovery runs; the worker clears its temporary key after completion.

## 1.13.0

- Add a compact, collapsible right-side vocabulary panel per novel. Remember source, VOCAB, extract/polish prompt files, provider, model and panel size independently.
- Run Extract → Polish → deterministic validation → byte-exact backup → atomic VOCAB replacement in a background thread; cancel before commit. Extraction never writes VOCAB.
- Read TXT/MD/JSON and DOCX prompts. Repair only JSON trailing commas outside strings in temporary copies; never rewrite prompt originals.
- Support headered UTF-8 TSV and JSON row arrays, full-row NEW/UPDATE changes, strict identities/columns, concurrent-change detection and cooperating-writer lock.
- Add HTTPS OpenAI-compatible and Anthropic provider adapters. Encrypt per-profile keys with current-user Windows DPAPI; redact provider errors and reject redirects.
- Migrate profile schema to v2 without modifying translation workflows. Support TSV editing; guard stale editor autosaves during vocabulary runs and reload afterwards.
- Keep installer AppId, self-updater and versioned release asset naming unchanged.

Uploaded prompts were not available in the referenced conversation's attachment list. This release uses the selected local prompts; it does not claim to embed or reproduce unavailable uploaded instructions.
