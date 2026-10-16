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

    def test_firestore_titles_from_2026_10_16(self):
        cases = [
            ('애니메이션 『푸른 상자』 2기 첫 화', ['푸른 상자']),
            ('[입고완료] 젠레스존제로 빌리키드', ['젠레스 존 제로']),
            ('CS.FRONT 나혼자만 레벨업 마루토', ['나 혼자만 레벨업']),
            ('FULL SCALE WORKS 코드기아스 반역의 를르슈', ['코드 기아스']),
            ('풀스케일웍스 코드기어스 제로의가면', ['코드 기아스']),
            ('넨도로이드모어 걸즈앤판처 티거I', ['걸즈 앤 판처']),
            ('팝업퍼레이드 니어시리즈15주년 애니버서리 2B', ['니어 오토마타']),
            ('신세기GPX 사이버포뮬러 아스라다', ['신세기 GPX 사이버 포뮬러']),
            ('붕괴3 키아나 종언의 율자', ['붕괴3rd']),
            ('쁘띠라마DX 신고지라(2016)', ['고질라']),
            ('PV237 사사키와피짱 엘자', ['사사키와 피짱']),
            ('은하특급 밀키서브웨이 후와코로린', ['은하특급 밀키 서브웨이']),
            ('아주르 프로밀리아 2차 창작', ['어쥬르 프로밀리아']),
            ('세나 리버스 귀칼 2차 컬래버', ['귀멸의 칼날', '세븐나이츠 리버스']),
            ('ヘラグ Gala Night Ver.', ['명일방주']),
            ('河原木 桃香', ['학원 아이돌마스터']),
            ('インプラカブル Special Ver.', ['벽람항로']),
            ('마징엠페러G 스카이X스튜디오', ['마징가 Z']),
            ('30MP 鹿目まどか ワルプルギス', ['마법소녀 마도카☆마기카']),
            ('イーヴィルティガ 限定版', ['울트라맨']),
            ('S14の「ドロンジョ」', ['야터맨']),
            ('VF-11B サンダーボルト', ['마크로스']),
            ('SEED FREEDOM ZEROのフェア', ['기동전사 건담']),
            ('프린세스커넥트 ReDive 페코린느 프리코네', ['프린세스 커넥트! Re:Dive']),
            ('페르소나 P30th 주인공 키홀더 P3', ['페르소나 3']),
            ('페르소나 P30th 주인공 키홀더 P5', ['페르소나 5']),
            ('『FFVII』 티파 코스프레', ['FINAL FANTASY']),
            ('儒烏風亭らでん商品発売', ['홀로라이브']),
            ('『〈物語〉シリーズ』くじメイト', ['모노가타리 시리즈']),
            ('데이브 더 다이버x서브노티카 2 컬래버', ['데이브 더 다이버', '서브노티카']),
            ('스카디 더 커럽팅 하트', ['명일방주']),
            ('명일방주 엔드필드 큐티시리즈', ['명일방주', '명일방주: 엔드필드']),
        ]
        for title, expected in cases:
            with self.subTest(title=title):
                self.assertEqual(match_works({'title': title}, self.compiled), expected)

    def test_title_ko_supplies_dragon_quest(self):
        self.assertEqual(match_works(
            {'title': 'タイトー、10月展開予定の関連プライズ',
             'titleKo': '타이토가 10월 드래곤 퀘스트 관련 상품 5개를 공개합니다!'},
            self.compiled), ['드래곤 퀘스트'])

    def test_ambiguous_names_and_notices_remain_unclassified(self):
        for title in ('AGF KOREA 2025 스폰서 공개', '태그검색',
                      '마키나', '카이', '티아', '블랙 스완', 'ブラックスワン',
                      '네이티브 사랑과 번영의 천사 프리엘 by 마타로',
                      '여름의소녀 by 네코미', 'SWC2026 유럽 컵',
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
