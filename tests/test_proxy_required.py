from utils.proxy import get_playwright_proxy, get_proxy_server


def test_provider_without_proxy_requirement_stays_direct(monkeypatch):
	monkeypatch.delenv('CHECKIN_PROXY_URL', raising=False)

	assert get_proxy_server(use_proxy=False) is None
	assert get_playwright_proxy(use_proxy=False) is None


def test_provider_uses_configured_endpoint_when_available(monkeypatch):
	monkeypatch.setenv('CHECKIN_PROXY_URL', 'http://127.0.0.1:7890')

	assert get_proxy_server(use_proxy=True) == 'http://127.0.0.1:7890'
	assert get_playwright_proxy(use_proxy=True) == {'server': 'http://127.0.0.1:7890'}
