from pathlib import Path

WORKFLOW = Path(__file__).parents[1] / '.github' / 'workflows' / 'dudu.yml'
SCRIPT = Path(__file__).parents[1] / 'scripts' / 'dudu_checkin.sh'


def test_dudu_workflow_uses_daily_schedule_and_manual_dispatch():
	text = WORKFLOW.read_text(encoding='utf-8')

	assert "cron: '10 0 * * *'" in text
	assert 'workflow_dispatch:' in text
	assert 'environment: production' in text


def test_dudu_workflow_uses_bearer_secret_and_checkin_endpoint():
	text = WORKFLOW.read_text(encoding='utf-8')

	assert 'DUDU_ACCESS_TOKEN: ${{ secrets.DUDU_ACCESS_TOKEN }}' in text
	assert 'run: bash scripts/dudu_checkin.sh' in text

	script = SCRIPT.read_text(encoding='utf-8')
	assert 'Authorization: Bearer ${DUDU_ACCESS_TOKEN}' in script
	assert '${base_url}/api/user/checkin' in script
	assert 'status_is_checked_in' in script
	assert 'checkin_succeeded' in script
	assert 'dudu_checkin' not in script


def test_dudu_workflow_does_not_contain_a_literal_access_token():
	text = '\n'.join((WORKFLOW.read_text(encoding='utf-8'), SCRIPT.read_text(encoding='utf-8')))

	assert 'xVpPGFlyFtApN' not in text
