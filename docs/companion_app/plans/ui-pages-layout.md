# Companion App — UI Refactoring: Pages + Layout

## Context

The companion app UI evolved milestone by milestone. M2 established
`draw_shell()` (header + body placeholder), M3 wired connection-state
values into it, and M4 slapped `draw_status()` on top via an if-ladder
in `app.py`. The result works but has two structural problems:

1. **`Section` enum is misnamed.** The concept doc and MVP plan call
   these "top-level sections" (STATUS, DATA, INVENTORY, MAP) but the
   original Pip-Boy calls them pages or tabs, and the term "section"
   is overloaded with sub-units within a page. M5 will compound this
   by adding actual sub-sections inside DATA.

2. **No explicit layout abstraction.** `draw_shell()` dumps background
   fill, header text, separator, and body placeholder into one
   function. The per-frame rendering order (page content, CRT overlays,
   debug) is a comment-less sequence in `app.py`. Adding a footer in
   the future means threading another parameter through `draw_shell()`.

This ticket refactors the UI to fix both without changing behavior or
adding features. Pages become the top-level navigation concept, a
`Layout` class owns the screen chrome, and each page is a self-contained
renderable unit.

## Design

```
Layout (header + separator + content area + footer)
  └─ content area contains the active Page
       └─ Page contains one or more Sections (sub-components)

e.g. StatusPage:
  └─ HpSection (HP label + value)
```

### Mapping

| Current | Proposed |
|---|---|
| `Section` enum (STATUS=1..4) | `Page` enum (same values) |
| `SectionButtonEvent` | `PageButtonEvent` (rename) |
| `SectionButton(index)` in config keymap | `PageButton(index)` |
| `draw_shell()` in `ui/shell.py` | `Layout` class in `ui/layout.py` |
| `draw_status()` in `ui/status.py` | `StatusPage` in `ui/pages/status.py` |
| `draw_status()` `player_available` gating | Handled by page dispatch in `app.py` |
| If-ladder in `app.py:166-173` | Page dispatch: `current_page.render(...)` |
| `BODY_RECT` / `SEPARATOR_Y` constants in `shell.py` | `Layout.content_rect` property |

### Layout

```python
class Layout:
    def __init__(self, virtual_size: tuple[int, int]) -> None:
        # Pre-compute all rects once
        self._header_rect = ...
        self._content_rect = ...
        self._footer_rect = ...

    def draw(self, surface, page_name: str, connection_status: str) -> None:
        \"\"\"Render chrome: background, header, separator, footer area.\"\"\"

    def draw_placeholder(self, surface, text: str) -> None:
        \"\"\"Center `text` in the content area (for CONNECTING… / NO SIGNAL).\"\"\"

    @property
    def content_rect(self) -> pygame.Rect:
        return self._content_rect
```

Header draws page name (left) and connection status (right), matching
the current `draw_shell()` header exactly. The content area is an empty
rect waiting for the page to draw into it. The footer is a defined slot
but draws nothing (background fill only) until a consumer exists.

### Pages

```python
class Page(Enum):
    STATUS = 1
    DATA = 2
    INVENTORY = 3
    MAP = 4

# Protocol: each page implements:
def render(surface, content_rect, state: AppState) -> None: ...
```

Pages are notified which rect they own and draw within it. They do not
draw outside the content rect. Each page handles its own content when
`state.connection == READY and state.player.available == True`.

Three stub pages (DATA, INVENTORY, MAP) draw `"NOT YET IMPLEMENTED"`
centered in the content rect. The STATUS page draws HP / max HP.

### Page Dispatch (in `app.py`)

```python
# Before: if-ladder in the main loop
if state.connection is ConnectionState.READY and state.player.available:
    if current_section is Section.STATUS:
        draw_status(...)

# After: page dispatch
pages: dict[Page, PageRenderer] = {
    Page.STATUS: StatusPage(),
    Page.DATA: PlaceholderPage("NOT YET IMPLEMENTED"),
    Page.INVENTORY: PlaceholderPage("NOT YET IMPLEMENTED"),
    Page.MAP: PlaceholderPage("NOT YET IMPLEMENTED"),
}

layout = Layout((VIRTUAL_WIDTH, VIRTUAL_HEIGHT))

# Main loop:
layout.draw(virtual, current_page.name, connection_status)
if state.connection is ConnectionState.READY and state.player.available:
    pages[current_page].render(virtual, layout.content_rect, state)
else:
    layout.draw_placeholder(virtual, body_text)
```

This replaces `draw_shell()` and the STATUS if-ladder. The connection
state placeholders (`CONNECTING…`, `NO SIGNAL`) are now the layout's
responsibility, not the page's.

## File Changes

### New files
- `companion_app/companion_app/ui/layout.py` — `Layout` class
- `companion_app/companion_app/ui/pages/__init__.py` — `Page` enum
- `companion_app/companion_app/ui/pages/status.py` — `StatusPage`
- `companion_app/companion_app/ui/pages/data.py` — stub
- `companion_app/companion_app/ui/pages/inventory.py` — stub
- `companion_app/companion_app/ui/pages/map.py` — stub

### Modified files
- `companion_app/companion_app/ui/__init__.py` — update docstring
- `companion_app/companion_app/ui/shell.py` — remove `draw_shell()`,
  keep constants (`HEADER_SIZE`, `BODY_SIZE`, `BODY_RECT`) for
  backward compat with any module that imports them; mark as deprecated
- `companion_app/companion_app/ui/status.py` — delete (replaced by
  `ui/pages/status.py`)
- `companion_app/companion_app/input/events.py` — rename
  `SectionButtonEvent` → `PageButtonEvent`, update docstring and
  `_EVENT_FACTORIES` keys from `"SectionButtonN"` → `"PageButtonN"`
- `companion_app/companion_app/input/keyboard.py` — update docstring
  (references `SectionButtonEvent`)
- `companion_app/companion_app/app.py` — replace `Section` with
  `Page`, replace `draw_shell`/`draw_status` with `Layout` + page
  dispatch
- `companion_app/companion_app/config.py` — update `VALID_EVENT_NAMES`
  from `SectionButtonN` → `PageButtonN`
- `companion_app/config.example.json` — update key names

### Test files
- `companion_app/tests/test_shell.py` — update imports and test names
  to reference `Layout` instead of `draw_shell`
- `companion_app/tests/test_status.py` — update to test
  `ui.pages.status.StatusPage` instead of `ui.status.draw_status`
- `companion_app/tests/test_app.py` — update `Section` → `Page`
- `companion_app/tests/test_events.py` — update
  `SectionButtonEvent` → `PageButtonEvent`
- `companion_app/tests/test_keyboard.py` — same rename

## Key Decisions

1. **`SectionButtonEvent` renamed to `PageButtonEvent`.** The physical
   buttons are the same, but the internal concept is now "pages" not
   "sections." Renaming the event type keeps the code self-consistent.
   Config keymap entries change from `SectionButton1` → `PageButton1`
   etc. This is a one-time rename with no backward compat concern (the
   app has not shipped).

2. **`_body_text()` stays in `app.py`.** It now feeds
   `layout.draw_placeholder()` instead of `draw_shell(body_text=...)`.
   Same logic, same tests.

3. **`_connection_status()` stays in `app.py`.** Feeds
   `layout.draw()` for the header right column. Unchanged.

4. **Layout draws the background fill.** Previously `draw_shell()`
   owned the background. Now `Layout.draw()` does. Pages draw on top
   of the background in their content rect — they should NOT call
   `fill_background()` themselves.

5. **Footer is defined but empty.** `Layout` reserves a footer rect
   (e.g. 0 px height for now, or a small 24 px band at the bottom) and
   fills it with `BACKGROUND`. Nothing draws into it. This avoids a
   layout re-shuffle when the first footer content appears. If the
   empty footer feels wasteful, it can be collapsed to 0 px and grown
   later.

6. **`Page` enum lives in `ui/pages/__init__.py`**, not in `app.py`.
   It is a UI concern. `app.py` imports it.

7. **Pages are stateless renderers.** A page has no mutable state; it
   reads from `AppState` each frame. This keeps them simple and
   testable.

8. **`PlaceholderPage`** is a small internal class used for DATA,
   INVENTORY, and MAP until they get real content in M5.

## Out of Scope

- Any behavioral change to the STATUS section.
- Any behavioral change to connection lifecycle display.
- Adding footer content (future work).
- Adding the DATA sub-tab UX (M5).
- Adding real content to DATA, INVENTORY, or MAP (post-M5).
- Changing the `SectionButton` physical-input concept (the hardware
  still has section buttons; only the code-level event type is renamed).

## Acceptance Criteria

1. `python -m unittest discover -s tests` passes with 155+ tests
   (same coverage, updated for renames).
2. App starts and renders identically to the pre-refactor: header with
   `STATUS` + connection status, body with `CONNECTING…` / `NO SIGNAL`
   / HP display as appropriate, CRT overlays unchanged.
3. All connection states (`CONNECTING`, `OK`, `NO SIGNAL`,
   `RECONNECTING`) produce the same header and body text as before.
4. Section-button events (now `PageButtonEvent`) still switch the
   active page correctly.
5. Activating STATUS with a connected+available player shows HP data
   at the same coordinates as pre-refactor.
6. DATA, INVENTORY, and MAP show `"NOT YET IMPLEMENTED"` centered in
   the content rect (had no content before; this is a visible
   improvement).
7. Pressing a `PageButton`(2-4) while not `READY` still shows the
   connection placeholder (no crash).
8. No imports of `state/` or `net/` in `ui/layout.py` or
   `ui/pages/*.py`.
9. Exit via `q`, `Escape`, or window close returns code 0 with no
   traceback.
