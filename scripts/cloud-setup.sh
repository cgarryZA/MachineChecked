#!/usr/bin/env bash
# Setup of a Claude Code cloud environment (or any Ubuntu 24.04 machine) for ProofLens and the
# Lean projects it reads: elan with the toolchains they pin, TeX Live with latexmk, zstd for the
# Lean build cache, the Python package and the web app's dependencies. Idempotent; safe to run at every session start.
set -euo pipefail

export DEBIAN_FRONTEND=noninteractive
SUDO=""; [[ $(id -u) -ne 0 ]] && SUDO="sudo"

# TeX Live: enough for amsart/amsthm papers with hyperref, TikZ and biblatex.
if ! command -v latexmk >/dev/null || ! kpsewhich lmodern.sty >/dev/null 2>&1; then
  $SUDO apt-get update -qq
  $SUDO apt-get install -y -qq --no-install-recommends \
    latexmk texlive-latex-recommended texlive-latex-extra texlive-science \
    texlive-fonts-recommended texlive-bibtex-extra texlive-pictures biber lmodern cm-super >/dev/null
fi

# zstd: the Lean build cache compresses its archives with it.
if ! command -v zstd >/dev/null; then
  $SUDO apt-get update -qq
  $SUDO apt-get install -y -qq --no-install-recommends zstd >/dev/null
fi

# elan and the Lean toolchain of the toy paper (other projects' toolchains install on first use).
if [[ ! -x "$HOME/.elan/bin/lake" ]]; then
  curl -sSfL https://raw.githubusercontent.com/leanprover/elan/master/elan-init.sh -o /tmp/elan-init.sh
  sh /tmp/elan-init.sh -y --default-toolchain none >/dev/null
fi
export PATH="$HOME/.elan/bin:$PATH"
grep -q '.elan/bin' "$HOME/.bashrc" 2>/dev/null || echo 'export PATH="$HOME/.elan/bin:$PATH"' >> "$HOME/.bashrc"

REPO="${PROOFLENS_DIR:-$(cd "$(dirname "$0")/.." 2>/dev/null && pwd || echo /home/user/ProofLens)}"
if [[ -f "$REPO/examples/toy-paper/lean/lean-toolchain" ]]; then
  elan toolchain install "$(cat "$REPO/examples/toy-paper/lean/lean-toolchain")" >/dev/null 2>&1 || true
fi

# Python package (editable) and the web app.
if [[ -f "$REPO/pyproject.toml" ]]; then
  python3 -m pip install -q --break-system-packages -e "$REPO[test]" 2>/dev/null \
    || python3 -m pip install -q -e "$REPO[test]"
fi
if [[ -f "$REPO/web/package.json" ]] && command -v npm >/dev/null; then
  (cd "$REPO/web" && npm ci --no-audit --no-fund --silent)
fi
echo "prooflens setup: done"
