#!/bin/sh
set -eu
allowed_root=/Users/ellis/Documents/CargoPPT/relay
allowed_url=https://github.com/ciby9833/ai-relay.git
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)
[ "$root" = "$allowed_root" ] || { echo '拒绝发布：仅允许指定的 relay 目录。' >&2; exit 1; }
cd "$root"
[ "$(git rev-parse --show-toplevel)" = "$allowed_root" ] || exit 1
[ "$(git remote get-url --push --all origin)" = "$allowed_url" ] || { echo '拒绝发布：origin 推送地址不符合白名单。' >&2; exit 1; }
[ "$(git branch --show-current)" = main ] || { echo '请在 main 分支发布。' >&2; exit 1; }
[ -z "$(git status --porcelain)" ] || { echo '请先检查并提交变更，然后发布。' >&2; exit 1; }
python3 scripts/check_release.py --history
git -c core.hooksPath=.githooks push -u origin main:main
