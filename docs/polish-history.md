# Polish History & Recovery

Version 3.10.0 adds a disk-backed snapshot service and a full utility page in
the existing shell. `NovelProfile.polish_history_step_id` enables exactly one
workflow step by stable ID; `None` explicitly disables it. Old documents without
this field auto-select only a unique explicit polish name, never a row index or
the default review step. Settings can select any custom step.

The named-stage button saves using the existing editor contract, selects the
step, then invokes snapshot creation before clipboard delivery. Work runs off
the UI thread with visible status; application close waits for an active job.
Other workflow steps retain their existing enabled-file and ZIP behavior.

## Storage and integrity

History must be inside an existing configured main novel folder. Since v3.10.1,
completed snapshots live directly in `Polish History/<step name>-บท <range>/`.
Changed versions add a local timestamp and numeric suffix if necessary; shared
main folders can add a readable profile name. Stable step/profile/snapshot IDs
remain in schema-1 metadata and identify ownership independently of directory names.
The v3.10.0 ID-container layout remains readable. Opening/refreshing History
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
enabled/order metadata, original paths/names, sizes, content hashes and Context
hash. Unknown schemas are displayed as unsupported without altering files.
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
before release. Upgrade CI starts from v3.10.0, downloads via the actual updater,
checks size/SHA-256 and validates legacy migration with the installed executable,
including unchanged raw manifest and payload hashes after migration.
The user's particular installed machine remains outside this automated test.
