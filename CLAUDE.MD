# CLAUDE.md — SmartCrop PDF (desktop)

## Source of truth
`docs/SmartCrop_PDF_Specification.md` is the behavioral contract. Code conforms to it, not
the reverse. Any behavior change requires updating the spec FIRST, then tests, then code —
in that order, with my sign-off on the spec diff before code changes start.

## Architecture rules (do not violate without flagging)
- Everything runs on the main thread (Tk/PyMuPDF requirement) — no threads/asyncio for
  PDF or Tk work.
- No upward imports: mixins/pure modules never import core.app.
- `core/render.py` is the ONE image path for both preview and export (WYSIWYG, §12.1) —
  never add a second rendering path.
- Tunables belong in core/constants.py — no magic numbers inline.

## Conventions
- One class (SmartCropApp) composed from mixins; keep each mixin file focused.
- Pure logic (geometry.py, viewmodel.py, parsing.py, imaging.py) stays Tk-free and
  unit-testable in isolation.
- `fitz` is PyMuPDF's import name — never let `pip install fitz` (wrong package) into
  the environment.

## Process
- Bug reports: diagnose root cause and report back before implementing a fix, when the
  cause is ambiguous between two plausible sites.
- After any fix: re-verify all acceptance invariants in spec §22, not just the one related
  to the bug.
- Don't rewrite spec/test prose unrelated to the change.

## Style
Senior-level, compact. No explanatory preamble in responses. Flag spec violations and
correctness issues directly; don't soften or hedge. State confidence on non-obvious
diagnoses.