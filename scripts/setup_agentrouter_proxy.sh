#!/usr/bin/env bash
# AgentRouter selection uses its public status API and login/WAF page as probes.

set -euo pipefail

PROXY_TEST_URL="${PROXY_TEST_URL:-${PROXY_STATUS_URL:-https://agentrouter.org/api/status}}"
PROXY_TEST_MODE="${PROXY_TEST_MODE:-status_json}"
PROXY_EXTRA_TEST_URL="${PROXY_EXTRA_TEST_URL:-https://agentrouter.org/login}"
PROXY_EXTRA_TEST_MODE="${PROXY_EXTRA_TEST_MODE:-login_page}"
export PROXY_TEST_URL PROXY_TEST_MODE PROXY_EXTRA_TEST_URL PROXY_EXTRA_TEST_MODE

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec bash "${SCRIPT_DIR}/setup_mihomo_proxy.sh"
