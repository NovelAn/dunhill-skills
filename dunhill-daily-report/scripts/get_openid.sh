#!/bin/zsh
# Usage: scripts/get_openid.sh 姓名  -> prints open_id (ou_...)

if [[ $# -ne 1 ]]; then
  echo "usage: scripts/get_openid.sh 姓名" >&2
  exit 1
fi

LARK_CLI="/Users/novel/.nvm/versions/node/v20.19.6/bin/lark-cli"
if [[ ! -x "$LARK_CLI" ]]; then
  LARK_CLI="$(command -v lark-cli)"
fi

result="$( "$LARK_CLI" contact +search-user --query "$1" --has-chatted --as user 2>/dev/null )"
if [[ $? -ne 0 ]]; then
  echo "lark-cli 查询失败（可能需要终端钥匙串权限）。请在一个普通终端窗口里重试。" >&2
  exit 1
fi

open_ids=( $( print -r -- "$result" | /usr/bin/grep -o 'ou_[a-f0-9]*' ) )

if [[ ${#open_ids[@]} -eq 0 ]]; then
  echo "未找到匹配的联系人: $1" >&2
  exit 1
fi

if [[ ${#open_ids[@]} -gt 1 ]]; then
  echo "匹配到多个人，请用更精确的姓名重试:" >&2
  print -r -- "$result" | /usr/bin/grep -E '"localized_name"|"open_id"|"department"'
  exit 1
fi

echo "${open_ids[1]}"
