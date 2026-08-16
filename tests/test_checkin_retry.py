from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

import checkin
from checkin import execute_browser_check_in, execute_check_in, get_check_in_retry_delays


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


@pytest.mark.asyncio
async def test_browser_check_in_uses_logged_in_page_context():
	page = AsyncMock()
	page.evaluate.return_value = {
		'before': {'status': 200, 'body': {'success': True, 'data': {'quota': 500000, 'used_quota': 0}}},
		'checkIn': {'status': 200, 'body': {'success': True}},
		'after': {'status': 200, 'body': {'success': True, 'data': {'quota': 1000000, 'used_quota': 0}}},
	}
	provider_config = SimpleNamespace(
		user_info_path='/api/user/self',
		sign_in_path='/api/user/checkin',
		api_user_key='new-api-user',
	)

	success, before, after = await execute_browser_check_in(page, 'account', provider_config, '42')

	assert success is True
	assert before['quota'] == 1.0
	assert after['quota'] == 2.0
	assert page.evaluate.await_args.args[1]['apiUser'] == '42'
	assert page.evaluate.await_args.args[1]['loginUser'] is None
	assert page.evaluate.await_args.args[1]['retryDelaysMs'] == [15000, 45000]
	assert "'Cache-Control': 'no-store'" in page.evaluate.await_args.args[0]
	assert 'retry ? [0, ...retryDelaysMs] : [0]' in page.evaluate.await_args.args[0]
