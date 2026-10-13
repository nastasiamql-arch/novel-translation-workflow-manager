# Confirmed Translator completion

`translator_export_events` is an additive profile field, separate from `verified_export_history` (TXT Submit) and the preserved `translation_daily_activity` (legacy Context scans). An event records its unique ID, profile ID, completion timestamp with local timezone/date, actual chapter numbers, newly confirmed numbers, source path/SHA-256, exported TXT and snapshot path, and committed status.

Chapter headings support Thai, English, Chinese and bilingual [A]/[B] markers. Explicit heading ranges expand into individual numbers; separate headings do not imply missing chapters. Global per-profile deduplication assigns each chapter only to its first successful Export day. A repeated event ID is idempotent; conflicting identity is rejected. Unverifiable chapter headings do not count, even if a manual range was entered for a history folder name.

All daily/weekly totals and translation goals derive from confirmed events. `translator_goal_baseline` is a lifetime unique-count checkpoint. Targets do not cap the displayed count or automatically reset. Reset changes only this checkpoint, never Export events or lifetime totals.

Profile schema 9 and progress schema 2 preserve existing Context fields and archive their provenance in `legacy_translation_progress`. Old activity remains viewable separately in Statistics. No historical chapters are inferred or imported from Context, default ChapterState, TXT Submit, or ambiguous last-export records.

Header, Library and Statistics share the same completion helpers. The header reports continuous completion only if every chapter from 1 is confirmed; otherwise it reports the most recent verified chapter set. Tooltip distinguishes total unique chapters, highest chapter and the continuous prefix. Context scanning still updates ChapterState for workflow references, independently of completed activity.

The existing pre-Export snapshot sequence is retained. After snapshot verification, TXT, Context, profile statistics and export status are staged and committed through the existing multi-file recovery function under the profile lock. A durable journal contains original rollback snapshots and intended destination hashes before any replacement; only a verified committed transaction can report success. These temporary rollback files are not additional Polish History snapshots.

On restart, prepared transactions roll back; committed transactions retain their results. Recovery validates ownership, path containment and symlinks/junctions. If a user has edited, moved or deleted a destination after the crash, recovery preserves every live file, original rollback snapshot and journal. The profile remains visible with its pre-transaction confirmed totals; profile writes and further Translator Export are blocked with a clear conflict message. Preserve external work separately and compare the live file with the journal's original/intended version before resolving the conflict; never discard the journal or recovery copies blindly.

The 10-second progress refresh also handles local date rollover without requiring a Context change. Upgrade installation keeps the application data namespace and installer identity unchanged.
