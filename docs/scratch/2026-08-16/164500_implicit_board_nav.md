# Implicit Board landing (no top-nav item)

Signals-style: `/` is the landing; the brand mark is home. A **Board**
menu item is redundant because that is what `/` already is.

## Change

- `chrome.html`: drop `<a href="/">Board</a>`; keep Cognition + Terminal.
- Brand still `href="/"`.
- `GET /` still renders the board page (`active: "board"` unused in nav).
- Footer `board API` and `GET /api/gaius/v1/board` unchanged.

## Verify

```sh
curl -sS http://127.0.0.1:9890/ | grep -E 'class="nav"|href="/cognition"|href="/terminal"|Board'
```

Nav should list Cognition and Terminal only. Page `<h1>` may still say Board.
