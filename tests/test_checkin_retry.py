from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx

import checkin
from checkin import execute_check_in, get_check_in_retry_delays


def response(status_code: int, payload: dict | None = None, text: str | None = None) -> MagicMock:
	result = MagicMock()
	result.status_code = status_code
	result.json.return_value = payload or {}
	result.text = text if text is not None else ''
	return result


def provider() -> SimpleNamespace:
	return SimpleNamespace(domain='https://anyrouter.example', sign_in_path='/api/user/sign_in')


def test_retries_lock_write_error_then_succeeds(monkeypatch):
	client = MagicMock()
	client.post.side_effect = [
		response(200, {'message': 'Error 1290: server is running with the LOCK_WRITE option'}),
		response(200, {'success': True}),
	]
	monkeypatch.setenv('CHECKIN_RETRY_DELAYS', '0')
	sleep = MagicMock()
	monkeypatch.setattr(checkin.time, 'sleep', sleep)

	assert execute_check_in(client, 'account', provider(), {}) is True
	assert client.post.call_count == 2
	sleep.assert_called_once_with(0)


def test_retries_transient_http_status(monkeypatch):
	client = MagicMock()
	client.post.side_effect = [response(503), response(200, {'code': 0})]
	monkeypatch.setenv('CHECKIN_RETRY_DELAYS', '0')
	monkeypatch.setattr(checkin.time, 'sleep', MagicMock())

	assert execute_check_in(client, 'account', provider(), {}) is True
	assert client.post.call_count == 2


def test_retries_network_error(monkeypatch):
	request = httpx.Request('POST', 'https://anyrouter.example/api/user/sign_in')
	client = MagicMock()
	client.post.side_effect = [httpx.ConnectError('temporary outage', request=request), response(200, {'ret': 1})]
	monkeypatch.setenv('CHECKIN_RETRY_DELAYS', '0')
	monkeypatch.setattr(checkin.time, 'sleep', MagicMock())

	assert execute_check_in(client, 'account', provider(), {}) is True
	assert client.post.call_count == 2


def test_does_not_retry_permanent_provider_error(monkeypatch):
	client = MagicMock()
	client.post.return_value = response(200, {'message': 'invalid account state'})
	monkeypatch.setenv('CHECKIN_RETRY_DELAYS', '0,0')
	sleep = MagicMock()
	monkeypatch.setattr(checkin.time, 'sleep', sleep)

	assert execute_check_in(client, 'account', provider(), {}) is False
	client.post.assert_called_once()
	sleep.assert_not_called()


def test_invalid_retry_delays_use_defaults(monkeypatch):
	monkeypatch.setenv('CHECKIN_RETRY_DELAYS', 'invalid')

	assert get_check_in_retry_delays() == checkin.DEFAULT_CHECKIN_RETRY_DELAYS


def test_non_finite_retry_delays_use_defaults(monkeypatch):
	monkeypatch.setenv('CHECKIN_RETRY_DELAYS', 'nan,inf')

	assert get_check_in_retry_delays() == checkin.DEFAULT_CHECKIN_RETRY_DELAYS
