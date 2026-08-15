from unittest.mock import AsyncMock

import pytest

from utils.browser import TURNSTILE_WAIT_TIMEOUT_MS, prepare_login_challenges


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
