# SmartCrop PDF — Phase 1: Bug/Problem Status Cross-Check

Scope note: `model.py`, `app_window.py`, `panels.py`, `ui_build.py`, `ARCHITECTURE.md`, and
`SmartCrop_PDF_Specification.md` were listed as uploaded but their content wasn't inline in the
chat context — read directly from `/mnt/user-data/uploads/` instead. Nothing here is guessed from
the critique docs; every row was checked against the current source.

Confidence tags: [H]=high [M]=medium [L]=low, per your convention.

## 1. `bugs.txt`

| # | Report | Status | Evidence |
|---|---|---|---|
|9|Auto-detect second press broken|**Confirmed, root cause found** [H]|`model._finish_detect` sets `d.union = union_box(good or results.values())` from *this call's* `results` only — never merges with the accumulated `detect_cache`. Detecting selection A then B gives each its own union (by design — Test Spec explicitly wants "two page-sets, two patterns"). The real defect: a **third** detect call touching a page from group A recomputes `d.union` from whatever the *current* selection is and reshapes that one page via `_crop_rect`, while A's other already-applied pages keep their old (different-union) boxes — silently breaking the "one constant W×H" invariant across a group. Spec text is internally in tension here (see Ambiguity Q1 below) — this is a design decision, not a one-line fix.|
|11|Right-click magnifies|**Inconclusive** [M]|Traced `<Button-3>` → `canvas_view._right_click` → `cancel_drag()` → `model.cancel_drag()` → `refresh_all()` → `redraw()` → `fit_scale(...)`. No state mutation in that path affects `_scale` beyond the normal fit computation; wheel is confirmed page-only (no zoom binding anywhere). No reproducing code path found by static reading — bugs.txt itself says "needs live testing," and I can't run the Tk GUI here. Needs your live confirmation (Q9).|
|14|Blinking segmented buttons|**Half-fixed** [H]|The *re-entrant dispatch* half is fixed: `_refresh_pages`/`_refresh_split` suppress `command=` during programmatic `.set()` (marked `#14` in both). The *visual-flicker* half is not: `set_active()` is called unconditionally on every `refresh()` — i.e. on every keypress/click anywhere in the app — for `btn_current`, `btn_dewarp`, `btn_bw`, `btn_sharpen`, and all 3 strength buttons, regardless of whether their active state changed. Matches critique #22 exactly. **Will fix**: make `set_active` a no-op when state is unchanged.|
|—|"Offset for bottom partially visible / or smaller than other"|**Plausible layout bug, needs a decision** [M]|4 offset spinners (`label width=16` + `entry width=52`, ~70-75px each incl. padding) pack side-by-left in one row inside a 320px panel (`PANEL_WIDTH`) with 12px card padding each side. Available width ≈ 296px vs. ≈290-300px needed for 4 — borderline, plausibly clips the last (B) spinner depending on CTk's internal widget padding. Needs a layout decision (Q7).|
|—|"No -- between app name and file name"|**Can't act on this as written** [M]|Current title is `f"SmartCrop PDF — {name}"` — already a single em-dash (`—`), not two hyphens (`--`). Either this was already fixed and the note is stale, or "no --" means something else (no separator at all? a different character?). Need your intent (Q8).|

## 2. Cross-check of the two prior critique documents against current code

### Document A (the "revised Bug 9/10/11/14/15" note)

| Claim | Verdict |
|---|---|
|Bug 9 retraction + sharper theory (union is call-scoped, not accumulated)|**Confirmed correct** [H] — see bugs.txt #9 above.|
|Bug 10 (no timing/perf tests)|**Confirmed** [H] — no timing assertions anywhere in the suite; can't be ruled in or out by tests.|
|Bug 11 (`fit_scale` overflow test doesn't check magnification)|**Confirmed** [H] — `test_fit_scale_never_overflows_the_window` only asserts `pw*s <= cw-margin`, which holds by construction of `min(...)` regardless of `s > 1`. No test anywhere asserts `s <= 1.0`. `fit_scale` itself: `min((canvas_w-margin)/content_w, (canvas_h-margin)/content_h)` — this **can exceed 1.0** on a canvas larger than the page, which would enlarge (not just fit) the page. Real gap, not yet decided whether it's also a real behavior bug (Q10).|
|Bug 14 (unconfirmed re: `set_active`)|**Now confirmed** [H] — see bugs.txt #14 above; the doc's uncertainty is resolved by reading `panels.py` directly.|
|Bug 15 (`delete_pages` never touches `current_follow`)|**Confirmed** [H] — `delete_pages` reindexes `detect_cache/processed/applied/rotation` but never reads or writes `current_follow`/`select_pattern`. If Current-follow is ON and the followed page shifts index after a delete, the pattern goes stale. No test covers this combination. Needs a decision on the intended behavior (Q6).|
|`History.set_depth` not trimming `_redo`|**Confirmed** [H] — will fix (unambiguous).|
|`parse_page_expr` "tested but production-unused"|**Confirmed** [M] — full unit coverage in `test_parsing.py::TestParsePageExpr`, zero call sites in `model.py` (which only imports `pages_for_mode`, which calls `_colon_slice`/`parse_selection`, never `parse_page_expr`). Needs a decision: delete, or wire it in somewhere (Q11).|
|`_is_typing_target` relying on `tk.Entry`|**Confirmed** [H] — `isinstance(self.root.focus_get(), tk.Entry)`; every entry in the app is `ctk.CTkEntry`, and this only works because CTk happens to hand focus to an internal raw `tk.Entry`. `test_app.py`'s own fixture docstring names this fragility and works around it by reaching into `entry_page._entry`.|
|`set_offset`/`commit_offsets`/live `AutoDrag` bypass Undo|**Real, but not as simple as "just add push()"** [M] — see below.|

### Document B (the numbered code-review list, #1–#30)

All 30 items were checked against the live files. Status:

| # | File | Verdict |
|---|---|---|
|1|geometry.hit_handle|**Confirmed** [H] — iteration order is `NW,N,NE,E,SE,S,SW,W`; `S` (edge, idx 5) precedes `SW` (corner, idx 6), so a point ambiguous between them resolves to the edge, contradicting the docstring's "corners win." **Will fix**: reorder to corners-first.|
|2|geometry — tiny-page guard|Confirmed absent, but genuinely low severity/low likelihood (pages are never below a few points). Deferred — see Q12 (bundled low-priority items).|
|3|Box not frozen (snapshot relies on convention)|Confirmed as described. Structural, not a live bug (no code currently mutates a shared `Box` in place). Deferred to Q12.|
|4|`History.set_depth` doesn't trim `_redo`|**Confirmed** [H]. **Will fix.**|
|5|`parse_page_expr` dead code|Confirmed — see Document A row above (Q11).|
|6|`render.crop_to_box` rounds x0/x1 independently|**Confirmed** [L] — can produce off-by-one-px seams between adjacent split crops. **Will fix**: round width once.|
|7|`clean_document_bilevel(upscale=2.0)` default unused|**Confirmed** [L] — every call site (model.py ×2, all of test_imaging.py) passes `upscale=1.0` explicitly. **Will fix**: default → 1.0.|
|8|`_UNWARP_CACHE` dict-as-singleton|**Confirmed**, cosmetic [L]. **Will fix**: plain module-level `Optional`.|
|9|`LRUCache.__contains__` doesn't bump recency|**Confirmed** [L]. Checked every call site in `model.py`/tests — nothing currently does `x in cache` (`.get()`/`.pop()` only), so it's latent, not live. **Will fix defensively** since it's a one-line override.|
|10|`set_offset`/`commit_offsets` bypass History|**Re-verified against spec §13, more nuanced than "bug"** [M] — see below.|
|11|Inconsistent `set_*` sync/async contract|**Confirmed** [M] — `set_filter_mode`/`set_filter_strength` return a `BatchJob` (need `dispatch_job`), every other `set_*` is synchronous (needs `dispatch`), nothing in the name signals which. Naming/API-shape change — needs your call (Q13).|
|12|`set_filter_strength` forces a no-op `PageJob` through the async path|**Confirmed**, consequence of #11. Same question (Q13).|
|13|`delete_pages` doesn't touch `current_follow`|Same as Document A row above — Q6.|
|14|`_FMT_EXT` duplicates `EXPORT_FORMATS`|**Confirmed** [L] — `_FMT_EXT` keys are hand-duplicated from `core.constants.EXPORT_FORMATS` instead of derived from it. **Will fix**: derive `_FMT_EXT` from `EXPORT_FORMATS` mechanically (or vice versa) so one list is authoritative.|
|15|`_is_typing_target` on `tk.Entry`|Confirmed — Document A row above.|
|16|Inconsistent shortcut guarding|**Confirmed** [H] — `Ctrl+O`, `Ctrl+Enter`, `Ctrl+S`, `Ctrl±`, `Ctrl+0` bind directly with no `_guarded`/`_guarded_nav` wrapper; `Ctrl+Z`, `Ctrl+Y`, arrows, `PgUp/PgDn` are wrapped. No stated rule for which. Needs a decision (Q14).|
|17|`entry_page` missing `<FocusOut>`|**Confirmed** [H] — every other entry in the app (`entry_pattern`, `entry_ratio`, offset spinners, every Settings entry) binds both `<Return>` and `<FocusOut>`; `entry_page` binds only `<Return>`. **Will fix**: add the binding, same handler.|
|18|Settings/Help re-open without checking for an existing window|**Confirmed** [H] — `_open_settings`/`_open_help` unconditionally construct a new `CTkToplevel` every call, with no guard. **Will fix**: track the window, `lift()`/`focus_force()` if it still exists instead of rebuilding.|
|19|Wheel treats any delta as one page|**Confirmed**, low severity — trackpad/precision-wheel over-scrolling. Deferred to Q12.|
|20|No z-order for overlapping split rects in cursor hit-test|**Confirmed**, low severity (nothing currently prevents overlapping split rects, but users rarely construct them). Deferred to Q12.|
|21|`view_snapshot()` populates caches (side effect on a "pure query")|**Confirmed** [L] — true as described, harmless in practice, docstring-only inconsistency. Will fix the docstring wording, not the behavior (caching on read is fine; claiming purity is the actual error).|
|22|`set_active` unconditional reconfigure|Same as bugs.txt #14 above — **will fix**.|
|23|Segmented-button suppress/restore duplicated verbatim|**Confirmed** [L] — same 5-line pattern in `_refresh_pages` and `_refresh_split`. **Will fix**: factor into one helper in `ui_build.py`.|
|24|`update_export_fmt_btn` string-matches `"▾"` in child text|**Confirmed, and worse than described** [H] — `export_split_button` doesn't even return `fmt_btn`; the caller has *no* way to get a direct reference today, so the scan-by-substring is currently load-bearing, not just "could be simpler." **Will fix**: return `fmt_btn` from `export_split_button` as a 3rd tuple element; update the one call site in `panels.py`.|
|25|`Tooltip` — one real `CTkToplevel` per widget|**Confirmed** [H] — counted the call sites: 5 in `app_window.py`, ~20+ in `panels.py` (every button/entry/switch gets one). That's 25+ live hidden OS windows for the app's lifetime. **Will fix**: one shared tooltip `CTkToplevel` per root, reused/repositioned on hover.|
|26|No dirty-checking at the panel level|Same root cause as #22 — fixing `set_active` addresses the visible symptom; the general "always re-walk everything" pattern is intentional/simple-by-design elsewhere and low risk. Deferred to Q12.|
|27|`_draw_move_sign` magic numbers|**Confirmed** [L], purely cosmetic geometry constants. **Will fix**: name the multipliers as module constants.|
|28|Zero logging anywhere|**Confirmed** [M] — real gap for a desktop tool, but "add logging" is a scope decision, not a bug fix. Needs your call on scope (Q15).|
|29|Stale spec-section citations as sole justification|Confirmed as a documentation style point; addressed structurally by the Ambiguity/Spec-diff phases below, not a code fix.|
|30|No dedicated test files existed at review time|**Now moot** — the full `tests/` suite you've since uploaded covers exactly the "pure leaf" modules this flagged (`test_geometry.py`, `test_parsing.py`, `test_viewmodel.py`, `test_property.py`, etc.).|

## 3. Re-examined against the spec directly (changes the read on two items)

**`set_offset`/`commit_offsets`/`AutoDrag.end_drag` and Undo (Doc A & B #10).** Spec §13: *"A
snapshot is taken before every mutating op — crop (the applied map), draw, rotate, and
dewarp/filter — so Undo reverts all of them. The snapshot captures … offsets …"* Read literally,
the ops that **trigger** a snapshot are Apply/Draw/Rotate/Dewarp/Filter; offsets are listed as
*part of what gets captured whenever some other op snapshots*, not as their own undo-triggering
op. `document_state.py`'s docstring mirrors this wording exactly. So the current code (no push on
offset edit or drag-release) is **plausibly correct as specified**, not a clear bug — but it does
leave a real UX gap: after typing a new offset value and pressing Enter (a discrete "commit"
gesture, unlike a live drag), there's no way to undo just that edit. This needs a decision, not a
silent fix (Q2).

**`fit_scale` magnification (Doc A, Bug 11).** Spec doesn't state "never magnify" anywhere I can
cite yet — that phrase is from `canvas_view.py`'s own docstring ("fits the page to the window
(never magnified, never overflowing")). So this is a **code-vs-code-comment** contradiction
confirmed independent of the spec, and worth fixing regardless of the spec text (Q10 asks only
about the fix mechanics, not whether it's real).

## 4. New finding not in either prior document: three-way architecture drift

`ARCHITECTURE.md`'s own file map (§ near the top) describes a *target* layout that was never
actually built: `ui/panels/crop.py` + `pages.py` + `output.py` (vs. the single flat `ui/panels.py`
that exists), separate `ui/settings_window.py` / `help_window.py` / `widgets.py` / `theme.py` (vs.
the single `ui/ui_build.py` that holds all of them), and `ui/overlay.py` described as *"progress
overlay, driven by a BatchJob handle"* — but the actual `ui/overlay.py` is crop-rectangle/handle
drawing; the real progress overlay is `ProgressCard` inside `ui_build.py`. ARCHITECTURE.md itself
flags part of this: *"`docs/SmartCrop_PDF_Specification.md` §3 still describes the mixin layout…
not done pre-approval."* So there are **three** module maps in play (spec §3's older mixin
layout, ARCHITECTURE.md's proposed modular split, and the actual flatter code), and none of the
three agree. This belongs in the Phase-3 diff but is worth flagging now since it explains several
"where did this file go" confusions above. No action needed from you yet — full treatment comes in
the diff phase.

---
*End of Phase 1. Nothing above has been edited yet — see the chat message for the consolidated
question list. Once you answer, I'll apply every fix (the "will fix" items plus whatever you
decide on the open questions) in one pass, then move to the spec-diff / ambiguity phases.*
