# Guru Meditation Codes

Inspired by the Amiga's iconic error screens, every failure mode in Gaius gets a unique identifier — a Guru Meditation Code. These codes create a traceable link from error messages to diagnostics and remediation.

## Format

**`#<COMPONENT>.<SEQUENCE>.<MNEMONIC>`**

- **Component**: Two or three letter abbreviation for the subsystem
- **Sequence**: Zero-padded number unique within the component
- **Mnemonic**: Human-readable description of the failure mode

## Components

| Code | Component |
|------|-----------|
| DS | DatasetService |
| NF | NiFi |
| EN | Engine |
| EP | Endpoints/Inference |
| EV | Evolution |
| DB | Database |
| QD | Qdrant |
| GR | gRPC |
| ACP | Agent Client Protocol |
| ACF | Article Curation Flow |
| HL | Health |
| XB | X Bookmarks |
| SDG | Signals Data Governance (sdg-corpora + sdg-strategy) |
| KB | Knowledge base board / current_state |
| AG | Agenda consciousness zettels |
| SS | Server-to-server (Engine/ServerQuery remotes) |
| WS | Weekly Signals Summary |
| UI | gaius-ui (PTY, brand, Ask artifacts) |

## How They're Used

Every error message includes the guru code and remediation path:

```
DatasetService not initialized.
  Guru: #DS.00000001.SVCNOTINIT
  Try: /health fix dataset
  Or:  just restart-clean
```

## Design Rules

1. **One code per failure mode**: Each code maps to exactly one failure
2. **Unique across the system**: No two failure modes share a code
3. **Stable**: Codes are never renumbered once assigned
4. **Documented**: Each code has a KB heuristic with symptom, cause, and fix

## KB Heuristics

Each guru code has a corresponding heuristic document in the knowledge base at `build/dev/current/heuristics/gaius/<category>/<name>.md` containing:

- **Symptom**: What the user sees
- **Cause**: Root cause analysis
- **Observation**: How to detect programmatically
- **Solution**: Remediation steps, including `/health fix` command

See [Guru Meditation Codes Reference](../reference/guru-codes.md) for the complete catalog.
