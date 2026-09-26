import pytest

from utils.proxy_selection import (
	ALLOWED_PROXY_NAMES,
	filter_vmess_candidates,
	select_stable_candidate,
	valid_http_response,
	valid_login_response,
	valid_status_response,
)

HONG_KONG = 'RN-CF-香港入口'
LOS_ANGELES = 'RN-CF-洛杉矶入口'


def _proxy(name: str, proxy_type: str = 'vmess') -> dict[str, str]:
	return {'name': name, 'type': proxy_type}


def test_allowed_proxy_names_are_the_two_expected_vmess_nodes():
	assert ALLOWED_PROXY_NAMES == {HONG_KONG, LOS_ANGELES}


def test_filter_returns_only_the_two_allowed_vmess_candidates():
	payload = {
		'proxies': [
			_proxy('unrelated-vmess'),
			{'name': {'malformed': True}, 'type': 'vmess'},
			_proxy(HONG_KONG),
			_proxy('unrelated-vless', 'vless'),
			_proxy(LOS_ANGELES),
			_proxy('unrelated-hysteria', 'hysteria2'),
		]
	}

	candidates = filter_vmess_candidates(payload)

	assert set(candidates) == {HONG_KONG, LOS_ANGELES}
	assert len(candidates) == 2


@pytest.mark.parametrize(
	'payload',
	[
		{'proxies': [_proxy(HONG_KONG)]},
		{'proxies': [_proxy(HONG_KONG), _proxy(LOS_ANGELES, 'vless')]},
		{'proxies': [_proxy(HONG_KONG), _proxy(HONG_KONG), _proxy(LOS_ANGELES)]},
	],
	ids=['missing-allowed-name', 'wrong-protocol', 'duplicate-allowed-name'],
)
def test_filter_rejects_missing_wrong_protocol_or_duplicate_allowed_nodes(payload):
	with pytest.raises(ValueError):
		filter_vmess_candidates(payload)


def test_selection_rejects_candidate_with_too_few_successful_samples():
	samples = {
		'unstable': [5, None, 6, None],
		'stable': [30, 31, 32],
	}

	assert select_stable_candidate(samples, min_samples=3) == 'stable'


def test_selection_prefers_lower_median_latency():
	samples = {
		HONG_KONG: [20, 21, 22],
		LOS_ANGELES: [30, 31, 32],
	}

	assert select_stable_candidate(samples) == HONG_KONG


def test_selection_uses_jitter_to_break_median_latency_tie():
	samples = {
		HONG_KONG: [10, 20, 30],
		LOS_ANGELES: [17, 20, 23],
	}

	assert select_stable_candidate(samples) == LOS_ANGELES


def test_selection_uses_name_as_deterministic_final_tie_breaker():
	samples = {
		'zeta': [20, 21, 22],
		'alpha': [20, 21, 22],
	}

	assert select_stable_candidate(samples) == 'alpha'


def test_selection_fails_when_no_candidate_has_enough_successful_samples():
	samples = {
		'one-sample': [12, None, 14],
		'all-failed': [None, 0, -3],
	}

	with pytest.raises(ValueError):
		select_stable_candidate(samples, min_samples=3)


def test_status_probe_requires_success_and_data_object():
	assert valid_status_response('{"success":true,"data":{}}')
	assert not valid_status_response('{"success":false,"data":{}}')
	assert not valid_status_response('{"success":true,"data":null}')
	assert not valid_status_response('<html>challenge</html>')


def test_login_probe_accepts_app_shell_but_rejects_challenge_or_short_body():
	app_shell = '<html><div id="root"></div>' + ('x' * 220) + '</html>'
	challenge = '<html>CF_APP_WAF' + ('x' * 220) + '</html>'

	assert valid_login_response(200, app_shell)
	assert not valid_login_response(200, challenge)
	assert not valid_login_response(530, app_shell)
	assert not valid_login_response(200, '<html>login</html>')


@pytest.mark.parametrize(
	'challenge',
	[
		'<html><title>Just a moment...</title><div id="root"></div>' + ('x' * 220) + '</html>',
		'<html>Verify you are human<div id="root"></div>' + ('x' * 220) + '</html>',
		'<html>Enable JavaScript and cookies<div id="root"></div>' + ('x' * 220) + '</html>',
	],
)
def test_login_probe_rejects_common_browser_challenge_pages(challenge):
	assert not valid_login_response(200, challenge)


def test_generic_probe_rejects_non_2xx_and_waf_challenge():
	assert valid_http_response(204, '')
	assert valid_http_response(200, '{"success":true}')
	assert not valid_http_response(530, '')
	assert not valid_http_response(200, 'Access Verification')
