# Polish History & Recovery

Version 3.11.0 adds pending-review capture to the disk-backed snapshot service and page in
the existing shell. `NovelProfile.polish_history_step_id` enables exactly one
workflow step by stable ID; `None` explicitly disables it. Old documents without
this field auto-select only a unique explicit polish name, never a row index or
the default review step. Settings can select any custom step.

The Novel Polish page displays the existing disk-backed sets for the current
novel. Translator Export captures pending-review snapshots under its existing
conditions; clicking a workflow stage copies its files without creating a
snapshot. Snapshot work runs off the UI thread with visible status, and the
application waits for an active job before closing. The ZIP choice on Novel
Polish is stored per novel, with the previous global preference used as the
fallback for existing profiles. Workflow copy preferences remain independent.

## Storage and integrity

History must be inside an existing configured main novel folder. Since v3.11.0,
completed snapshots live directly in `Polish History/<step name> บท <range>/`.
Changed versions add a local timestamp and numeric suffix if necessary; shared
main folders can add a readable profile name. Stable step/profile/snapshot IDs
remain in schema-1 metadata and identify ownership independently of directory names.
The v3.10.0 ID-container and v3.10.1 hyphenated layouts remain readable. Opening/refreshing History
validates metadata, ownership and every payload hash before an atomic move into
the flat layout, then validates again. Failed verification rolls back the move;
failed rollback keeps all data discoverable at its new location. Corrupt records
remain untouched. Clipboard references defer migration with a visible warning
and working Copy action. Only verified empty legacy containers are removed.
Payload files are streamed byte-for-byte without text normalization. Attachment
order, flags and duplicate links are retained in metadata; repeated source files
need only one payload copy. Folder trees retain their relative structure. Separate
attachment containers prevent duplicate basenames from overwriting each other.

SHA-256 is checked before and after streaming, across the complete source set,
and against the staged payload before publication. Folder membership is rechecked.
All payload/manifest writes are flushed before atomic staging-directory rename.
Symlinks/reparse points/junctions are rejected before directory traversal, and
project references and manifest payload paths require containment. No automatic
cleanup removes old or incomplete snapshots. Incomplete staging directories are
visible with an error and can be inspected through the secondary folder action.

Schema 1 manifests record identity, UTC time, chapter range, attachment links,
enabled/order metadata, original paths/names, sizes, content hashes, pending range,
review status and optional Context hash. Context is captured only when it is
explicitly attached to the configured step. Unknown schemas are displayed as unsupported without altering files.
Only unambiguous structural trailing commas can be recovered in a temporary
parsed copy; quoted text and the original raw manifest remain unchanged. Other
ambiguous JSON damage is reported. Payload, schema, types, counts and metadata
fingerprint are validated before delivery. Range edits preserve a metadata backup
and update the disk directory with the range. Payload bytes stay unchanged;
Clipboard references block renaming before either metadata or paths are changed.
Interrupted range renames are reconciled on the next verified History refresh.

## Chapter ranges and recovery

Range inference uses the existing Thai/English/Chinese heading reader only for
dynamic chapters, explicitly classified novel-content files, or Translator files.
Context is excluded even when attached; different inferred attachment ranges
require explicit user input. The compact workspace field accepts arbitrary
positive ranges, clears after success and is never populated from progress counters.
It is a user declaration when source files contain no verifiable chapter headings.

The `บันทึกไว้รอตรวจ` workspace action saves the configured step without
changing workflow selection or the clipboard. Each successful TXT Export also
creates a pending snapshot after export metadata is committed. A chapter range
is taken from exported content; if it cannot be verified, the item remains
`รอระบุช่วงบท` until the user assigns a range. Users may switch the status
between `รอตรวจ` and `ตรวจแล้ว` in the History menu. Neither action snapshots
files outside the configured step.

Translator Editor `Export` has a separate ordered transaction: it first asks for
confirmation, then snapshots the configured step and validates every payload.
The profile Context must already be attached to that step because Export replaces
it; the service never adds Context implicitly. Snapshot range comes from the
current Translator headings, or from a range the user enters when headings are
not conclusive. The Context payload therefore contains the exact pre-Export bytes.
Only after that snapshot and a second source/profile conflict check does the
existing atomic TXT/Context replacement run. Canceling creates no snapshot; a
snapshot failure leaves both TXT output and Context untouched; an Export failure
retains the verified snapshot and rolls the file transaction back. This button
does not use the clipboard or alter workflow selection, verified counters or TXT
Submit behavior.

History reads and verifies disk records after restart. Copy always uses the
selected snapshot and never writes Context, changes workflow selection, creates
export events or advances verified/TXT counters. ZIP mode uses the existing
persistent clipboard cache; ordinary mode publishes actual snapshot file URLs
through QMimeData. Published files survive app exit. A manual deletion is refused
while the current clipboard references snapshot payload paths.

## Validation

Unit/integration coverage includes lossless UTF-8/BOM/TSV/JSON/binary payloads,
all flags, external/dynamic/folder attachments, collisions, chapter inference,
deduplication, corruption, partial writes, permissions, traversal and source changes.
Real named-stage buttons, full-page copy/back navigation, profile settings and
post-close file existence are covered. Native Windows CF_HDROP/CF_UNICODETEXT,
four DPI scales in Light/Dark, full regression suite and installer-upgrade CI run
before release. Upgrade CI starts from v3.11.0, downloads via the actual updater,
checks size/SHA-256 and validates legacy migration with the installed executable,
including unchanged raw manifest and payload hashes after migration.
The user's particular installed machine remains outside this automated test.
# v3.12 history controls

Each complete snapshot has a permanent `history_number` displayed as `[001]`. A per-profile `history_numbers.json` ledger reserves numbers before publication, remembers deleted IDs and prevents number reuse. Legacy snapshots are numbered by creation timestamp and stable ID without changing their folder names, payloads or hashes.

Compact rows expose Copy, Recycle and More. Recycle has no confirmation dialog and requires the modern Windows shell API; missing support or a failed operation preserves the row and reports the error. Ownership, containment, traversal, symlink/junction and clipboard checks apply before recycling. History operations share a lock to prevent concurrent writers and deletion from racing.

New clipboard payloads are independent copies in the persistent application cache. They preserve historical snapshot bytes and remain usable after recycling the source snapshot. Direct clipboard references created by older versions are still guarded and block deletion until another clipboard selection is made.

## v3.13.1 Context and review consistency

Display-only blank-line normalization in an open Context tab no longer blocks Translator Export or overwrites its old bytes before the verified History snapshot. Real unsaved edits and external disk changes remain blockers. New pre-Export snapshots identify `capture_reason: translator_pre_export`.

Review-step Copy and post-TXT-Export history creation prefer a verified pre-Export capture when reusing the same chapter range after Context changed. Explicit `บันทึกไว้รอตรวจ` remains available for deliberate new versions. ZIP keeps other steps' fresh attachments independently. Without an old capture, a matching Translator/Context cannot be falsely claimed as an old review snapshot.

## v3.13.2 revised snapshots and display order

Polish History list numbers are contiguous display positions, newest first. Removing any row shifts the displayed ordinals without rewriting stable snapshot IDs, `history_number`, file paths or manifests.

Editing any History payload outside the application intentionally invalidates its original SHA-256/size record. On Copy the UI now offers an explicit confirmation if the recorded error is specifically a payload hash/size mismatch. Confirmation validates the entire snapshot structure and file membership, preserves an exact pre-revision manifest backup (`manifest.<id>.bak`), updates only the changed payload size/hash and derived manifest fields, marks it pending review, validates again, and copies the accepted content. Missing or unexpected payloads, traversal, symlinks, tampered manifests and external file conflicts are not auto-repaired. Merely editing the linked live Context does not change existing History snapshots.

## v3.13.3 compact review row position

The chapter label stands alone at the left of each History row; the contiguous display ordinal (e.g. `[003]`) sits immediately to the left of Copy. The ordinal uses the existing theme palette for Light/Dark contrast and does not modify snapshot identities, manifest contents, deletion, copying, or History sorting.

## v3.13.4 larger History number badges

The History sequence number beside Copy uses a larger 12pt bold, 64px-wide, at least 34px-tall pill with theme-appropriate text contrast. The chapter title remains on the left. The number is a display ordinal and still closes gaps when history rows are deleted, without changing any stored Snapshot identities.

## v3.14.0 History sorting and compact action grouping

The History page defaults to the existing newest-first order. To switch to numerical sorting, explicitly choose `เลขบท: มาก → น้อย` or `เลขบท: น้อย → มาก`; the sort is numeric by the first chapter and then the final chapter. Unknown chapter ranges remain at the bottom. `จัดเรียงด้วยตัวเอง` exposes accessible Up/Down buttons, disabled while search is filtering to avoid moving the wrong item. A novel's sort mode and manual Snapshot-ID list are saved in application settings under its profile ID and restored on reopening. New manual-mode captures appear above retained custom positions.

Rows use the compact left cluster `1 บท 430 คัดลอก`, with time, file count and review status under the chapter. Delete and More remain at the far right. Visible ordinals restart from 1 in the selected display/search order and are not stored in manifests. Real chapter numbers, Snapshot IDs, Context, payloads, manifest hashes and directory names are not changed.
