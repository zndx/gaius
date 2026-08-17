# Terminal SSE: Grok requires chunk `id`

Ask progress ticks omitted `id`/`created`/`model`. Grok's
`ChatCompletionChunk.id` is required → “missing field `id`”.
Every SSE chunk now carries them. UI recycled; engine untouched.
