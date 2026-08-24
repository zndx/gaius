# Thinking Completes are sized with the Qwen3.8-27B tokenizer

Qwen3.8-27B context is 262_144. 65_536 tokens stay empty for the next
inbound question. The remaining 196_608 is this Complete: evidence +
generation. Thinking traces count against `max_tokens`.

Count those tokens with `AutoTokenizer.from_pretrained("Qwen/Qwen3.8-27B")`,
not chars/3. Compaction (Ambient, Prospects, Publishing) uses the same
ceiling. HTTP read timeout scales with that output budget so a long
think is not killed at 420s.
