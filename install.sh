#!/usr/bin/env bash
# Instala o Reelay: o comando no PATH e a skill onde o Claude Code a enxerga.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="${REELAY_BIN_DIR:-$HOME/.local/bin}"
SKILL_DIR="${REELAY_SKILL_DIR:-$HOME/.claude/skills/reelay}"

echo "Reelay — installing"

missing=0
for tool in python3 yt-dlp ffmpeg ffprobe; do
  if command -v "$tool" >/dev/null 2>&1; then
    echo "  ok       $tool"
  else
    echo "  MISSING  $tool"
    missing=1
  fi
done

if [ "$missing" -ne 0 ]; then
  echo
  echo "Install the missing tools first:"
  echo "  brew install python yt-dlp ffmpeg"
  exit 1
fi

mkdir -p "$BIN_DIR"
ln -sf "$ROOT/bin/reelay" "$BIN_DIR/reelay"
echo "  linked   $BIN_DIR/reelay"

mkdir -p "$SKILL_DIR"
cp "$ROOT/skill/SKILL.md" "$SKILL_DIR/SKILL.md"
echo "  skill    $SKILL_DIR/SKILL.md"

case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *) echo; echo "  Add this to your shell profile:"; echo "    export PATH=\"$BIN_DIR:\$PATH\"" ;;
esac

echo
echo "Done. Try:  reelay --doctor"
