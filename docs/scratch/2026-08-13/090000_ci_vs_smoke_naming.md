# CI vs smoke naming

**Date:** 2026-08-13

Elevated gates are CI (`*-ci` / `*.ci.*`). Smoke is one-off `./scripts/`
first-run feedback only.

Persisted:

- `~/.grok/rules/ci-vs-smoke.md` (federation-wide; Grok home rules)
- Gaius `CLAUDE.md` Testing Methodology + RASE import check wording
- `docs/current/src/development/testing.md`

Signals already had this in `CLAUDE.md` (2026-08-12 smoke→ci rename).
Legacy `*.smoke.*` CE/DAG aliases stay dual-mapped; do not rename in place.
