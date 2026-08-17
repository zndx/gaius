# Qwen XML tool calls were dumped as content

Engine/Complete is text-in/text-out. Qwen emitted
`<tool_call><function=list_files>…` in the completion body;
the façade returned `tool_calls: []`, so Grok printed the
markup instead of running tools.

The façade now parses those blocks (XML and JSON), aliases
`list_files` → `list_dir` (`target_directory`), and returns
OpenAI `tool_calls` with `finish_reason=tool_calls`.
