#!/usr/bin/env bash

set -euo pipefail

: "${DUDU_ACCESS_TOKEN:?请配置 DUDU_ACCESS_TOKEN}"
base_url="${DUDU_BASE_URL:-https://wududu.edu.kg}"
status_body="$(mktemp)"
checkin_body="$(mktemp)"
trap 'rm -f "$status_body" "$checkin_body"' EXIT

request() {
	local method="$1"
	local output="$2"
	local data_args=()
	if [[ "$method" == 'POST' ]]; then
		data_args=(--header 'Content-Type: application/json' --data '{}')
	fi
	curl \
		--silent \
		--show-error \
		--retry 2 \
		--retry-all-errors \
		--connect-timeout 15 \
		--max-time 45 \
		--request "$method" \
		--header "Authorization: Bearer ${DUDU_ACCESS_TOKEN}" \
		--header 'Accept: application/json, text/plain, */*' \
		--header 'User-Agent: dudu-checkin-github-actions' \
		"${data_args[@]}" \
		--output "$output" \
		--write-out '%{http_code}' \
		"${base_url}/api/user/checkin"
}

status_is_checked_in() {
	python3 - "$1" <<'PY'
import json
import sys

try:
	with open(sys.argv[1], encoding='utf-8') as handle:
		payload = json.load(handle)
	data = payload.get('data') or {}
	stats = data.get('stats') or {}
	checked = stats.get('checked_in_today') or data.get('checked_in_today')
	raise SystemExit(0 if payload.get('success') is True and checked is True else 1)
except (OSError, ValueError, TypeError):
	raise SystemExit(1)
PY
}

checkin_succeeded() {
	python3 - "$1" <<'PY'
import json
import sys

try:
	with open(sys.argv[1], encoding='utf-8') as handle:
		payload = json.load(handle)
	message = str(payload.get('message') or payload.get('msg') or '').lower()
	already = ('already checked', 'already signed', '已签到', '重复签到')
	ok = (
		payload.get('success') is True
		or payload.get('ret') == 1
		or payload.get('code') == 0
		or any(marker in message for marker in already)
	)
	raise SystemExit(0 if ok else 1)
except (OSError, ValueError, TypeError):
	raise SystemExit(1)
PY
}

status_code="$(request GET "$status_body")"
if [[ ! "$status_code" =~ ^2[0-9][0-9]$ ]]; then
	echo "dudu 状态查询失败，HTTP ${status_code}"
	cat "$status_body"
	exit 1
fi

if status_is_checked_in "$status_body"; then
	echo 'dudu 今日已签到，跳过重复请求'
	exit 0
fi

checkin_code="$(request POST "$checkin_body")"
if [[ ! "$checkin_code" =~ ^2[0-9][0-9]$ ]]; then
	echo "dudu 签到请求失败，HTTP ${checkin_code}"
	cat "$checkin_body"
	exit 1
fi

if checkin_succeeded "$checkin_body"; then
	echo 'dudu 签到成功（或今日已签到）'
	exit 0
fi

echo 'dudu 签到返回未识别的失败结果'
cat "$checkin_body"
exit 1