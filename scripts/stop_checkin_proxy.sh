#!/usr/bin/env bash
set -euo pipefail

PROXY_DIR="${RUNNER_TEMP:-/tmp}/checkin-proxy"
PID_FILE="${PROXY_DIR}/mihomo.pid"

if [[ -f "${PID_FILE}" ]]; then
	echo "[INFO] Stopping mihomo proxy (pid $(cat "${PID_FILE}"))"
	kill "$(cat "${PID_FILE}")" 2>/dev/null || true
	rm -f "${PID_FILE}"
fi

rm -f \
	"${PROXY_DIR}/agentrouter-node.txt" \
	"${PROXY_DIR}/config.yaml" \
	"${PROXY_DIR}/subscription.yaml" \
	"${PROXY_DIR}/subscription-download.err" \
	"${PROXY_DIR}/select.json" \
	"${PROXY_DIR}/provider.json" \
	"${PROXY_DIR}/candidates.tsv" \
	"${PROXY_DIR}/probe-results.json" \
	"${PROXY_DIR}/selected.json" \
	"${PROXY_DIR}"/probe-*.body \
	"${PROXY_DIR}"/status-*.json \
	"${PROXY_DIR}"/login-*.html \
	"${PROXY_DIR}/mihomo.log" \
	"${PROXY_DIR}/mihomo-linux-amd64-*.gz" \
	"${PROXY_DIR}/mihomo-linux-amd64-v*"
