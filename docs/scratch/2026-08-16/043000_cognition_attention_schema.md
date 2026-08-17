# Where aperture admits are recorded (AST)

Three stores, one job each:

| Store | What | Not |
|-------|------|-----|
| Qdrant C (`gaius_prospects_aperture`, ambient C) | the lens | the harvest |
| Stream FIFOs + window metadata | the *act* of attention | the model of it |
| **Cognition Buffer** | Graziano attention *schema* | a 262k prose dump |

Cognition had no FIFO. It now has `cognition_buffer.CognitionBuffer`:
records (stream, code, margin, admit/suppress/review, excerpt pointer),
token-budgeted at 1/8 of Qwen3.8 context so Complete can *hold the
schema* and still work. Overwatch `hx_reasoning` is the social schema
(modeling our attention), not this RAM.
