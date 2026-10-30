import copy
import json
import tempfile
import unittest
from pathlib import Path
from src.agent import Agent
from src.cli import write_result
from src.providers import MockPolicy, decision
from src.tools import Tools

DATA = Path(__file__).resolve().parents[1] / 'data'
BRIEF = {'topic': '轻剪字幕', 'audience': '口播创作者', 'platform': '抖音', 'target_seconds': 30, 'style': '直接演示'}
SCRIPT = {'title': '给口播加字幕', 'shots': [{'visual': '展示字幕编辑界面', 'lead': '', 'fact_ids': ['P01-F1'], 'close': ''}]}


class Sequence:
    name = 'test-double'
    def __init__(self, actions):
        self.actions = iter(actions)
    def decide(self, system, context):
        return next(self.actions)


class AgentTests(unittest.TestCase):
    def run_mock(self, brief=None, fail=None, limit=8):
        brief = brief or copy.deepcopy(BRIEF)
        return Agent(MockPolicy(), Tools(DATA, brief, fail), limit).run(brief)

    def ready_tools(self):
        t = Tools(DATA, BRIEF)
        t.call('search', {'query': '轻剪'})
        return t

    def test_normal(self):
        r = self.run_mock()
        self.assertEqual(r['status'], 'completed')
        self.assertEqual(r['script']['shots'][0]['sources'][0]['material_id'], 'P01')

    def test_each_missing_field(self):
        for field in BRIEF:
            with self.subTest(field=field):
                b = dict(BRIEF); del b[field]
                self.assertEqual(self.run_mock(b)['status'], 'needs_input')

    def test_invalid_duration(self):
        for value in [-1, '30', True, float('nan'), float('inf')]:
            self.assertIn('target_seconds', Agent.missing({**BRIEF, 'target_seconds': value}))

    def test_no_material(self):
        r = self.run_mock({**BRIEF, 'topic': '星际跃迁引擎'})
        self.assertEqual(r['status'], 'needs_input')
        self.assertEqual(sum(s['action'] == 'search' for s in r['trace']), 2)

    def test_alias_search(self):
        t = Tools(DATA, BRIEF)
        self.assertEqual(t.search('caption')['materials'][0]['id'], 'P01')

    def test_search_empty_not_entire_database(self):
        self.assertFalse(Tools(DATA, BRIEF).call('search', {'query': ''})['ok'])

    def test_transient_search_failure(self):
        r = self.run_mock(fail='search')
        self.assertEqual(r['status'], 'completed')
        self.assertEqual(r['trace'][0]['observation']['error'], 'TEMPORARY_UNAVAILABLE')

    def test_transient_check_failure_preserves_search(self):
        r = self.run_mock(fail='check_script')
        self.assertEqual(r['status'], 'completed')
        self.assertEqual(sum(s['action'] == 'search' for s in r['trace']), 1)

    def test_over_duration_revision(self):
        r = self.run_mock({**BRIEF, 'target_seconds': 8, 'start_long': True})
        self.assertFalse(r['revisions'][0]['passed'])
        self.assertLessEqual(r['script']['estimated_total_seconds'], 8)
        self.assertEqual(r['status'], 'completed')

    def test_impossible_duration(self):
        self.assertEqual(self.run_mock({**BRIEF, 'target_seconds': 1})['status'], 'incomplete')

    def test_banned_claim_in_title_and_visual(self):
        for field in ['title', 'visual']:
            s = copy.deepcopy(SCRIPT)
            if field == 'title': s[field] = '效率提升80%'
            else: s['shots'][0][field] = '自动翻译'
            self.assertFalse(self.ready_tools().check_script(s)['passed'])

    def test_unknown_source(self):
        s = copy.deepcopy(SCRIPT); s['shots'][0]['fact_ids'] = ['P99-F1']
        r = self.ready_tools().check_script(s)
        self.assertIn('UNKNOWN_FACT', [x['code'] for x in r['issues']])

    def test_cannot_cite_unretrieved_fact(self):
        self.assertFalse(Tools(DATA, BRIEF).check_script(SCRIPT)['passed'])

    def test_changed_source_changes_output(self):
        t = self.ready_tools()
        t.retrieved['P01']['facts'][0]['text'] = '轻剪支持手动输入字幕。'
        r = t.check_script(SCRIPT)
        self.assertEqual(r['shots'][0]['narration'], '轻剪支持手动输入字幕。')

    def test_changed_rate_changes_timing(self):
        t = self.ready_tools(); original = t.check_script(SCRIPT)['estimated_total_seconds']
        t.rules['speech_units_per_second'] = 2
        self.assertGreater(t.check_script(SCRIPT)['estimated_total_seconds'], original)

    def test_source_quotes_exact(self):
        t = self.ready_tools(); r = t.check_script(SCRIPT)
        self.assertEqual(r['shots'][0]['narration'], r['shots'][0]['sources'][0]['quote'])

    def test_unapproved_narration(self):
        s = copy.deepcopy(SCRIPT); s['shots'][0]['lead'] = '效率提升80%'
        self.assertFalse(self.ready_tools().check_script(s)['passed'])

    def test_empty_shots(self):
        self.assertFalse(self.ready_tools().call('check_script', {'script': {'title': 'x', 'shots': []}})['ok'])

    def test_no_false_completion(self):
        p = Sequence([decision('finish', '尝试直接完成', status='completed', script_id='fake')])
        r = Agent(p, Tools(DATA, BRIEF), 1).run(BRIEF)
        self.assertEqual(r['status'], 'incomplete')
        self.assertEqual(r['trace'][0]['observation']['error'], 'COMPLETION_REJECTED')

    def test_failed_revision_invalidates_prior_pass(self):
        t = self.ready_tools(); passed = t.check_script(SCRIPT)
        t.call('check_script', {'script': {}})
        p = Sequence([decision('finish', '旧版本通过', status='completed', script_id=passed['script_id'])])
        self.assertEqual(Agent(p, t, 1).run(BRIEF)['status'], 'incomplete')

    def test_stale_script_id(self):
        t = self.ready_tools(); t.check_script(SCRIPT)
        p = Sequence([decision('finish', '错误版本号', status='completed', script_id='old')])
        self.assertEqual(Agent(p, t, 1).run(BRIEF)['status'], 'incomplete')

    def test_tool_failure_invalidates_prior_pass(self):
        t = self.ready_tools(); passed = t.check_script(SCRIPT)
        t.fail_once = 'check_script'
        t.call('check_script', {'script': SCRIPT})
        p = Sequence([decision('finish', '尝试使用旧稿', status='completed', script_id=passed['script_id'])])
        self.assertEqual(Agent(p, t, 1).run(BRIEF)['status'], 'incomplete')

    def test_malformed_model_json(self):
        p = Sequence([{'action': 'search', 'arguments_json': 'broken'}])
        r = Agent(p, Tools(DATA, BRIEF), 1).run(BRIEF)
        self.assertEqual(r['trace'][0]['observation']['error'], 'INVALID_JSON_ARGUMENTS')

    def test_unknown_action(self):
        p = Sequence([decision('publish', '不支持的动作')])
        r = Agent(p, Tools(DATA, BRIEF), 1).run(BRIEF)
        self.assertEqual(r['trace'][0]['observation']['error'], 'UNKNOWN_ACTION')

    def test_step_limit(self):
        r = self.run_mock(limit=1)
        self.assertEqual((r['status'], r['steps']), ('incomplete', 1))

    def test_model_failure(self):
        r = Agent(Sequence([]), Tools(DATA, BRIEF)).run(BRIEF)
        self.assertEqual(r['trace'][0]['action'], 'model_error')
        self.assertEqual(r['status'], 'incomplete')

    def test_export(self):
        r = self.run_mock()
        directory = DATA.parent / 'runs' / 'test-export'
        write_result(directory, r)
        self.assertIn('P01-F1', (directory / 'script.md').read_text(encoding='utf-8'))
        self.assertEqual(len((directory / 'trace.jsonl').read_text(encoding='utf-8').splitlines()), r['steps'])


if __name__ == '__main__':
    unittest.main()
