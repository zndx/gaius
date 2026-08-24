# vLLM failures stay visible

Cognition+Theta health is thinking synthesis. Do not skip gpu_cleanup on
engine start (that hid thinking death after recycle). Ambient must ERROR
when thinking is not HEALTHY (`#AMB.00000014.NOHEALTHY`) — Try:
`/health fix endpoints` or `/gpu status thinking`. Health checker defaults
thinking to `:8081`, not optillm `:8082`.
