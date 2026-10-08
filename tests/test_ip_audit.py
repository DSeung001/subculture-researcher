"""Offline regressions for the IP gaps found in the 2026-10-08 public snapshot."""
import importlib.util
from pathlib import Path
import unittest

from subculture.library.application.catalog import load_catalog
from subculture.library.domain.keywords import compile_works, match_works

SCRIPT = Path(__file__).resolve().parents[1] / '.agents/skills/audit-ip-matching/scripts/audit_ip.py'
spec = importlib.util.spec_from_file_location('audit_ip', SCRIPT)
audit_ip = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit_ip)


class CatalogGapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.compiled = compile_works(load_catalog())

    def test_real_missing_titles(self):
        cases = [
            ('쵸코푸니봉제인형 고깔모자의아틀리에 코코', ['고깔모자의 아틀리에']),
            ('코토부키야 마법기사레이어스 시도우히카루', ['마법기사 레이어스']),
            ('후류 비큐트바니 딸기100 토죠아야', ['딸기 100%']),
            ('세레니엘 복각, 카제나 시즌 5 프롤로그 스토리 공개', ['카오스 제로 나이트메어']),
            ('이환, 신규 지역 푸카 파라다이스 업데이트', ['NTE']),
            ('넨도로이드 3149 마남이치', ['마남 이치']),
            ('Qset 해즈빈호텔 알래스터', ['해즈빈 호텔']),
            ('다이블로스코어 울리안 해질녘 해변 ver.', ['다이블로스 코어']),
            ('선드롭 아스트랄파티 낸시루', ['아스트랄 파티']),
            ('니지산지KR 양나리 DMM', ['니지산지']),
            ('銀河特急 ミルキー☆サブウェイ マキナ', ['은하특급 밀키 서브웨이']),
            ('은하특급밀키서브웨이 마키나 코토부키야', ['은하특급 밀키 서브웨이']),
            ('Chill with You : Lo-Fi Story 사토네', ['Chill with You: Lo-Fi Story']),
            ('Chill with You Lo-Fi Story 사토네', ['Chill with You: Lo-Fi Story']),
            ('星のカービィ チョコボックス', ['별의 커비']),
            ('「俺ガイル」一色いろは 原作Ver.', ['역시 내 청춘 러브코메디는 잘못됐다']),
            ('トイライズ グランゾート', ['마동왕 그랑조트']),
            ('スイプリ＆まほプリの新商品', ['프리큐어']),
            ('ニューカニの新商品', ['NU:카니발']),
            ('アズールプロミリア キャスベル', ['어쥬르 프로밀리아']),
            ('모데로이드 티타노마키아 SIDE:R 포겔그', ['티타노마키아']),
        ]
        for title, expected in cases:
            with self.subTest(title=title):
                self.assertEqual(match_works({'title': title}, self.compiled), expected)

    def test_collaborations_keep_every_work(self):
        self.assertEqual(set(match_works(
            {'title': '라인게임즈 대항해시대 오리진, 창세기전과 협업'}, self.compiled)),
            {'대항해시대 오리진', '창세기전'})
        self.assertEqual(set(match_works(
            {'title': '팬텀 블레이드 제로·콜옵 등 대작 쏟아진다'}, self.compiled)),
            {'팬텀 블레이드 제로', '콜 오브 듀티'})

    def test_display_title_can_supply_missing_ip(self):
        self.assertEqual(match_works({'title': 'New goods', 'titleKo': '별의 커비 굿즈'},
                                     self.compiled), ['별의 커비'])

    def test_ambiguous_names_and_notices_remain_unclassified(self):
        for title in ('AGF KOREA 2025 스폰서 공개', '태그검색',
                      '마키나', '카이', '티아', '블랙 스완',
                      '네이티브 사랑과 번영의 천사 프리엘 by 마타로',
                      'HAKUBAのレンズフィルター', 'DTFTX 대회'):
            with self.subTest(title=title):
                self.assertEqual(match_works({'title': title}, self.compiled), [])


class AuditHelperTests(unittest.TestCase):
    def test_site_snapshot_is_rematched_without_using_stale_works_or_metadata(self):
        payload = {'items': [
            {'id': 'GOODS:one', 'source': 'IP', 'works': ['stale'],
             'view': {'original_title': '', 'title_text': 'IP 굿즈', 'url': 'https://example.com'}},
            {'id': 'GOODS:two', 'source': 'IP', 'works': ['IP'],
             'view': {'original_title': '일반 공지', 'title_text': '공지', 'url': 'https://example.com/IP'}},
        ]}
        result = audit_ip.audit(audit_ip.site_records(payload), [{'name': 'IP'}])
        self.assertEqual(result['total'], 2)
        self.assertEqual(result['unclassified'], 1)
        self.assertEqual(result['items'][0]['works'], ['IP'])
        self.assertEqual(result['missing'][0]['id'], 'GOODS:two')
        # Reusing a saved report must also replace the old match sets.
        again = audit_ip.audit(result['items'], [{'name': '일반 공지'}])
        self.assertEqual(again['items'][0]['works'], [])
        self.assertEqual(again['items'][1]['works'], ['일반 공지'])


if __name__ == '__main__':
    unittest.main()
