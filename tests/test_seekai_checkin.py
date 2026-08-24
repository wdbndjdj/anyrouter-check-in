from types import SimpleNamespace

import pytest

import seekai_checkin
from seekai_checkin import (
	SeekAIAccount,
	bearer_headers,
	checkin_response_result,
	checkin_status,
	extract_refresh_result,
	parse_accounts,
	parse_cookies,
)


def test_parse_cookie_header_and_mapping():
	assert parse_cookies('session=abc; cf_clearance=xyz') == {'session': 'abc', 'cf_clearance': 'xyz'}
	assert parse_cookies({'session': 'abc'}) == {'session': 'abc'}
	assert parse_cookies([{'name': 'session', 'value': 'abc'}]) == {'session': 'abc'}


def test_parse_accounts_requires_auth_material():
	accounts = parse_accounts('[{"name":"one","cookies":{"session":"abc"}}]')
	assert accounts == [SeekAIAccount('one', {'session': 'abc'})]
	with pytest.raises(ValueError, match='cookies or access_token'):
		parse_accounts('[{"name":"one"}]')


def test_parse_accounts_accepts_single_object_and_api_user_alias():
	account = parse_accounts('{"name":"one","cookies":"session=abc","api_user":29704}')[0]
	assert account.user_id == '29704'
	assert account.cookies == {'session': 'abc'}


def test_bearer_headers_include_optional_session_header():
	account = SeekAIAccount('one', {}, 'TOKEN', 'SID')
	headers = bearer_headers(account)
	assert headers['Authorization'] == 'Bearer TOKEN'
	assert headers['X-Auth-Session'] == 'SID'
	assert 'new-api-user' not in headers


def test_refresh_result_validates_user_id_without_using_it_as_a_header():
	account = SeekAIAccount('one', {'session': 'abc'}, user_id='29704')
	token, user_id = extract_refresh_result({'access_token': 'NEW', 'user': {'id': 29704}}, account)
	assert token == 'NEW'
	assert user_id == '29704'
	with pytest.raises(ValueError, match='refresh user id mismatch'):
		extract_refresh_result({'access_token': 'NEW', 'user': {'id': 999}}, account)


def test_checkin_status_reads_nested_stats():
	checked, stats = checkin_status({'success': True, 'data': {'stats': {'checked_in_today': True}}})
	assert checked is True
	assert stats['checked_in_today'] is True


def test_checkin_response_handles_success_already_and_turnstile():
	result = checkin_response_result({'success': True, 'data': {'quota_awarded': 123}}, status=200)
	assert result.success is True
	assert result.quota_awarded == 123
	assert checkin_response_result({'message': 'Already checked in'}, status=200).already_checked is True
	assert checkin_response_result({'success': False, 'message': 'Turnstile required'}, status=200).success is False


@pytest.mark.asyncio
async def test_refresh_access_token_uses_response_token(monkeypatch):
	account = SeekAIAccount('one', {'session': 'abc'}, None, 'SID')
	page = SimpleNamespace(evaluate=lambda *args: None)

	async def fake_api(*args, **kwargs):
		assert kwargs['method'] == 'POST'
		assert kwargs['headers']['X-Auth-Session'] == 'SID'
		return {'status': 200, 'body': {'success': True, 'data': {'access_token': 'NEW'}}}

	monkeypatch.setattr(seekai_checkin, '_page_api', fake_api)
	assert await seekai_checkin.refresh_access_token(page, account) == 'NEW'
