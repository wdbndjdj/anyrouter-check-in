from unittest.mock import AsyncMock, MagicMock

import pytest

from utils.browser import TURNSTILE_WAIT_TIMEOUT_MS, prepare_login_challenges, submit_login_form


class ResponseContext:
	def __init__(self, response):
		async def response_value():
			return response

		self.value = response_value()

	async def __aenter__(self):
		return self

	async def __aexit__(self, exc_type, exc, traceback):
		return False


class TimeoutResponseContext:
	async def __aenter__(self):
		return self

	async def __aexit__(self, exc_type, exc, traceback):
		raise TimeoutError('response timed out')


@pytest.mark.asyncio
async def test_prepare_login_challenges_accepts_terms_and_waits_for_turnstile(capsys):
	page = AsyncMock()
	page.evaluate.side_effect = [1, True]

	await prepare_login_challenges(page, 120_000)

	page.wait_for_function.assert_awaited_once()
	assert page.wait_for_function.await_args.kwargs['timeout'] == TURNSTILE_WAIT_TIMEOUT_MS
	output = capsys.readouterr().out
	assert 'Accepted 1 required login agreement checkbox' in output
	assert 'Turnstile login token is ready' in output


@pytest.mark.asyncio
async def test_prepare_login_challenges_skips_wait_when_turnstile_is_absent():
	page = AsyncMock()
	page.evaluate.side_effect = [0, False]

	await prepare_login_challenges(page, 120_000)

	page.wait_for_function.assert_not_awaited()


@pytest.mark.asyncio
async def test_prepare_login_challenges_raises_when_turnstile_never_finishes():
	page = AsyncMock()
	page.evaluate.side_effect = [0, True]
	page.wait_for_function.side_effect = RuntimeError('timed out')

	with pytest.raises(TimeoutError, match='Turnstile login token was not generated'):
		await prepare_login_challenges(page, 15_000)

	assert page.wait_for_function.await_args.kwargs['timeout'] == 15_000


@pytest.mark.asyncio
async def test_submit_login_form_reports_server_rejection(mocker, capsys):
	submit = AsyncMock()
	response = MagicMock(url='https://example.test/api/user/login?turnstile=token', status=200)
	response.json = AsyncMock(return_value={'success': False, 'message': 'bad credentials'})
	page = MagicMock()
	page.expect_response.return_value = ResponseContext(response)
	mocker.patch('utils.browser._first_visible_locator', new=AsyncMock(return_value=submit))

	with pytest.raises(RuntimeError, match='bad credentials'):
		await submit_login_form(page, 30_000)

	submit.click.assert_awaited_once_with(timeout=15_000)
	assert 'success=False, message=bad credentials' in capsys.readouterr().out


@pytest.mark.asyncio
async def test_submit_login_form_accepts_successful_login(mocker):
	submit = AsyncMock()
	response = MagicMock(url='https://example.test/api/user/login', status=200)
	response.json = AsyncMock(return_value={'success': True, 'data': {'id': 42}})
	page = MagicMock()
	page.expect_response.return_value = ResponseContext(response)
	wait_load = mocker.patch('utils.browser._wait_for_optional_load_state', new=AsyncMock(return_value=True))
	wait_login = mocker.patch('utils.browser.wait_for_logged_in', new=AsyncMock(return_value=True))
	mocker.patch('utils.browser._first_visible_locator', new=AsyncMock(return_value=submit))

	await submit_login_form(page, 30_000)

	assert wait_load.await_count == 2
	wait_login.assert_awaited_once()


@pytest.mark.asyncio
async def test_submit_login_form_falls_back_to_native_form_submission(mocker):
	submit = AsyncMock()
	submit.evaluate.side_effect = [
		{'disabled': True, 'ariaDisabled': None, 'type': 'submit', 'formValid': True, 'formAction': None},
		None,
	]
	response = MagicMock(url='https://example.test/api/user/login/', status=200)
	response.json = AsyncMock(return_value={'success': True, 'data': {'id': 42}})
	page = MagicMock()
	page.expect_response.side_effect = [
		TimeoutResponseContext(),
		TimeoutResponseContext(),
		ResponseContext(response),
	]
	mocker.patch('utils.browser._wait_for_optional_load_state', new=AsyncMock(return_value=True))
	mocker.patch('utils.browser.wait_for_logged_in', new=AsyncMock(return_value=True))
	mocker.patch('utils.browser._first_visible_locator', new=AsyncMock(return_value=submit))

	await submit_login_form(page, 30_000)

	assert submit.click.await_count == 2
	assert submit.click.await_args_list[0].kwargs == {'timeout': 15_000}
	assert submit.click.await_args_list[1].kwargs == {'force': True, 'timeout': 15_000}
	assert submit.evaluate.await_count == 2
