#!/usr/bin/env python3
"""Compare the filtered VMess nodes using repeated read-only application probes."""

from __future__ import annotations

import json
import os
import statistics
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from utils.proxy_selection import (
	filter_vmess_candidates,
	select_stable_candidate,
	valid_http_response,
	valid_login_response,
	valid_status_response,
)


def _controller_request(url: str, *, payload: dict | None = None) -> dict:
	data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode('utf-8')
	headers = {'Content-Type': 'application/json'} if data is not None else {}
	request = urllib.request.Request(url, data=data, headers=headers, method='GET' if data is None else 'PUT')
	try:
		with urllib.request.urlopen(request, timeout=5) as response:
			content = response.read()
			if not content and data is not None:
				return {}
			return json.loads(content.decode('utf-8'))
	except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
		raise RuntimeError('Mihomo controller request failed') from exc


def _request_probe(url: str, proxy_url: str, timeout: int) -> tuple[int, str, int]:
	opener = urllib.request.build_opener(urllib.request.ProxyHandler({'http': proxy_url, 'https': proxy_url}))
	request = urllib.request.Request(
		url,
		headers={
			'Accept': 'application/json, text/html;q=0.9, */*;q=0.8',
			'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36',
		},
	)
	started = time.monotonic()
	try:
		with opener.open(request, timeout=timeout) as response:
			status = response.status
			body = response.read(1_000_000).decode('utf-8', errors='replace')
	except urllib.error.HTTPError as exc:
		status = exc.code
		body = exc.read(1_000_000).decode('utf-8', errors='replace')
	except (urllib.error.URLError, TimeoutError, OSError, ValueError):
		status = 0
		body = ''
	latency_ms = max(1, round((time.monotonic() - started) * 1000))
	return status, body, latency_ms


def _probe_is_valid(mode: str, status: int, body: str) -> bool:
	if mode == 'status_json':
		return status == 200 and valid_status_response(body)
	if mode == 'login_page':
		return valid_login_response(status, body)
	return valid_http_response(status, body)


def main() -> int:
	if len(sys.argv) != 6:
		print('usage: probe_proxy_candidates.py PROVIDER_JSON CONTROLLER_URL PROXY_URL ROUNDS TIMEOUT', file=sys.stderr)
		return 2

	provider_path, controller_url, proxy_url, rounds_text, timeout_text = sys.argv[1:]
	try:
		rounds = int(rounds_text)
		timeout = int(timeout_text)
		provider_payload = json.loads(Path(provider_path).read_text(encoding='utf-8'))
		candidates = filter_vmess_candidates(provider_payload)
	except (OSError, ValueError, json.JSONDecodeError) as exc:
		print(f'[FAILED] Invalid filtered proxy provider: {exc}', file=sys.stderr)
		return 2
	if rounds < 1 or timeout < 1:
		print('[FAILED] Probe rounds and timeout must be positive integers', file=sys.stderr)
		return 2

	probe_urls = [os.getenv('PROXY_TEST_URL', 'https://www.google.com/generate_204')]
	probe_modes = [os.getenv('PROXY_TEST_MODE', 'http_2xx')]
	extra_url = os.getenv('PROXY_EXTRA_TEST_URL', '').strip()
	if extra_url:
		probe_urls.append(extra_url)
		probe_modes.append(os.getenv('PROXY_EXTRA_TEST_MODE', 'http_2xx'))
	if any(mode not in {'http_2xx', 'status_json', 'login_page'} for mode in probe_modes):
		print('[FAILED] Unsupported proxy probe mode', file=sys.stderr)
		return 2

	samples: dict[str, list[int]] = {name: [] for name in candidates}
	for index, name in enumerate(candidates, start=1):
		try:
			_controller_request(f'{controller_url}/proxies/CHECKIN', payload={'name': name})
		except RuntimeError:
			print(f'[WARN] Candidate {index}/{len(candidates)} could not be selected', file=sys.stderr)
			continue
		for round_number in range(1, rounds + 1):
			round_passed = True
			round_latency = 0
			for target_index, (url, mode) in enumerate(zip(probe_urls, probe_modes, strict=True), start=1):
				status, body, latency_ms = _request_probe(url, proxy_url, timeout)
				if not _probe_is_valid(mode, status, body):
					print(
						f'[INFO] Candidate {index}/{len(candidates)} probe {target_index}/{len(probe_urls)} '
						f'round {round_number}/{rounds} rejected (mode={mode}, code={status or 0})',
						file=sys.stderr,
					)
					round_passed = False
				else:
					round_latency += latency_ms
			if round_passed:
				samples[name].append(round_latency)
				print(
					f'[INFO] Candidate {index}/{len(candidates)} round {round_number}/{rounds} passed', file=sys.stderr
				)

	try:
		winner = select_stable_candidate(samples, min_samples=rounds)
	except ValueError:
		for index, name in enumerate(candidates, start=1):
			print(
				f'[INFO] Candidate {index}/{len(candidates)} stable rounds={len(samples[name])}/{rounds}',
				file=sys.stderr,
			)
		print('[FAILED] No VMess candidate passed every repeated endpoint check', file=sys.stderr)
		return 1

	latencies = samples[winner]
	result = {
		'name': winner,
		'median_ms': round(statistics.median(latencies)),
		'jitter_ms': max(latencies) - min(latencies),
		'rounds_passed': len(latencies),
	}
	print(
		f'[INFO] Candidate selected: {winner} (median={result["median_ms"]}ms, jitter={result["jitter_ms"]}ms)',
		file=sys.stderr,
	)
	print(json.dumps(result, ensure_ascii=False, separators=(',', ':')))
	return 0


if __name__ == '__main__':
	raise SystemExit(main())
