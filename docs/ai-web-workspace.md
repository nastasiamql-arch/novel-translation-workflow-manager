# AI Web Workspace — v5.10.0

This feature is intended for an **installed Google Chrome** and an existing Google account.
It does **not** use Gemini API keys, extract Google credentials, bypass sign-in challenges,
or guarantee that Google's frequently changing website will expose stable automation controls.

## Workflow

1. Open **AI Web Workspace** from the existing sidebar.
2. Select a novel, stage (vocabulary, translation, polish), and a source already bound to that stage.
3. Choose a chapter range, chapters per job, 1–10 maximum tabs, and normal-file or ZIP attachments.
4. Enter the name of a Gemini model **actually available on your signed-in webpage**. A different
   name can be assigned to a selected job before submission. Browser automation confirms it
   before attaching files; a failed confirmation must be handled in Chrome.
5. Preview and prepare bundles in the background. The original files are validated and
   remain unchanged. Start Chrome to attempt sequential sends (default gap: one second).
6. On a failed or uncertain job, open its original tab, resolve login/attachment/model issues,
   retry a definitely-unsent job, confirm a manual send, or manually import the raw answer.
   **Never retry a SEND_UNCONFIRMED job automatically.**
7. Responses are stored under the user's local NovelWorkflow profile, validated, and kept
   in original submission order. Unparseable responses remain available for manual review.
8. Translator import is guarded: it requires a completely validated translation batch and
   an **empty, uniquely bound Translator**. Existing Translator and Context export confirmation,
   backup, recovery journal and progress checks are preserved. Use the ordinary Export
   workflow if Translator already contains edited work.

## Recovery and privacy

Application data, per-novel AI job journals, staged attachments, and the persistent Chrome
profile are kept outside the installed application and GitHub repository. Never commit or
share the Chrome profile directory. A Google re-login may be required at any time. On an
unverifiable attachment, model, send or Copy state, the adapter deliberately stops that
job and preserves manual recovery instead of guessing.

## Acceptance scope

Automated tests validate job grouping, storage, ordering, parser boundaries, file bundles,
synthetic attachment DOM states, Qt smoke, installer upgrade, and published update pipeline.
These tests **do not** establish compatibility with the live signed-in Gemini website.
Live acceptance must be performed on an authorized signed-in Chrome session, separately
recording 1/3/10-job tests, model selection, slow uploads, clipboard copies, restart,
and import/export. Changes to Google's webpage may require an updated adapter.

The Chrome website workflow is best regarded as assisted automation with strict
fail-closed safety checks; no promise of service-wide unattended operation is made.
