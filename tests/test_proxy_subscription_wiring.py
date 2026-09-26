import re
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
TARGET_WORKFLOWS = {
	'.github/workflows/checkin.yml': {
		'test_url': 'https://api.bxacc.xyz/api/status',
		'extra_url': 'https://api.bxacc.xyz/login',
		'required': 'github.event.inputs.proxy_validation_only',
		'signin_step': '执行签到',
	},
	'.github/workflows/agentrouter.yml': {
		'test_url': 'https://agentrouter.org/api/status',
		'extra_url': 'https://agentrouter.org/login',
		'required': 'true',
		'signin_step': '执行 AgentRouter 签到',
	},
	'.github/workflows/seekai.yml': {
		'test_url': 'https://seekai.cc/api/status',
		'extra_url': 'https://seekai.cc/login',
		'required': 'github.event.inputs.proxy_validation_only',
		'signin_step': '执行 SeekAI 签到',
	},
}


def _step_block(workflow_text: str, step_name: str) -> str:
	lines = workflow_text.splitlines()
	marker = f'- name: {step_name}'
	start = next((index for index, line in enumerate(lines) if line.strip() == marker), None)
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


@pytest.mark.parametrize(('workflow_path', 'expected'), TARGET_WORKFLOWS.items())
def test_every_preexisting_proxy_workflow_uses_the_scoped_vmess_selector(workflow_path, expected):
	workflow_text = (ROOT / workflow_path).read_text(encoding='utf-8')
	proxy_step = _step_block(workflow_text, expected.get('proxy_step', '配置代理'))

	assert 'PROXY_SUBSCRIPTION_URL: ${{ secrets.PROXY_SUBSCRIPTION_URL }}' in proxy_step
	assert f'PROXY_TEST_URL: {expected["test_url"]}' in proxy_step
	assert f'PROXY_TEST_MODE: {expected.get("test_mode", "status_json")}' in proxy_step
	if 'extra_url' in expected:
		assert f'PROXY_EXTRA_TEST_URL: {expected["extra_url"]}' in proxy_step
		assert 'PROXY_EXTRA_TEST_MODE: login_page' in proxy_step
	else:
		assert 'PROXY_EXTRA_TEST_URL:' not in proxy_step
	assert 'run: bash scripts/setup_checkin_proxy.sh' in proxy_step
	assert expected['required'] in proxy_step

	stop_step = _step_block(workflow_text, '停止代理')
	assert 'if: always()' in stop_step
	assert 'run: bash scripts/stop_checkin_proxy.sh' in stop_step


@pytest.mark.parametrize('workflow_path', TARGET_WORKFLOWS)
def test_proxy_only_validation_skips_that_workflows_sign_in(workflow_path):
	workflow_text = (ROOT / workflow_path).read_text(encoding='utf-8')
	assert 'proxy_validation_only:' in workflow_text
	signin_step = _step_block(workflow_text, TARGET_WORKFLOWS[workflow_path]['signin_step'])
	assert "if: ${{ github.event.inputs.proxy_validation_only != 'true' }}" in signin_step


def test_seekai_keeps_its_existing_optional_proxy_gate():
	workflow_text = (ROOT / '.github/workflows/seekai.yml').read_text(encoding='utf-8')
	assert "SEEKAI_USE_PROXY: ${{ secrets.SEEKAI_USE_PROXY || 'false' }}" in workflow_text
	assert "github.event.inputs.proxy_validation_only == 'true'" in workflow_text
	assert "|| 'false'" in workflow_text


def test_non_proxy_dudu_workflow_stays_proxy_free():
	workflow_text = (ROOT / '.github/workflows/dudu.yml').read_text(encoding='utf-8').lower()
	assert 'proxy' not in workflow_text
	assert 'PROXY_SUBSCRIPTION_URL' not in workflow_text
	assert 'setup_checkin_proxy.sh' not in workflow_text


def test_only_preexisting_proxy_workflows_use_the_new_selector():
	for workflow_path in Path(ROOT / '.github/workflows').glob('*.yml'):
		workflow_text = workflow_path.read_text(encoding='utf-8')
		if 'setup_checkin_proxy.sh' in workflow_text:
			assert workflow_path.relative_to(ROOT).as_posix() in TARGET_WORKFLOWS


def test_proxy_subscription_values_are_not_embedded_in_workflows():
	for workflow_path in TARGET_WORKFLOWS:
		workflow_text = (ROOT / workflow_path).read_text(encoding='utf-8')
		expected = TARGET_WORKFLOWS[workflow_path]
		proxy_step = _step_block(workflow_text, expected.get('proxy_step', '配置代理'))
		assert '${{ secrets.PROXY_SUBSCRIPTION_URL }}' in proxy_step
		assert not re.search(r'(?m)^\s*PROXY_SUBSCRIPTION_URL:\s*https?://', proxy_step)


def test_target_selector_restricts_to_the_two_approved_vmess_nodes():
	script = (ROOT / 'scripts' / 'setup_checkin_proxy.sh').read_text(encoding='utf-8')
	config_start = script.index('cat > config.yaml <<EOF')
	config_end = script.index('\nEOF', config_start)
	provider_config = script[config_start:config_end]

	assert 'curl' in script
	assert '"${PROXY_SUBSCRIPTION_URL}"' in script
	assert 'User-Agent: mihomo/' in script
	assert 'Accept: application/yaml, text/yaml, */*' in script
	assert 'type: file' in provider_config
	assert 'path: ./subscription.yaml' in provider_config
	assert 'filter:' not in provider_config
	assert 'filter_vmess_candidates' in script
	assert 'type: http' not in provider_config
	assert 'PROXY_VALIDATION_ROUNDS="${PROXY_VALIDATION_ROUNDS:-5}"' in script
	assert re.search(r'(?m)^\s*if \[\[ -z "\$\{PROXY_SUBSCRIPTION_URL:-\}" \]\]', script)
