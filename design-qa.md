# Desktop settings visual QA

## Reference and capture
- Reference: user-provided ChatGPT Settings screenshot in this conversation (General page, 1278 × 1600 image).
- Implementation: `.dev/zn-api-final-qa.png`, captured from the isolated Leopard ZN source build at 2560 × 1600 monitor resolution.
- State: Settings → API & models; connection not configured; no secret entered or shown.
- The two images differ in page and aspect ratio, so this is a directional layout comparison rather than a pixel comparison.

## Findings
- The settings navigation uses grouped sections and a clear active state, following the reference hierarchy.
- API setup now uses a single-column form with provider, model ID, API address, and password field; content width is capped and aligned to the left edge of the main pane.
- At the final capture, the form card and fields fit within the visible pane. Lower actions require normal vertical scrolling.
- API secrets remain write-only; saved credentials are not rendered back into the field.
- General, background service, updates, compact mode, expanded conversation, and artifact workbench were not re-captured in this QA pass. Their final visual behavior is not verified here.

## Changes made during review
- Replaced the initial wide form layout with a single column.
- Added min/max width constraints after the first capture showed right-edge clipping.
- Aligned the settings content to the left with a smaller responsive gutter after a second capture showed excessive centered whitespace.

## Result
blocked

The API settings view is materially improved and its final screenshot no longer shows the earlier horizontal clipping. The remaining settings sections and the three chat/workbench states still need a fresh visual pass before this desktop redesign can be marked complete.