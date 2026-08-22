# Landing contract and YK extract floor

Short-term publish skipped two required features: treating
`article_curate` YK Blocked as terminal, and a 2-summary gate that
could omit LuxCore/local OW.

Card page (BDD `features/content/landing_cards.feature`):
- required: LuxCore image + local open-weights panel
- optional: Brave / Cerebras (API + budget). Cerebras falls back
  `qwen-3-32b` / `llama-3.3-70b` when `zai-glm-4.7` is archived.

YK: extract had guaranteed 0 GPU while thinking 4 + ask-sae 2 filled
the node. Article-curate Pending 60s, then STZ → `#YK.00000002.NOTADMITTED`.
Signals now floors extract at 1 GPU so YK preempts medium; Gaius waits
180s for that preemption instead of deleting the claim.
