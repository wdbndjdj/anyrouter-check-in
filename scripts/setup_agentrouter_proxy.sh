#!/usr/bin/env bash
# Start a dedicated local Mihomo proxy and select a node that can reach AgentRouter
# without being redirected to an access-verification or slider page.
#
# Environment variables:
#   PROXY_SUBSCRIPTION_URL   Clash/Mihomo subscription URL (required to enable)
#   PROXY_NODE_URI           Single encrypted VMess URI (takes precedence)
#   PROXY_TEST_URL           AgentRouter login URL
#   PROXY_STATUS_URL         AgentRouter status API used to reject hijacked pages
#   PROXY_REQUIRED           Exit with status 1 when no safe node is found
#   PROXY_PORT               Local mixed proxy port (default: 7890)
#   PROXY_CONTROLLER_PORT    Local Mihomo controller port (default: 9091)
#   PROXY_MAX_CANDIDATES     Maximum number of nodes to inspect (default: 160)
#   PROXY_CANDIDATE_TIMEOUT  Per-request timeout in seconds (default: 12)

set -euo pipefail
umask 077

if [[ -z "${PROXY_NODE_URI:-}" && -z "${PROXY_SUBSCRIPTION_URL:-}" ]]; then
	echo "[FAILED] No proxy source configured"
	if [[ "${PROXY_REQUIRED:-false}" == "true" ]]; then
		exit 1
	fi
	exit 0
fi

PROXY_DIR="${RUNNER_TEMP:-/tmp}/checkin-proxy"
PROXY_PORT="${PROXY_PORT:-7890}"
PROXY_CONTROLLER_PORT="${PROXY_CONTROLLER_PORT:-9091}"
PROXY_TEST_URL="${PROXY_TEST_URL:-https://agentrouter.org/login}"
PROXY_STATUS_URL="${PROXY_STATUS_URL:-https://agentrouter.org/api/status}"
PROXY_MAX_CANDIDATES="${PROXY_MAX_CANDIDATES:-160}"
PROXY_CANDIDATE_TIMEOUT="${PROXY_CANDIDATE_TIMEOUT:-12}"
MIHOMO_VERSION="${MIHOMO_VERSION:-v1.19.0}"
PROXY_REQUIRED="${PROXY_REQUIRED:-false}"
CONTROLLER_URL="http://127.0.0.1:${PROXY_CONTROLLER_PORT}"
PROXY_URL="http://127.0.0.1:${PROXY_PORT}"

mkdir -p "${PROXY_DIR}"
cd "${PROXY_DIR}"

cleanup_failed_proxy() {
	if [[ -f mihomo.pid ]]; then
		kill "$(cat mihomo.pid)" 2>/dev/null || true
	fi
	rm -f agentrouter-node.txt config.yaml select.json provider.json candidates.tsv status-*.json login-*.html
}

fail_or_skip() {
	local message="$1"
	echo "[FAILED] ${message}"
	cleanup_failed_proxy
	if [[ "${PROXY_REQUIRED}" == "true" ]]; then
		exit 1
	fi
	exit 0
}

echo "[INFO] Downloading Mihomo ${MIHOMO_VERSION}..."
ARCHIVE="mihomo-linux-amd64-${MIHOMO_VERSION}.gz"
if ! curl --retry 3 --retry-delay 5 --retry-all-errors -fsSL -o "${ARCHIVE}" \
	"https://github.com/MetaCubeX/mihomo/releases/download/${MIHOMO_VERSION}/${ARCHIVE}"; then
	fail_or_skip "Failed to download Mihomo ${MIHOMO_VERSION}"
fi
gunzip -f "${ARCHIVE}"
chmod +x "mihomo-linux-amd64-${MIHOMO_VERSION}"
MIHOMO_BIN="${PROXY_DIR}/mihomo-linux-amd64-${MIHOMO_VERSION}"

if [[ -n "${PROXY_NODE_URI:-}" ]]; then
	echo "[INFO] Preparing encrypted single-node proxy provider..."
	if [[ "${#PROXY_NODE_URI}" -gt 16384 || "${PROXY_NODE_URI}" == *$'\n'* || "${PROXY_NODE_URI}" == *$'\r'* || "${PROXY_NODE_URI}" != vmess://* ]]; then
		fail_or_skip "Invalid encrypted VMess node configuration"
	fi
	printf '%s\n' "${PROXY_NODE_URI}" > agentrouter-node.txt
	chmod 600 agentrouter-node.txt
	unset PROXY_NODE_URI
else
	echo "[INFO] Downloading proxy subscription..."
	if ! curl --retry 3 --retry-delay 3 --retry-all-errors -fsSL \
		--max-time 60 -o agentrouter-node.txt "${PROXY_SUBSCRIPTION_URL}"; then
		fail_or_skip "Failed to download proxy subscription"
	fi
fi

cat > config.yaml <<EOF
mixed-port: ${PROXY_PORT}
external-controller: 127.0.0.1:${PROXY_CONTROLLER_PORT}
allow-lan: false
ipv6: false
mode: rule
log-level: warning
unified-delay: true

proxy-providers:
  agentrouter_node:
    type: file
    path: ./agentrouter-node.txt
    health-check:
      enable: true
      interval: 300
      timeout: 5000
      url: https://www.gstatic.com/generate_204

proxy-groups:
  - name: CHECKIN
    type: select
    use:
      - agentrouter_node

rules:
  - MATCH,CHECKIN
EOF

echo "[INFO] Validating Mihomo configuration..."
if ! "${MIHOMO_BIN}" -t -d "${PROXY_DIR}" -f config.yaml; then
	fail_or_skip "Mihomo rejected the generated configuration"
fi

echo "[INFO] Starting Mihomo on 127.0.0.1:${PROXY_PORT}..."
nohup "${MIHOMO_BIN}" -d "${PROXY_DIR}" -f config.yaml > mihomo.log 2>&1 &
echo $! > mihomo.pid

PROVIDER_JSON="${PROXY_DIR}/provider.json"
PROVIDER_READY=false
for attempt in $(seq 1 30); do
	if curl -fsS --max-time 3 \
		"${CONTROLLER_URL}/providers/proxies/agentrouter_node" -o "${PROVIDER_JSON}" && \
		python3 - "${PROVIDER_JSON}" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    proxies = json.load(handle).get("proxies", [])
valid = len(proxies) >= 1
raise SystemExit(0 if valid else 1)
PY
	then
		PROVIDER_READY=true
		break
	fi
	echo "[INFO] Waiting for subscription provider (${attempt}/30)..."
	sleep 2
done

if [[ "${PROVIDER_READY}" != "true" ]]; then
	tail -n 40 mihomo.log || true
	fail_or_skip "Subscription provider did not load"
fi

# Ask Mihomo to run its provider health check. A timeout here is harmless; the
# content-aware checks below remain authoritative.
curl -fsS --max-time 20 \
	"${CONTROLLER_URL}/providers/proxies/agentrouter_node/healthcheck" -o /dev/null 2>&1 || true
curl -fsS --max-time 5 \
	"${CONTROLLER_URL}/providers/proxies/agentrouter_node" -o "${PROVIDER_JSON}"

CANDIDATES_FILE="${PROXY_DIR}/candidates.tsv"
python3 - "${PROVIDER_JSON}" "${PROXY_MAX_CANDIDATES}" > "${CANDIDATES_FILE}" <<'PY'
import base64
import json
import sys

provider_path, max_candidates = sys.argv[1], int(sys.argv[2])
with open(provider_path, encoding="utf-8") as handle:
    proxies = json.load(handle).get("proxies", [])

preferred = {
    "VLESS": 0,
    "Trojan": 0,
    "VMess": 0,
    "Shadowsocks": 0,
    "AnyTLS": 0,
    "Hysteria2": 1,
    "Hysteria": 1,
    "Socks5": 2,
    "Http": 2,
}
rows = []
for index, proxy in enumerate(proxies):
    name = proxy.get("name")
    reported_type = str(proxy.get("type", "Unknown"))
    canonical_types = {item.lower(): item for item in preferred}
    proxy_type = canonical_types.get(reported_type.lower(), reported_type)
    if not name or proxy_type not in preferred:
        continue
    history = proxy.get("history") or []
    delays = [item.get("delay") for item in history if isinstance(item.get("delay"), int) and item.get("delay") > 0]
    delay = min(delays) if delays else 999999
    alive_rank = 0 if proxy.get("alive") is True else 1
    encoded_name = base64.b64encode(name.encode("utf-8")).decode("ascii")
    rows.append((preferred[proxy_type], alive_rank, delay, index, encoded_name, proxy_type))

rows.sort()
for _, alive_rank, delay, _, encoded_name, proxy_type in rows[:max_candidates]:
    print(f"{encoded_name}\t{proxy_type}\t{1 - alive_rank}\t{delay}")
PY

CANDIDATE_COUNT="$(wc -l < "${CANDIDATES_FILE}" | tr -d ' ')"
if [[ "${CANDIDATE_COUNT}" == "0" ]]; then
	fail_or_skip "No supported proxy nodes were found"
fi
echo "[INFO] Prepared ${CANDIDATE_COUNT} candidate nodes for AgentRouter-specific checks"

READY=false
ATTEMPT=0
while IFS=$'\t' read -r encoded_name proxy_type alive delay; do
	ATTEMPT=$((ATTEMPT + 1))
	NODE_NAME="$(printf '%s' "${encoded_name}" | base64 --decode)"
	python3 - "${NODE_NAME}" > select.json <<'PY'
import json
import sys

print(json.dumps({"name": sys.argv[1]}, ensure_ascii=False))
PY
	if ! curl -fsS --max-time 5 -X PUT -H 'Content-Type: application/json' \
		--data-binary @select.json "${CONTROLLER_URL}/proxies/CHECKIN" -o /dev/null; then
		echo "[WARN] Candidate ${ATTEMPT}/${CANDIDATE_COUNT} could not be selected"
		continue
	fi
	sleep 1

	STATUS_BODY="${PROXY_DIR}/status-${ATTEMPT}.json"
	STATUS_CODE="$(curl -sS -L --compressed -x "${PROXY_URL}" \
		--connect-timeout 5 --max-time "${PROXY_CANDIDATE_TIMEOUT}" \
		-o "${STATUS_BODY}" -w '%{http_code}' "${PROXY_STATUS_URL}" 2>/dev/null || true)"
	if [[ "${STATUS_CODE}" != "200" ]] || ! python3 - "${STATUS_BODY}" <<'PY'
import json
import sys

try:
    with open(sys.argv[1], encoding="utf-8") as handle:
        payload = json.load(handle)
except (OSError, UnicodeDecodeError, json.JSONDecodeError):
    raise SystemExit(1)
valid = payload.get("success") is True and isinstance(payload.get("data"), dict)
raise SystemExit(0 if valid else 1)
PY
	then
		echo "[INFO] Candidate ${ATTEMPT}/${CANDIDATE_COUNT} rejected by status API (type=${proxy_type}, code=${STATUS_CODE:-000})"
		continue
	fi

	LOGIN_BODY="${PROXY_DIR}/login-${ATTEMPT}.html"
	LOGIN_META="$(curl -sS -L --compressed -x "${PROXY_URL}" \
		--connect-timeout 5 --max-time "${PROXY_CANDIDATE_TIMEOUT}" \
		-o "${LOGIN_BODY}" -w '%{http_code}\t%{size_download}' "${PROXY_TEST_URL}" 2>/dev/null || true)"
	LOGIN_CODE="${LOGIN_META%%$'\t'*}"
	LOGIN_SIZE="${LOGIN_META##*$'\t'}"
	if [[ "${LOGIN_CODE}" != "200" ]] || ! python3 - "${LOGIN_BODY}" <<'PY'
import pathlib
import sys

try:
    text = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8", errors="ignore").lower()
except OSError:
    raise SystemExit(1)

blocked_markers = (
    "access verification",
    "slide to verify",
    "please slide",
    "cf_app_waf",
    "aliyun",
    "captcha",
    "人机验证",
    "滑动验证",
    "访问验证",
)
app_markers = ("id=\"root\"", "id='root'", "/assets/", "agentrouter", "login")
valid = len(text) >= 200 and not any(marker in text for marker in blocked_markers) and any(marker in text for marker in app_markers)
raise SystemExit(0 if valid else 1)
PY
	then
		echo "[INFO] Candidate ${ATTEMPT}/${CANDIDATE_COUNT} rejected by login-page verification (type=${proxy_type}, code=${LOGIN_CODE:-000}, bytes=${LOGIN_SIZE:-0})"
		continue
	fi

	echo "[SUCCESS] Selected AgentRouter-capable candidate ${ATTEMPT}/${CANDIDATE_COUNT} (type=${proxy_type}, delay=${delay}ms)"
	READY=true
	break
done < "${CANDIDATES_FILE}"

rm -f select.json status-*.json login-*.html

if [[ "${READY}" != "true" ]]; then
	tail -n 40 mihomo.log || true
	fail_or_skip "No candidate passed AgentRouter status and WAF checks"
fi

echo "[SUCCESS] Proxy is ready: ${PROXY_URL}"
echo "[INFO] Proxy is scoped to CHECKIN_PROXY_URL (browser/python only, not global HTTP_PROXY)"
if [[ -n "${GITHUB_ENV:-}" ]]; then
	echo "CHECKIN_PROXY_URL=${PROXY_URL}" >> "${GITHUB_ENV}"
fi
