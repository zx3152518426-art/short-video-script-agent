"""Generate evidence by running cases, never by writing expected output as actual output."""
import argparse
import json
import time
import unittest
from pathlib import Path
from src.agent import Agent
from src.cli import write_result
from src.providers import CodexPolicy, MockPolicy
from src.tools import Tools

ROOT = Path(__file__).resolve().parent
BASE = {'topic': '轻剪字幕演示', 'audience': '刚开始做口播的创作者', 'platform': '抖音', 'target_seconds': 30, 'style': '操作演示，表达直接'}
LONG = {'title': '给口播加字幕', 'shots': [{'visual': '录好口播后打开字幕编辑页', 'lead': '口播录好了，字幕怎么加？', 'fact_ids': ['P01-F1', 'P01-F2', 'P01-F3', 'P01-F4'], 'close': '检查完，再导出。'}]}
CASES = {
    'normal': (BASE, None, 'completed'),
    'missing_info': ({k: v for k, v in BASE.items() if k != 'target_seconds'}, None, 'needs_input'),
    'no_material': ({**BASE, 'topic': '星际跃迁引擎'}, None, 'needs_input'),
    'tool_failure': (BASE, 'check_script', 'completed'),
    'over_duration': ({**BASE, 'target_seconds': 8, 'initial_script': LONG, 'start_long': True}, None, 'completed'),
    'rule_revision': ({**BASE, 'initial_script': {**LONG, 'title': '效率提升80%'}}, None, 'completed'),
    'impossible_duration': ({**BASE, 'target_seconds': 1}, None, 'incomplete'),
}


def validate_result(name, result, expected):
    errors = []
    if result['status'] != expected:
        errors.append('任务状态与预期不同')
    if result['status'] == 'completed':
        script = result['script']
        if not script or not script['passed'] or script['estimated_total_seconds'] > script['target_seconds']:
            errors.append('成稿未通过检查或超时')
        if not script or not any(s['sources'] for s in script['shots']):
            errors.append('成稿缺少引用')
    if name == 'over_duration':
        revisions = result['revisions']
        if len(revisions) < 2 or not any(x['code'] == 'OVER_DURATION' for x in revisions[0]['issues']):
            errors.append('没有留下超时稿及修订稿')
    if name == 'tool_failure':
        if not any(r.get('observation', {}).get('error') == 'TEMPORARY_UNAVAILABLE' for r in result['trace']):
            errors.append('未观察到注入的工具失败')
    if name == 'rule_revision':
        if len(result['revisions']) < 2 or not any(x['code'] == 'BANNED_CLAIM' for x in result['revisions'][0]['issues']):
            errors.append('缺少规则违规与修改记录')
    if name in ('missing_info', 'no_material') and not result['questions']:
        errors.append('没有给出具体待补充项')
    return errors


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--provider', choices=['mock', 'codex'], default='mock')
    parser.add_argument('--cases', nargs='*', default=list(CASES))
    args = parser.parse_args()
    summary = []
    for name in args.cases:
        brief, fail, expected = CASES[name]
        dest = ROOT / 'examples' / args.provider / name
        dest.mkdir(parents=True, exist_ok=True)
        (dest / 'input.json').write_text(json.dumps(brief, ensure_ascii=False, indent=2), encoding='utf-8')
        policy = MockPolicy() if args.provider == 'mock' else CodexPolicy()
        result = Agent(policy, Tools(ROOT / 'data', brief, fail), 8).run(brief)
        write_result(dest, result)
        errors = validate_result(name, result, expected)
        row = {'case': name, 'expected': expected, 'actual': result['status'], 'passed': not errors, 'errors': errors,
               'steps': result['steps'], 'elapsed_seconds': result['elapsed_seconds'],
               'revisions': len(result['revisions']), 'path': str(dest.relative_to(ROOT)).replace('\\', '/')}
        summary.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
    summary_path = ROOT / 'examples' / args.provider / 'summary.json'
    previous = json.loads(summary_path.read_text(encoding='utf-8')) if summary_path.exists() else []
    merged = {row['case']: row for row in previous}
    merged.update({row['case']: row for row in summary})
    summary_path.write_text(json.dumps(list(merged.values()), ensure_ascii=False, indent=2), encoding='utf-8')
    return 0 if all(row['passed'] for row in summary) else 1


if __name__ == '__main__':
    raise SystemExit(main())
