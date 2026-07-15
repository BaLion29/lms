{ pkgs ? import <nixpkgs> { } }:

pkgs.mkShell {
  name = "firnline-dev";

  packages = with pkgs; [
    python312
    uv
  ];

  shellHook = ''
    echo "firnline development environment"
    echo "run: uv sync && uv run pytest"
  '';
}
