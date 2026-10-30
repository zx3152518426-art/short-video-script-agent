"""Local tools. Facts and checks remain reproducible without a model."""
import hashlib
import json
import math
import re
from pathlib import Path


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]


class Tools:
    def __init__(self, data_dir, brief, fail_once=None):
        self.materials = json.loads((Path(data_dir) / 'materials.json').read_text(encoding='utf-8'))
        self.rules = json.loads((Path(data_dir) / 'rules.json').read_text(encoding='utf-8'))
        self.brief = brief
        self.fail_once = fail_once
        self.retrieved = {}
        self.latest = None
        self.revisions = []

    def call(self, action, args):
        if action == 'check_script':
            self.latest = None
        if self.fail_once == action:
            self.fail_once = None
            return {'ok': False, 'error': 'TEMPORARY_UNAVAILABLE', 'retryable': True}
        try:
            if action == 'search':
                return self.search(args['query'])
            if action == 'check_script':
                return self.check_script(args['script'])
            return {'ok': False, 'error': 'UNKNOWN_TOOL'}
        except (KeyError, TypeError, ValueError) as exc:
            return {'ok': False, 'error': 'INVALID_ARGUMENTS', 'detail': str(exc)[:200]}

    def search(self, query):
        if not isinstance(query, str) or not query.strip():
            raise ValueError('query 需要非空文本')
        tokens = re.findall(r'[a-z0-9]+|[\u4e00-\u9fff]+', query.lower())
        hits = []
        for material in self.materials:
            terms = [material['id'], material['name'], *material['keywords']]
            score = sum(1 for term in terms if any(term.lower() in t or t in term.lower() for t in tokens))
            if score:
                hits.append((score, material))
        hits.sort(key=lambda item: (-item[0], item[1]['id']))
        records = [m for _, m in hits[:3]]
        self.retrieved.update({m['id']: m for m in records})
        return {'ok': True, 'query': query, 'materials': records, 'count': len(records),
                'copy_options': self.rules['copy_options'], 'rules': self.rules}

    def check_script(self, script):
        """Resolve narration from fact IDs; never take product claims on trust."""
        self.latest = None  # a malformed new revision invalidates the previous approval
        if not isinstance(script, dict) or not isinstance(script.get('title'), str):
            raise ValueError('script 需要 title 和 shots')
        shots = script.get('shots')
        if not isinstance(shots, list) or not 1 <= len(shots) <= 8:
            raise ValueError('shots 数量应为 1–8')
        issues, rendered = [], []
        catalog = {f['id']: (m, f) for m in self.retrieved.values() for f in m['facts']}
        used = set()
        for index, shot in enumerate(shots, 1):
            if not isinstance(shot, dict) or not isinstance(shot.get('visual'), str) or not shot['visual'].strip():
                raise ValueError('每镜需要 visual')
            if not isinstance(shot.get('fact_ids'), list) or not all(isinstance(x, str) for x in shot['fact_ids']):
                raise ValueError('每镜需要 fact_ids 列表')
            lead, close = shot.get('lead', ''), shot.get('close', '')
            if lead not in self.rules['copy_options']['lead'] or close not in self.rules['copy_options']['close']:
                issues.append({'code': 'COPY_NOT_APPROVED', 'shot': index, 'message': '开场或收尾不在品牌用语表中'})
            facts, sources = [], []
            for fid in shot['fact_ids']:
                if fid not in catalog:
                    issues.append({'code': 'UNKNOWN_FACT', 'shot': index, 'fact_id': fid})
                    continue
                material, fact = catalog[fid]
                facts.append(fact['text'])
                sources.append({'material_id': material['id'], 'fact_id': fid, 'quote': fact['text']})
                used.add(fid)
            narration = ''.join([lead, *facts, close])
            if not narration.strip():
                issues.append({'code': 'EMPTY_NARRATION', 'shot': index})
            units = len(re.findall(r'[\u4e00-\u9fff]|[a-zA-Z0-9]+', narration))
            seconds = round(max(self.rules['min_shot_seconds'], units / self.rules['speech_units_per_second'] + self.rules['pause_seconds']), 2)
            rendered.append({'shot': index, 'visual': shot['visual'], 'narration': narration,
                             'subtitle': narration, 'estimated_seconds': seconds, 'sources': sources})
        if not used:
            issues.append({'code': 'NO_FACTS', 'message': '至少使用一条检索所得产品事实'})
        # Check every visible copy field, including titles and visual directions.
        all_text = script['title'] + '\n' + '\n'.join(s['visual'] + s['narration'] for s in rendered)
        for word in self.rules['banned_terms']:
            if word.lower() in all_text.lower():
                issues.append({'code': 'BANNED_CLAIM', 'term': word})
        permitted_numbers = set(re.findall(r'\d+(?:\.\d+)?%?', ''.join(f['text'] for _, f in catalog.values())))
        for number in set(re.findall(r'\d+(?:\.\d+)?%?', all_text)) - permitted_numbers:
            issues.append({'code': 'UNSUPPORTED_NUMBER', 'value': number})
        total = round(sum(s['estimated_seconds'] for s in rendered), 2)
        target = self.brief.get('target_seconds')
        if isinstance(target, bool) or not isinstance(target, (int, float)) or not math.isfinite(target) or target <= 0:
            issues.append({'code': 'MISSING_DURATION'})
        elif total > target:
            issues.append({'code': 'OVER_DURATION', 'seconds_over': round(total - target, 2)})
        revision = {'revision': len(self.revisions) + 1, 'script_id': fingerprint(script),
                    'title': script['title'], 'shots': rendered, 'estimated_total_seconds': total,
                    'target_seconds': target, 'passed': not issues, 'issues': issues}
        self.latest = revision
        self.revisions.append(revision)
        return {'ok': True, **revision}
