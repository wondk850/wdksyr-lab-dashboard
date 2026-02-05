"""
정보공개포털 (open.go.kr) 스크래퍼
Playwright 사용 - JavaScript 렌더링 지원
"""
import os
import json
import asyncio
from datetime import datetime, timezone, timedelta

# 텔레그램 설정
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '8209005017:AAH1IOr7h49dI3lX2TSBNOrvMsQEIcHCouM')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '1489387702')

# 키워드
KEYWORDS = [
    '수도권광역급행철도',
    'GTX-C',
    'gtx-c',
    '광운대',
    '광운대역',
    '석계역',
    '노원구',
    '월계동',
    '우이천',
    '중랑천',
    '동부간선도로',
    '동북권',
    'DBC',
    'dbc'
]

# 기관 유형
INST_TYPES = ['중앙행정기관', '광역자치단체', '기초자치단체', '교육청', '공공기관']

STATE_FILE = 'opengo_sent.json'


async def search_with_playwright(keyword):
    """Playwright로 정보공개포털 검색"""
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("[ERROR] playwright 설치 필요: pip install playwright && playwright install chromium")
        return []
    
    items = []
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        try:
            print(f"\n[검색] {keyword}...")
            
            # 페이지 로드
            await page.goto('https://www.open.go.kr/othicInfo/infoList/infoList.do', timeout=60000)
            await page.wait_for_load_state('networkidle', timeout=30000)
            
            # 검색어 입력
            search_input = await page.query_selector('input[name="searchWord"]')
            if search_input:
                await search_input.fill(keyword)
                await search_input.press('Enter') # 엔터키 입력
                await page.wait_for_load_state('networkidle', timeout=60000) # 타임아웃 60초
            else:
                print(f"  [오류] 검색창을 찾을 수 없음")
                
            # 검색 버튼 클릭 (백업)
            # search_btn = await page.query_selector('button.btn_search, a.btn_search, input[type="submit"]')
            # if search_btn:
            #     await search_btn.click()
            #     await page.wait_for_load_state('networkidle', timeout=30000)
            
            # 결과 테이블 찾기 (여러 테이블 중 결과 테이블 식별)
            tables = await page.query_selector_all('table')
            target_rows = []
            
            for table in tables:
                # 테이블 헤더 확인
                header_text = await table.inner_text()
                if "번호" in header_text and "공개정보" in header_text:
                    target_rows = await table.query_selector_all('tbody tr')
                    break
            
            if not target_rows:
                print("  [경고] 결과 테이블을 찾을 수 없음. 기본 테이블 사용 시도.")
                target_rows = await page.query_selector_all('table.tbl_type01 tbody tr') # 대안

            rows = target_rows
            print(f"  {len(rows)}개 행 발견 (결과 테이블)")
            
            for row in rows[:20]:  # 최대 20개
                try:
                    cols = await row.query_selector_all('td')
                    # 디버깅: 행 내용 출력
                    row_text = await row.inner_text()
                    print(f"    [Row] Cols: {len(cols)}, Text: {row_text.replace(chr(10), ' ')[:50]}...")
                    
                    if len(cols) >= 3:
                        title_el = await cols[1].query_selector('a')
                        title = await title_el.inner_text() if title_el else await cols[1].inner_text()
                        inst = await cols[2].inner_text() if len(cols) > 2 else ''
                        
                        title = title.strip()
                        inst = inst.strip()
                        
                        print(f"    -> 추출: {title} / {inst}")
                        
                        if title and "검색된 결과가 없습니다" not in title:
                            items.append({
                                'title': title,
                                'institution': inst,
                                'keyword': keyword
                            })
                except Exception as e:
                    print(f"    [Row Error] {e}")
                    continue
            
            print(f"  [결과] {len(items)}건 수집")
            
        except Exception as e:
            print(f"[오류] {keyword}: {e}")
        
        await browser.close()
    
    return items


def filter_by_keywords(items):
    """키워드 필터링"""
    filtered = []
    
    for item in items:
        title_lower = item['title'].lower()
        for kw in KEYWORDS:
            if kw.lower() in title_lower:
                item['matched_keyword'] = kw
                filtered.append(item)
                print(f"  ✓ [{kw}] {item['title'][:40]}...")
                break
    
    return filtered


def load_state():
    try:
        with open(STATE_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return {'sent_ids': [], 'last_check': None}


def save_state(state):
    try:
        state['sent_ids'] = state['sent_ids'][-500:]
        with open(STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[State] 오류: {e}")


def send_telegram(message):
    import requests
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        'chat_id': TELEGRAM_CHAT_ID,
        'text': message,
        'parse_mode': 'HTML',
        'disable_web_page_preview': True
    }
    try:
        resp = requests.post(url, json=payload, timeout=10)
        resp.raise_for_status()
        print("[Telegram] 발송 성공!")
        return True
    except Exception as e:
        print(f"[Telegram] 오류: {e}")
        return False


def format_message(items):
    kst = timezone(timedelta(hours=9))
    now_kst = datetime.now(kst).strftime('%Y-%m-%d %H:%M KST')
    
    msg = "📂 <b>정보공개포털 알림</b>\n"
    msg += f"━━━━━━━━━━━━━━━━━━━━━\n\n"
    
    if items:
        for item in items[:10]:
            title = item['title'][:45] + '...' if len(item['title']) > 45 else item['title']
            kw = item.get('matched_keyword', '')
            msg += f"🔍 <b>[{kw}]</b>\n"
            msg += f"• {title}\n"
            if item.get('institution'):
                msg += f"  🏢 {item['institution'][:20]}\n"
            msg += "\n"
    else:
        msg += "오늘은 키워드에 맞는 새 정보가 없습니다. 🤷\n\n"
    
    msg += f"━━━━━━━━━━━━━━━━━━━━━\n"
    msg += f"📊 총 <b>{len(items)}건</b>\n"
    msg += f"🔗 <a href='https://www.open.go.kr/othicInfo/infoList/infoList.do'>정보공개포털</a>\n"
    msg += f"⏰ {now_kst}"
    
    return msg


async def main_async(mode='opengo'):
    print(f"[정보공개포털] {mode} 모드 실행...")
    
    state = load_state()
    sent_ids = set(state.get('sent_ids', []))
    
    all_items = []
    
    # 각 키워드로 검색 (처음 5개만)
    for keyword in KEYWORDS[:5]:
        items = await search_with_playwright(keyword)
        all_items.extend(items)
    
    # 키워드 필터링
    filtered = filter_by_keywords(all_items)
    
    # 새 항목만
    new_items = []
    for item in filtered:
        item_id = f"{item['title']}_{item.get('institution', '')}"
        if item_id not in sent_ids:
            new_items.append(item)
            sent_ids.add(item_id)
    
    print(f"\n[신규] {len(new_items)}건")
    
    if mode == 'test':
        print("\n[테스트 모드] 텔레그램 발송 안 함")
        for item in new_items[:5]:
            print(f"  {item['title'][:50]}")
        return
    
    # 발송
    msg = format_message(new_items)
    send_telegram(msg)
    
    # 저장
    state['sent_ids'] = list(sent_ids)
    state['last_check'] = datetime.now(timezone.utc).isoformat()
    save_state(state)
    
    print("\n[완료!]")


def main(mode='opengo'):
    asyncio.run(main_async(mode))


if __name__ == '__main__':
    import sys
    mode = sys.argv[1] if len(sys.argv) > 1 else 'opengo'
    main(mode)
