# Web harness sandbox needs bubblewrap in devenv

`--sandbox workspace` re-execs `bwrap`. Without it grok refuses
to start (`#UI.00000002.NOBWRAP`). `devenv.nix` now includes
`pkgs.bubblewrap` so another checkout gets it. gaius-ui prepends
that binary's dir to the PTY PATH and fails fast if missing.
