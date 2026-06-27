# HANDOFF — SmartCrop PDF bug-fix round

Last passing: **223 passed, 2 skipped** (`python -m pytest`, ~75s). 2 skips = docuwarp pair. pyflakes clean (bar intentional docuwarp probe in imaging.py).

## 10-item status
1. Overlay partial paint — DONE (`_show_progress` update_idletasks+update, ui_build.py).
2. Split=1 draw "jump" / cancel — PARTIAL: cancel gesture DONE (Esc/right-click `_cancel_drag`); cropped-view editing (option a) **BROKEN in real app** (see below).
3. Load resets all state — DONE (already true; test added).
4. Undo/Redo/Reset placement — DONE (moved to pinned bottom card).
5. Constant W×H clamp→shift — DONE (`geometry.fit_box_keep_size`/`anchored_base`).
6. Layout vs §6 — DONE (Pages 2nd, Advanced card, Actions card, Export row).
7. Auto-detect re-runnable — DONE (draw-anytime model; Clear removed).
8. Label truncation — DONE (Settings rows size to content; menus widened).
9. Keep ratio split 2/4 — PARTIAL: ratio source fixed (`_active_ratio`) but control **in wrong place / disabled in split** (see below).
10. Remove "Clear" button — DONE (button + `clear_detect` deleted).

## Confirmed still-broken
A. **Mouse behavior, split=1 cropped-view editing** (item 2a). User reports the jump/magnify persists.
   - `core/canvas.py:107` `_on_press` — committed-page branch routes to `kind="crop-edit"` (no flip). May not match real interaction.
   - `core/canvas.py:155` `_press_auto` — clicking ANYWHERE inside a live (uncommitted) auto crop → `kind="auto-move"` (line 156); user expects a fresh rubber-band, not move. No distinct "move sign" hit region exists.
   - `core/canvas.py:304` `_commit_crop_edit` — maps band into committed box (tighten-only); unverified vs real coords.
   - UNRESOLVED: is the user running stale code? Verify via visible layout markers ("Load Files", "Compress Document", "Sharpen", Undo/Redo/Reset at bottom). Headless tests pass; needs real-app run.

B. **Keep Ratio in wrong card / disabled in split** (item 9).
   - `core/ui_build.py:244` `self.sw_ratio` — built inside `_build_detect_section` ("Detect Text Borders", labeled split=1).
   - `core/detect.py:233` `_set_detect_enabled` — disables `sw_ratio` + `ratio_entry` when split>1, so Keep ratio is unusable in split though §9.7 requires it. FIX: stop disabling sw_ratio/ratio_entry (or relocate the control out of the split=1 card). EDIT WAS NOT APPLIED.

## Other notes
- No known test failures/regressions; suite green at handoff.
- Items in §A/§B not yet covered by passing assertions for the real (interactive) behavior — headless tests can't exercise mouse coords/layout.
- Spec + test-spec updated for items 1-10; §22 has new invariant 24 (cancel drag).
- Nothing committed (working tree only).
