# theta_sitrep called unknown service ThetaAgent

MCP used `client.call("ThetaAgent", "sitrep")`. The gRPC
dispatcher only knows `Gaius` / `ThetaSitrep`. Tool returned
`{"error":"Unknown service: ThetaAgent"}`; Qwen then emitted
an empty completion and grok reported no_visible_content.

All three Theta MCP calls now use `Gaius` / `ThetaSitrep` /
`ThetaConsolidate` / `ThetaConsolidationStats`.
