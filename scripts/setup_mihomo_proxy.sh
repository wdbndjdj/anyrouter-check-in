#!/usr/bin/env bash
# Fetch a subscription privately, restrict it to the two approved VMess nodes,
# and select the fastest candidate that passes repeated project probes.

set -euo pipefail
umask 077

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROXY_DIR="${RUNNER_TEMP:-/tmp}/checkin-proxy"
PROXY_PORT="${PROXY_PORT:-7890}"
PROXY_CONTROLLER_PORT="${PROXY_CONTROLLER_PORT:-9091}"
PROXY_TEST_URL="${PROXY_TEST_URL:-https://www.google.com/generate_204}"
PROXY_TEST_MODE="${PROXY_TEST_MODE:-http_2xx}"
PROXY_EXTRA_TEST_URL="${PROXY_EXTRA_TEST_URL:-}"
PROXY_EXTRA_TEST_MODE="${PROXY_EXTRA_TEST_MODE:-http_2xx}"
PROXY_CANDIDATE_TIMEOUT="${PROXY_CANDIDATE_TIMEOUT:-12}"
PROXY_VALIDATION_ROUNDS="${PROXY_VALIDATION_ROUNDS:-5}"
MIHOMO_VERSION="${MIHOMO_VERSION:-v1.19.27}"
PROXY_REQUIRED="${PROXY_REQUIRED:-false}"
CONTROLLER_URL="http://127.0.0.1:${PROXY_CONTROLLER_PORT}"
PROXY_URL="http://127.0.0.1:${PROXY_PORT}"

cleanup_proxy() {
	if [[ -f "${PROXY_DIR}/mihomo.pid" ]]; then
		kill "$(cat "${PROXY_DIR}/mihomo.pid")" 2>/dev/null || true
		rm -f "${PROXY_DIR}/mihomo.pid"
	fi
	rm -f "${PROXY_DIR}/config.yaml" "${PROXY_DIR}/subscription.yaml" \
		"${PROXY_DIR}/subscription-download.err" "${PROXY_DIR}/provider.json" \
		"${PROXY_DIR}/probe-results.json" "${PROXY_DIR}/selected.json" \
		"${PROXY_DIR}/select.json" "${PROXY_DIR}"/probe-*.body \
		"${PROXY_DIR}/mihomo.log" \
		"${PROXY_DIR}/mihomo-linux-amd64-${MIHOMO_VERSION}" \
		"${PROXY_DIR}/mihomo-linux-amd64-${MIHOMO_VERSION}.gz"
}

fail_or_skip() {
	echo "[FAILED] $1"
	cleanup_proxy
	if [[ "${PROXY_REQUIRED}" == "true" ]]; then
		exit 1
	fi
	echo "[INFO] Proxy is optional for this workflow; no proxy endpoint was exported"
	exit 0
}

if [[ -z "${PROXY_SUBSCRIPTION_URL:-}" ]]; then
	if [[ "${PROXY_REQUIRED}" == "true" ]]; then
		fail_or_skip "PROXY_SUBSCRIPTION_URL is required but not configured"
	fi
	echo "[INFO] PROXY_SUBSCRIPTION_URL not set; skip proxy setup"
	exit 0
fi

if ! [[ "${PROXY_VALIDATION_ROUNDS}" =~ ^[1-9][0-9]*$ ]] || (( PROXY_VALIDATION_ROUNDS > 10 )); then
	fail_or_skip "PROXY_VALIDATION_ROUNDS must be an integer from 1 to 10"
fi

mkdir -p -m 700 "${PROXY_DIR}"
chmod 700 "${PROXY_DIR}"
cd "${PROXY_DIR}"

echo "[INFO] Downloading Mihomo ${MIHOMO_VERSION}..."
ARCHIVE="mihomo-linux-amd64-${MIHOMO_VERSION}.gz"
if ! curl --retry 3 --retry-delay 5 --retry-all-errors -fsSL -o "${ARCHIVE}" \
	"https://github.com/MetaCubeX/mihomo/releases/download/${MIHOMO_VERSION}/${ARCHIVE}"; then
	fail_or_skip "Failed to download Mihomo ${MIHOMO_VERSION}"
fi
gunzip -f "${ARCHIVE}"
chmod 700 "mihomo-linux-amd64-${MIHOMO_VERSION}"
MIHOMO_BIN="${PROXY_DIR}/mihomo-linux-amd64-${MIHOMO_VERSION}"

echo "[INFO] Downloading proxy subscription with Mihomo-compatible headers..."
if ! curl --retry 3 --retry-delay 3 --retry-all-errors -fsSL --compressed \
	--max-time 60 \
	-H "User-Agent: mihomo/${MIHOMO_VERSION#v}" \
	-H 'Accept: application/yaml, text/yaml, */*' \
	-o subscription.yaml "${PROXY_SUBSCRIPTION_URL}" 2>subscription-download.err; then
	rm -f subscription.yaml
	fail_or_skip "Failed to download proxy subscription"
fi
chmod 600 subscription.yaml
rm -f subscription-download.err

cat > config.yaml <<EOF
mixed-port: ${PROXY_PORT}
external-controller: 127.0.0.1:${PROXY_CONTROLLER_PORT}
allow-lan: false
ipv6: false
mode: rule
log-level: warning
unified-delay: true

proxy-providers:
  subscription:
    type: file
    path: ./subscription.yaml
    interval: 3600

proxy-groups:
  - name: CHECKIN
    type: select
    use:
      - subscription

rules:
  - MATCH,CHECKIN
EOF
chmod 600 config.yaml

echo "[INFO] Validating Mihomo configuration..."
if ! "${MIHOMO_BIN}" -t -d "${PROXY_DIR}" -f config.yaml >/dev/null 2>&1; then
	fail_or_skip "Mihomo rejected the generated configuration or subscription"
fi

echo "[INFO] Starting Mihomo on 127.0.0.1:${PROXY_PORT}..."
nohup "${MIHOMO_BIN}" -d "${PROXY_DIR}" -f config.yaml > mihomo.log 2>&1 &
echo $! > mihomo.pid
chmod 600 mihomo.pid mihomo.log

PROVIDER_JSON="${PROXY_DIR}/provider.json"
PROVIDER_READY=false
for attempt in $(seq 1 30); do
	if curl -fsS --max-time 3 "${CONTROLLER_URL}/providers/proxies/subscription" -o "${PROVIDER_JSON}" && \
		python3 - "${PROVIDER_JSON}" >/dev/null 2>&1 <<'PY'
import json
import sys

try:
    with open(sys.argv[1], encoding='utf-8') as handle:
        proxies = json.load(handle).get('proxies')
except (OSError, UnicodeDecodeError, json.JSONDecodeError):
    raise SystemExit(1)
raise SystemExit(0 if isinstance(proxies, list) and proxies else 1)
PY
	then
		PROVIDER_READY=true
		break
	fi
	echo "[INFO] Waiting for subscription provider nodes (${attempt}/30)..."
	sleep 2
done

if [[ "${PROVIDER_READY}" != "true" ]]; then
	fail_or_skip "The subscription provider did not load any proxy nodes"
fi
chmod 600 "${PROVIDER_JSON}"

if ! PYTHONPATH="${REPO_ROOT}" python3 - "${PROVIDER_JSON}" <<'PY'
import json
import sys
from collections.abc import Mapping

from utils.proxy_selection import ALLOWED_PROXY_NAMES, filter_vmess_candidates

try:
    with open(sys.argv[1], encoding='utf-8') as handle:
        payload = json.load(handle)
    proxies = payload.get('proxies', [])
    if not isinstance(proxies, list):
        raise ValueError('Mihomo provider response has no proxy list')
    allowed = {
        proxy.get('name')
        for proxy in proxies
        if isinstance(proxy, Mapping)
        and isinstance(proxy.get('name'), str)
        and proxy.get('name') in ALLOWED_PROXY_NAMES
    }
    vmess = {
        proxy.get('name')
        for proxy in proxies
        if isinstance(proxy, Mapping)
        and isinstance(proxy.get('name'), str)
        and proxy.get('name') in ALLOWED_PROXY_NAMES
        and str(proxy.get('type', '')).casefold() == 'vmess'
    }
    print(
        f'[INFO] Provider loaded {len(proxies)} nodes; '
        f'approved labels={len(allowed)}/2, VMess matches={len(vmess)}/2'
    )
    filter_vmess_candidates(payload)
except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
    print(f'[FAILED] Approved VMess candidates are unavailable: {exc}')
    raise SystemExit(1)
PY
then
	fail_or_skip "The loaded subscription does not contain both approved VMess candidates"
fi

echo "[INFO] Comparing the two VMess candidates with ${PROXY_VALIDATION_ROUNDS} repeated endpoint probes..."
if ! PYTHONPATH="${REPO_ROOT}" python3 "${SCRIPT_DIR}/probe_proxy_candidates.py" \
	"${PROVIDER_JSON}" "${CONTROLLER_URL}" "${PROXY_URL}" \
	"${PROXY_VALIDATION_ROUNDS}" "${PROXY_CANDIDATE_TIMEOUT}" \
	> "${PROXY_DIR}/probe-results.json"; then
	fail_or_skip "No VMess candidate passed every repeated project endpoint check"
fi
chmod 600 "${PROXY_DIR}/probe-results.json"

WINNER="$(python3 - "${PROXY_DIR}/probe-results.json" <<'PY'
import json
import sys

with open(sys.argv[1], encoding='utf-8') as handle:
	print(json.load(handle)['name'])
PY
)"
MEDIAN_MS="$(python3 - "${PROXY_DIR}/probe-results.json" <<'PY'
import json
import sys

with open(sys.argv[1], encoding='utf-8') as handle:
	print(json.load(handle)['median_ms'])
PY
)"
JITTER_MS="$(python3 - "${PROXY_DIR}/probe-results.json" <<'PY'
import json
import sys

with open(sys.argv[1], encoding='utf-8') as handle:
	print(json.load(handle)['jitter_ms'])
PY
)"

python3 - "${WINNER}" > "${PROXY_DIR}/select.json" <<'PY'
import json
import sys

print(json.dumps({'name': sys.argv[1]}, ensure_ascii=False))
PY
if ! curl -fsS --max-time 5 -X PUT -H 'Content-Type: application/json' \
	--data-binary @"${PROXY_DIR}/select.json" \
	"${CONTROLLER_URL}/proxies/CHECKIN" -o /dev/null; then
	fail_or_skip "Could not select the winning VMess candidate"
fi

echo "[SUCCESS] Selected ${WINNER} (median=${MEDIAN_MS}ms, jitter=${JITTER_MS}ms; ${PROXY_VALIDATION_ROUNDS}/${PROXY_VALIDATION_ROUNDS} rounds passed)"
echo "[SUCCESS] Proxy is ready: ${PROXY_URL}"
echo "[INFO] Proxy is scoped to CHECKIN_PROXY_URL (browser/python only, not global HTTP_PROXY)"
if [[ -n "${GITHUB_ENV:-}" ]]; then
	printf 'CHECKIN_PROXY_URL=%s\n' "${PROXY_URL}" >> "${GITHUB_ENV}"
fi
