"""代理配置：读取环境变量并供浏览器 / HTTP 客户端使用。"""

from __future__ import annotations

import os


def get_proxy_server(*, use_proxy: bool = True) -> str | None:
	"""Read CHECKIN_PROXY_URL and fail closed when a provider requires it."""
	if not use_proxy:
		return None
	server = os.getenv('CHECKIN_PROXY_URL', '').strip()
	if not server:
		raise RuntimeError('Provider requires proxy but CHECKIN_PROXY_URL is not set')
	return server


def get_playwright_proxy(*, use_proxy: bool = True) -> dict[str, str] | None:
	server = get_proxy_server(use_proxy=use_proxy)
	if not server:
		return None
	return {'server': server}
