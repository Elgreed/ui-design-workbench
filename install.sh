#!/usr/bin/env sh
set -eu

agent="${1:-all}"
skill_name="ui-design-workbench"
source_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

install_link() {
  name=$1
  target=$2
  parent=$(dirname -- "$target")
  mkdir -p -- "$parent"
  if [ -e "$target" ] || [ -L "$target" ]; then
    resolved=$(CDPATH= cd -- "$target" 2>/dev/null && pwd || true)
    if [ "$resolved" = "$source_dir" ]; then
      printf '%s: already installed at %s\n' "$name" "$target"
      return
    fi
    printf '%s\n' "$name target already exists: $target. Move or remove it explicitly, then rerun the installer." >&2
    exit 2
  fi
  ln -s -- "$source_dir" "$target"
  printf '%s: installed at %s\n' "$name" "$target"
}

install_one() {
  case "$1" in
    agents) install_link agents "$HOME/.agents/skills/$skill_name" ;;
    codex) install_link codex "$HOME/.codex/skills/$skill_name" ;;
    claude) install_link claude "$HOME/.claude/skills/$skill_name" ;;
    cursor) install_link cursor "$HOME/.cursor/skills/$skill_name" ;;
    gemini) install_link gemini "$HOME/.gemini/skills/$skill_name" ;;
    copilot) install_link copilot "$HOME/.copilot/skills/$skill_name" ;;
    opencode) install_link opencode "$HOME/.config/opencode/skills/$skill_name" ;;
    *) printf 'Unknown agent: %s\n' "$1" >&2; exit 2 ;;
  esac
}

if [ "$agent" = all ]; then
  for name in agents codex claude cursor gemini copilot opencode; do install_one "$name"; done
else
  install_one "$agent"
fi

printf '%s\n' 'Done. Restart the selected agent or open a new session so it can rediscover the skill.'
