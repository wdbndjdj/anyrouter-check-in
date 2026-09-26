"""Filter and rank the two approved VMess proxy candidates."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from statistics import median
from typing import Any

ALLOWED_PROXY_NAMES = frozenset({'RN-CF-香港入口', 'RN-CF-洛杉矶入口'})

_BLOCKED_MARKERS = (
	'access verification',
	'attention required',
	'just a moment',
	'verify you are human',
	'verify your browser',
	'enable javascript and cookies',
	'checking your browser',
	'challenge-platform',
	'cf-chl-',
	'slide to verify',
	'please slide',
	'cf_app_waf',
	'captcha',
	'人机验证',
	'滑动验证',
	'访问验证',
)
_APP_MARKERS = (
	'id="root"',
	"id='root'",
	'id="app"',
	"id='app'",
	'id="__next"',
	"id='__next'",
	'__next',
	'/assets/',
)


def filter_vmess_candidates(provider_payload: Mapping[str, Any]) -> list[str]:
	"""Require exactly the two screenshot VMess nodes and reject ambiguous feeds."""
	if not isinstance(provider_payload, Mapping):
		raise ValueError('Mihomo provider response must be an object')

	proxies = provider_payload.get('proxies')
	if not isinstance(proxies, list):
		raise ValueError('Mihomo provider response has no proxy list')

	found: dict[str, int] = {}
	for proxy in proxies:
		if not isinstance(proxy, Mapping):
			continue
		name = proxy.get('name')
		if not isinstance(name, str) or name not in ALLOWED_PROXY_NAMES:
			continue
		if name in found:
			raise ValueError(f'duplicate approved proxy candidate: {name}')
		if str(proxy.get('type', '')).casefold() != 'vmess':
			raise ValueError(f'approved proxy candidate is not VMess: {name}')
		found[name] = 1

	missing = ALLOWED_PROXY_NAMES.difference(found)
	if missing:
		raise ValueError('proxy subscription is missing an approved VMess candidate')
	return sorted(found)


def select_stable_candidate(latency_samples: Mapping[str, Sequence[int | None]], *, min_samples: int = 3) -> str:
	"""Pick the lowest-median candidate with all samples successful and stable."""
	if min_samples < 1:
		raise ValueError('min_samples must be at least 1')

	ranked: list[tuple[float, int, str]] = []
	for name, samples in latency_samples.items():
		if not isinstance(samples, Sequence) or isinstance(samples, (str, bytes)):
			continue
		if len(samples) < min_samples or not samples:
			continue
		if any(not isinstance(sample, int) or isinstance(sample, bool) or sample <= 0 for sample in samples):
			continue
		values = list(samples)
		ranked.append((median(values), max(values) - min(values), name))

	if not ranked:
		raise ValueError('no candidate passed every stability probe')
	return min(ranked)[2]


def valid_status_response(body: str) -> bool:
	"""Validate a public NewAPI status response without exposing its body."""
	try:
		payload = json.loads(body)
	except (TypeError, json.JSONDecodeError):
		return False
	return isinstance(payload, dict) and payload.get('success') is True and isinstance(payload.get('data'), dict)


def valid_login_response(status_code: int, body: str) -> bool:
	"""Accept the app login shell while rejecting known WAF/challenge pages."""
	text = body.lower()
	if status_code != 200 or len(text) < 200:
		return False
	return not any(marker in text for marker in _BLOCKED_MARKERS) and any(marker in text for marker in _APP_MARKERS)


def valid_http_response(status_code: int, body: str) -> bool:
	"""Accept successful HTTP probes while excluding common challenge pages."""
	if not 200 <= status_code < 300:
		return False
	text = body.lower()
	return not any(marker in text for marker in _BLOCKED_MARKERS)
