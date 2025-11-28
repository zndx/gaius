{ pkgs, lib, config, inputs, ... }:

{

  dotenv.enable = true;
  cachix.enable = false;

  env.PATH_CONF = "conf";

  # https://devenv.sh/packages/
  packages = with pkgs; [
    cmake
    conftest
    d2
    git
    gh
    imagemagick
    jq
    mdbook
    mdbook-d2
    mdbook-katex
    mdbook-mermaid
    presenterm
  ];

  languages.python = {
    enable = true;
    package = pkgs.python312;
    uv.enable = true;
    uv.sync.enable = true;
    venv.enable = true;
  };

  tasks = {
    "docs:build".exec = "mdbook build docs";
    "docs:open".exec = "mdbook build docs --open";
  };
}

