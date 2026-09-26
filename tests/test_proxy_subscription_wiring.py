import re
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
WORKFLOW_PROXIES = (
	(
		'.github/workflows/checkin.yml',
		'配置代理',
		'scripts/setup_mihomo_proxy.sh',
		'https://anyrouter.top/api/status',
		'https://anyrouter.top/login',
	),
	(
		'.github/workflows/agentrouter.yml',
		'配置代理',
		'scripts/setup_agentrouter_proxy.sh',
		'https://agentrouter.org/api/status',
		'https://agentrouter.org/login',
	),
	(
		'.github/workflows/seekai.yml',
		'配置代理',
		'scripts/setup_mihomo_proxy.sh',
		'https://seekai.cc/api/status',
		'https://seekai.cc/profile',
	),
	(
		'.github/workflows/xingjianya.yml',
		'配置星见雅代理',
		'scripts/setup_mihomo_proxy.sh',
		'https://new.xinjianya.top/api/status',
		'https://new.xinjianya.top/login',
	),
)


def _step_block(workflow_text: str, step_name: str) -> str:
	lines = workflow_text.splitlines()
	marker = f'- name: {step_name}'
	start = next(
		(index for index, line in enumerate(lines) if line.strip() == marker),
		None,
	)
	assert start is not None, f'missing workflow step: {step_name}'
	indent = len(lines[start]) - len(lines[start].lstrip())
	end = next(
		(
			index
			for index in range(start + 1, len(lines))
			if len(lines[index]) - len(lines[index].lstrip()) == indent and lines[index].lstrip().startswith('- ')
		),
		len(lines),
	)
	return '\n'.join(lines[start:end])


@pytest.mark.parametrize(
	'workflow_path,step_name,setup_script,test_url,login_url',
	WORKFLOW_PROXIES,
)
def test_proxy_workflow_uses_shared_secret_and_project_probe(
	workflow_path, step_name, setup_script, test_url, login_url
):
	workflow_text = (ROOT / workflow_path).read_text(encoding='utf-8')
	proxy_step = _step_block(workflow_text, step_name)

	assert 'PROXY_SUBSCRIPTION_URL: ${{ secrets.PROXY_SUBSCRIPTION_URL }}' in proxy_step
	assert f'PROXY_TEST_URL: {test_url}' in proxy_step
	assert f'PROXY_EXTRA_TEST_URL: {login_url}' in proxy_step
	assert 'PROXY_EXTRA_TEST_MODE: login_page' in proxy_step
	assert f'run: bash {setup_script}' in proxy_step

	stop_step = _step_block(workflow_text, '停止代理')
	assert 'if: always()' in stop_step
	assert 'run: bash scripts/stop_mihomo_proxy.sh' in stop_step


def test_common_mihomo_provider_fetches_only_the_injected_subscription_url():
	script = (ROOT / 'scripts' / 'setup_mihomo_proxy.sh').read_text(encoding='utf-8')
	config_start = script.index('cat > config.yaml <<EOF')
	config_end = script.index('\nEOF', config_start)
	provider_config = script[config_start:config_end]

	assert 'curl' in script
	assert '"${PROXY_SUBSCRIPTION_URL}"' in script
	assert 'User-Agent: mihomo/' in script
	assert 'Accept: application/yaml, text/yaml, */*' in script
	assert 'type: file' in provider_config
	assert 'path: ./subscription.yaml' in provider_config
	assert 'filter: "${PROXY_NODE_FILTER}"' in provider_config
	assert 'type: http' not in provider_config
	assert 'PROXY_VALIDATION_ROUNDS="${PROXY_VALIDATION_ROUNDS:-5}"' in script
	assert re.search(r'(?m)^\s*if \[\[ -z \"\$\{PROXY_SUBSCRIPTION_URL:-\}\" \]\]', script)


def test_agentrouter_setup_downloads_shared_subscription_and_filters_candidate_nodes():
	script = (ROOT / 'scripts' / 'setup_agentrouter_proxy.sh').read_text(encoding='utf-8')

	assert 'setup_mihomo_proxy.sh' in script
	assert 'https://agentrouter.org/api/status' in script
	assert ':-status_json' in script
	assert 'https://agentrouter.org/login' in script
	assert ':-login_page' in script
	assert 'PROXY_NODE_URI' not in script


def test_proxy_subscription_values_are_not_embedded_in_workflow_files():
	for workflow_path, step_name, *_ in WORKFLOW_PROXIES:
		workflow_text = (ROOT / workflow_path).read_text(encoding='utf-8')
		proxy_step = _step_block(workflow_text, step_name)

		assert '${{ secrets.PROXY_SUBSCRIPTION_URL }}' in proxy_step
		assert not re.search(r'(?m)^\s*PROXY_SUBSCRIPTION_URL:\s*https?://', proxy_step)


@pytest.mark.parametrize(
	'workflow_path',
	[workflow_path for workflow_path, *_ in WORKFLOW_PROXIES],
)
def test_workflows_expose_a_proxy_only_validation_dispatch(workflow_path):
	workflow_text = (ROOT / workflow_path).read_text(encoding='utf-8')

	assert 'proxy_validation_only:' in workflow_text
	assert "github.event.inputs.proxy_validation_only != 'true'" in workflow_text
