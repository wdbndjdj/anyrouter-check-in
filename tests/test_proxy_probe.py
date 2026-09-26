import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from scripts import probe_proxy_candidates
from scripts.probe_proxy_candidates import _controller_request


class EmptySelectionResponseHandler(BaseHTTPRequestHandler):
	def do_PUT(self):
		length = int(self.headers.get('Content-Length', '0'))
		self.server.received_payload = json.loads(self.rfile.read(length).decode('utf-8'))
		self.send_response(204)
		self.end_headers()

	def log_message(self, *_args):
		pass


def test_mihomo_selection_accepts_empty_204_response():
	server = ThreadingHTTPServer(('127.0.0.1', 0), EmptySelectionResponseHandler)
	thread = threading.Thread(target=server.serve_forever, daemon=True)
	thread.start()
	try:
		result = _controller_request(
			f'http://127.0.0.1:{server.server_port}/proxies/CHECKIN',
			payload={'name': 'RN-CF-香港入口'},
		)
		assert result == {}
		assert server.received_payload == {'name': 'RN-CF-香港入口'}
	finally:
		server.shutdown()
		thread.join(timeout=2)
		server.server_close()


def test_main_picks_lowest_latency_candidate_after_all_project_probes_pass(tmp_path, monkeypatch, capsys):
	provider_file = tmp_path / 'provider.json'
	provider_file.write_text(
		json.dumps(
			{
				'proxies': [
					{'name': 'RN-CF-香港入口', 'type': 'VMess'},
					{'name': 'RN-CF-洛杉矶入口', 'type': 'VMess'},
				]
			}
		),
		encoding='utf-8',
	)
	monkeypatch.setattr(
		sys,
		'argv',
		['probe_proxy_candidates.py', str(provider_file), 'http://controller', 'http://proxy', '3', '4'],
	)
	monkeypatch.setenv('PROXY_TEST_URL', 'https://service/api/status')
	monkeypatch.setenv('PROXY_TEST_MODE', 'status_json')
	monkeypatch.setenv('PROXY_EXTRA_TEST_URL', 'https://service/login')
	monkeypatch.setenv('PROXY_EXTRA_TEST_MODE', 'login_page')
	selected: list[str] = []

	def choose_candidate(_url, *, payload=None):
		selected.append(payload['name'])
		return {}

	def successful_probe(url, _proxy_url, _timeout):
		latency = 15 if selected[-1] == 'RN-CF-香港入口' else 40
		body = '{"success":true,"data":{}}' if url.endswith('/status') else '<div id="root">Sign in</div>' + ('x' * 220)
		return 200, body, latency

	monkeypatch.setattr(probe_proxy_candidates, '_controller_request', choose_candidate)
	monkeypatch.setattr(probe_proxy_candidates, '_request_probe', successful_probe)

	assert probe_proxy_candidates.main() == 0
	assert json.loads(capsys.readouterr().out) == {
		'name': 'RN-CF-香港入口',
		'median_ms': 30,
		'jitter_ms': 0,
		'rounds_passed': 3,
	}
	assert set(selected) == {'RN-CF-香港入口', 'RN-CF-洛杉矶入口'}
