from unittest.mock import AsyncMock, MagicMock

import pytest

from utils.browser import (
	_ACCEPT_LOGIN_TERMS_JS,
	TURNSTILE_WAIT_TIMEOUT_MS,
	_first_visible_locator,
	_set_input_value,
	prepare_login_challenges,
	submit_login_form,
)


def test_login_terms_acceptor_supports_english_and_aria_checkboxes():
	assert 'I have read' in _ACCEPT_LOGIN_TERMS_JS
	assert 'User Agreement' in _ACCEPT_LOGIN_TERMS_JS
	assert 'Privacy Policy' in _ACCEPT_LOGIN_TERMS_JS
	assert '[role="checkbox"]' in _ACCEPT_LOGIN_TERMS_JS


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
async def test_set_input_value_types_and_blurs_controlled_input():
	locator = AsyncMock()
	locator.input_value.return_value = 'account@example.test'

	await _set_input_value(locator, 'account@example.test', 15_000)

	locator.fill.assert_awaited_once_with('', timeout=15_000)
	locator.press_sequentially.assert_awaited_once_with('account@example.test', delay=20, timeout=15_000)
	locator.press.assert_awaited_once_with('Tab', timeout=5000)
	locator.evaluate.assert_not_awaited()


@pytest.mark.asyncio
async def test_set_input_value_fallback_forces_value_transition_and_focusout():
	locator = AsyncMock()
	locator.press_sequentially.side_effect = RuntimeError('keyboard unavailable')
	locator.press.side_effect = RuntimeError('tab unavailable')
	locator.input_value.return_value = 'account@example.test'

	await _set_input_value(locator, 'account@example.test', 15_000)

	assert locator.evaluate.await_count == 2
	value_script = locator.evaluate.await_args_list[0].args[0]
	focus_script = locator.evaluate.await_args_list[1].args[0]
	assert "setter?.call(el, '')" in value_script
	assert "setter?.call(el, v)" in value_script
	assert "new Event('input'" in value_script
	assert "new Event('change'" in value_script
	assert "new FocusEvent('focusout'" in focus_script


@pytest.mark.asyncio
async def test_first_visible_locator_checks_all_matches():
	hidden = AsyncMock()
	hidden.is_visible.return_value = False
	visible = AsyncMock()
	visible.is_visible.return_value = True
	matches = MagicMock()
	matches.count = AsyncMock(return_value=2)
	matches.nth.side_effect = [hidden, visible]
	page = MagicMock()
	page.locator.return_value = matches

	result = await _first_visible_locator(page, ('input[name="email"]',))

	assert result is visible
	assert matches.nth.call_count == 2


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
async def test_submit_login_form_enables_disabled_button_fallback(mocker):
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
	assert 'button.disabled = false' in submit.evaluate.await_args_list[1].args[0]
