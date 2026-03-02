# AGENTS.md

## Project
- Name: `ics-edit`
- Main script: `remove-old-ics-entries.py`
- Purpose: Remove expired events from ICS files.

## Scope
- Keep the project minimal and script-first.
- Preserve existing CLI arguments and defaults unless explicitly changed.

## Language Policy
- Use English only for code comments, documentation, commit messages, issue text, and pull requests.
- Keep user-facing CLI text in English.
- This language policy applies even if the chat with the user is in another language.

## Coding Guidelines
- Use Python 3.
- Favor small, readable functions.
- Keep timezone behavior explicit and predictable.
- Do not introduce heavy dependencies without clear need.

## Safety
- Never commit personal calendar files (`*.ics`).
- Treat any local sample calendar data as private.
- Prefer writing output to a new file instead of in-place overwrite.

## Validation
- Verify `--help` output after CLI changes.
- Test with:
  - single past event
  - future event
  - recurring event with `UNTIL`
  - recurring event with `COUNT`
  - event without end limit
