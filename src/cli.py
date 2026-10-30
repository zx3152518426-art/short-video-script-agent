import argparse
import json
from pathlib import Path
from .agent import Agent
from .providers import CodexPolicy, MockPolicy, OpenAICompatiblePolicy
from .tools import Tools


def write_result(output, result):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    (output / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    (output / 'trace.jsonl').write_text(''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in result['trace']), encoding='utf-8')
    script = result.get('script')
    text = [f"# {script['title'] if script else '脚本任务'}", '', f"状态：{result['status']}", '', result['message'], '']
    if script:
        text += [f"预计总时长：{script['estimated_total_seconds']} 秒 / 目标 {script['target_seconds']} 秒", '']
        for shot in script['shots']:
            text += [f"## 镜头 {shot['shot']} · {shot['estimated_seconds']} 秒", '', f"画面：{shot['visual']}", '', f"旁白 / 字幕：{shot['narration']}", '', '来源：' + '、'.join(s['fact_id'] for s in shot['sources']), '']
        text += ['检查结果：' + ('通过' if script['passed'] else json.dumps(script['issues'], ensure_ascii=False)), '']
    if result['questions']:
        text += ['待补充：' + '；'.join(str(q) for q in result['questions'])]
    (output / 'script.md').write_text('\n'.join(text), encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description='有素材依据、能自检修改的短视频脚本 Agent')
    parser.add_argument('--input', required=True)
    parser.add_argument('--provider', choices=['mock', 'codex', 'openai'], default='mock')
    parser.add_argument('--model')
    parser.add_argument('--data', default='data')
    parser.add_argument('--output', default='runs/latest')
    parser.add_argument('--max-steps', type=int, default=8)
    parser.add_argument('--fail-once', choices=['search', 'check_script'])
    args = parser.parse_args()
    brief = json.loads(Path(args.input).read_text(encoding='utf-8-sig'))
    policy = {'mock': lambda: MockPolicy(), 'codex': lambda: CodexPolicy(args.model), 'openai': lambda: OpenAICompatiblePolicy(args.model)}[args.provider]()
    result = Agent(policy, Tools(args.data, brief, args.fail_once), args.max_steps).run(brief)
    write_result(args.output, result)
    print(json.dumps({'status': result['status'], 'steps': result['steps'], 'output': args.output}, ensure_ascii=False))
    return 0 if result['status'] == 'completed' else 2


if __name__ == '__main__':
    raise SystemExit(main())
