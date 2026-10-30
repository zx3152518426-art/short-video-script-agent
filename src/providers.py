"""Model adapters. No credentials are read or copied by the Codex adapter."""
import json
import os
import shutil
import subprocess
import tempfile
import urllib.request
from pathlib import Path

SCHEMA = {'type': 'object', 'properties': {
    'action': {'type': 'string', 'enum': ['search', 'check_script', 'finish']},
    'reason': {'type': 'string'}, 'arguments_json': {'type': 'string'}},
    'required': ['action', 'reason', 'arguments_json'], 'additionalProperties': False}


class CodexPolicy:
    name = 'codex-live'

    def __init__(self, model=None):
        self.model = model or os.getenv('CODEX_MODEL', 'gpt-6.1-sol')
        self.executable = os.getenv('CODEX_BIN') or shutil.which('codex')
        if not self.executable:
            raise RuntimeError('找不到 codex，请先安装 Codex CLI 并执行 codex login')

    def decide(self, system, context):
        with tempfile.TemporaryDirectory(prefix='script-agent-') as tmp:
            root = Path(tmp)
            schema, output = root / 'schema.json', root / 'decision.json'
            schema.write_text(json.dumps(SCHEMA), encoding='utf-8')
            cmd = [self.executable, 'exec', '--ignore-user-config', '--ephemeral', '--skip-git-repo-check',
                   '--sandbox', 'read-only', '--color', 'never', '-m', self.model,
                   '-c', 'model_reasoning_effort="low"', '--output-schema', str(schema),
                   '-o', str(output), '-']
            proc = subprocess.run(cmd, input=system + '\n' + json.dumps(context, ensure_ascii=False),
                                  text=True, encoding='utf-8', capture_output=True, cwd=tmp, timeout=180)
            if proc.returncode != 0 or not output.exists():
                raise RuntimeError('Codex 调用失败，请检查本机登录与模型权限')
            return json.loads(output.read_text(encoding='utf-8'))


class OpenAICompatiblePolicy:
    name = 'openai-compatible-live'

    def __init__(self, model=None):
        self.model = model or os.environ['LLM_MODEL']
        self.url = os.environ['LLM_BASE_URL'].rstrip('/') + '/chat/completions'
        self.key = os.environ['LLM_API_KEY']

    def decide(self, system, context):
        payload = {'model': self.model, 'messages': [
            {'role': 'system', 'content': system + '\n输出结构：' + json.dumps(SCHEMA)},
            {'role': 'user', 'content': json.dumps(context, ensure_ascii=False)}],
            'response_format': {'type': 'json_object'}}
        request = urllib.request.Request(self.url, data=json.dumps(payload).encode(), headers={
            'Authorization': 'Bearer ' + self.key, 'Content-Type': 'application/json'})
        with urllib.request.urlopen(request, timeout=90) as response:
            data = json.load(response)
        return json.loads(data['choices'][0]['message']['content'])


def decision(action, reason, **args):
    return {'action': action, 'reason': reason, 'arguments_json': json.dumps(args, ensure_ascii=False)}


class MockPolicy:
    """Deterministic offline fixture, intentionally separate from the live adapters."""
    name = 'mock'
    model = None

    def decide(self, system, context):
        from .agent import Agent
        brief, trace = context['brief'], context['observations']
        missing = Agent.missing(brief)
        if missing:
            return decision('finish', '输入不完整', status='needs_input', message='请补充创作要求。', questions=missing, script_id='')
        if trace and trace[-1].get('observation', {}).get('error') == 'TEMPORARY_UNAVAILABLE':
            last = trace[-1]
            return decision(last['action'], '工具暂时失败，重试本步', **last['arguments'])
        searches = [r['observation'] for r in trace if r['action'] == 'search' and r['observation'].get('ok')]
        if not searches:
            return decision('search', '先查主题相关素材', query=brief['topic'])
        if not searches[-1]['count']:
            if len(searches) < 2:
                return decision('search', '原词无结果，改用产品名称', query=brief.get('product_name', brief['topic']))
            return decision('finish', '两次检索都未找到素材', status='needs_input', message='请提供产品介绍或素材。', questions=['产品素材'], script_id='')
        checks = [r['observation'] for r in trace if r['action'] == 'check_script' and r['observation'].get('ok')]
        if not checks and brief.get('initial_script'):
            return decision('check_script', '先检查用户已有稿件', script=brief['initial_script'])
        if checks and checks[-1]['passed']:
            return decision('finish', '最新版本已通过检查', status='completed', message='脚本已完成。', questions=[], script_id=checks[-1]['script_id'])
        facts = searches[-1]['materials'][0]['facts']
        count = max(1, len(facts) - len(checks)) if brief.get('start_long') else 1
        if checks and len(checks) >= len(facts):
            return decision('finish', '最短版本仍超时', status='incomplete', message='需要延长目标时长。', questions=[], script_id='')
        script = {'title': '给口播加上字幕', 'shots': [{'visual': '展示字幕编辑界面', 'lead': '', 'fact_ids': [f['id'] for f in facts[:count]], 'close': ''}]}
        return decision('check_script', '按检查结果压缩内容' if checks else '选择素材写成分镜并检查', script=script)
