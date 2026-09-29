#!/bin/bash
# Run `ruff check --fix` after an agent edits a Python file in this repo.
#
# Worktree-portable: the repo root is derived from the edited file, not
# hard-coded, so this behaves correctly in every worktree wsx syncs it into.
# F401 (unused import) is left unfixable: agents edit in several steps and
# would otherwise lose an import they added but haven't used yet.
INPUT=$(cat)

read_field() { # read_field <python expression over `d`>
	printf '%s' "$INPUT" | python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
    a = d.get('toolArgs')
    if isinstance(a, str):
        a = json.loads(a)
    d['toolArgs'] = a if isinstance(a, dict) else {}
except Exception:
    raise SystemExit(0)
print($1 or '')
" 2>/dev/null
}

TOOL=$(read_field "d.get('toolName', '')")
[[ "$TOOL" =~ ^(edit_file|create_file|edit|create)$ ]] || exit 0

FILE=$(read_field "d['toolArgs'].get('path', '')")
[[ "$FILE" == *.py ]] || exit 0
[[ -f "$FILE" ]] || exit 0

ROOT=$(git -C "$(dirname "$FILE")" rev-parse --show-toplevel 2>/dev/null) || exit 0
case "$FILE" in
"$ROOT/"*) ;;
*) exit 0 ;;
esac

RUFF="$ROOT/.venv/bin/ruff"
[[ -x "$RUFF" ]] || RUFF=$(command -v ruff) || exit 0

cd "$ROOT" && "$RUFF" check --fix --unfixable F401 --exit-zero --quiet "$FILE" >/dev/null 2>&1 || true
