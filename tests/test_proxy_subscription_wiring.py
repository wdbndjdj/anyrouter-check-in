import re
from pathlib import Path

ROOT = Path(__file__).parents[1]
TARGET_WORKFLOW = '.github/workflows/checkin.yml'


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


def test_target_proxy_workflow_uses_existing_subscription_and_probe():
	workflow_text = (ROOT / TARGET_WORKFLOW).read_text(encoding='utf-8')
	proxy_step = _step_block(workflow_text, '配置代理')

	assert 'PROXY_SUBSCRIPTION_URL: ${{ secrets.PROXY_SUBSCRIPTION_URL }}' in proxy_step
	assert 'PROXY_TEST_URL: https://anyrouter.top/api/status' in proxy_step
	assert 'PROXY_EXTRA_TEST_URL: https://anyrouter.top/login' in proxy_step
	assert 'PROXY_EXTRA_TEST_MODE: login_page' in proxy_step
	assert 'run: bash scripts/setup_checkin_proxy.sh' in proxy_step

	stop_step = _step_block(workflow_text, '停止代理')
	assert 'if: always()' in stop_step
	assert 'run: bash scripts/stop_checkin_proxy.sh' in stop_step


def test_target_setup_selects_only_the_approved_nodes():
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


def test_agentrouter_keeps_its_preexisting_dedicated_proxy_configuration():
	workflow_text = (ROOT / '.github/workflows/agentrouter.yml').read_text(encoding='utf-8')
	proxy_step = _step_block(workflow_text, '配置代理')

	assert 'PROXY_NODE_URI: ${{ secrets.AGENTROUTER_PROXY_NODE_URI }}' in proxy_step
	assert 'PROXY_SUBSCRIPTION_URL:' not in proxy_step
	assert 'proxy_validation_only:' not in workflow_text


def test_other_workflows_do_not_get_new_proxy_validation_or_project_probes():
	for workflow_path in (
		'.github/workflows/agentrouter.yml',
		'.github/workflows/seekai.yml',
		'.github/workflows/xingjianya.yml',
	):
		workflow_text = (ROOT / workflow_path).read_text(encoding='utf-8')
		assert 'proxy_validation_only:' not in workflow_text
		assert 'PROXY_EXTRA_TEST_URL:' not in workflow_text

	seekai = (ROOT / '.github/workflows/seekai.yml').read_text(encoding='utf-8')
	assert "SEEKAI_USE_PROXY: ${{ secrets.SEEKAI_USE_PROXY || 'false' }}" in seekai
	assert 'PROXY_REQUIRED: false' in seekai


def test_proxy_subscription_values_are_not_embedded_in_target_workflow():
	workflow_text = (ROOT / TARGET_WORKFLOW).read_text(encoding='utf-8')
	proxy_step = _step_block(workflow_text, '配置代理')

	assert '${{ secrets.PROXY_SUBSCRIPTION_URL }}' in proxy_step
	assert not re.search(r'(?m)^\s*PROXY_SUBSCRIPTION_URL:\s*https?://', proxy_step)


def test_only_target_workflow_exposes_proxy_only_validation_dispatch():
	target = (ROOT / TARGET_WORKFLOW).read_text(encoding='utf-8')
	assert 'proxy_validation_only:' in target
	assert "github.event.inputs.proxy_validation_only != 'true'" in target

	for workflow_path in (
		'.github/workflows/agentrouter.yml',
		'.github/workflows/seekai.yml',
		'.github/workflows/xingjianya.yml',
	):
		workflow_text = (ROOT / workflow_path).read_text(encoding='utf-8')
		assert 'proxy_validation_only:' not in workflow_text
