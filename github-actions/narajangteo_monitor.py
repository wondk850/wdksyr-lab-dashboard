import os
import json
import requests
from datetime import datetime, timezone, timedelta

# ===== 설정 =====
# data.go.kr API 키 (사전규격, 입찰공고 모두 동일)
API_KEY = os.environ.get('NARAJANGTEO_API_KEY', '')

# 텔레그램 설정
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '8209005017:AAH1IOr7h49dI3lX2TSBNOrvMsQEIcHCouM')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '1489387702')

# ===== 키워드 (제목에서 필터링) =====
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

# 상태 저장 파일
STATE_FILE = 'narajangteo_sent.json'


def get_kst_dates(days_back=7):
    """KST 기준 날짜 범위 반환"""
    kst = timezone(timedelta(hours=9))
    today = datetime.now(kst)
    start = (today - timedelta(days=days_back)).strftime('%Y%m%d') + '0000'
    end = today.strftime('%Y%m%d') + '2359'
    return start, end


def search_bid_announcements():
    """입찰공고 검색 (공공데이터개방표준서비스)"""
    if not API_KEY:
        print("[ERROR] API_KEY not set!")
        return []
    
    start_date, end_date = get_kst_dates(7)
    
    url = "https://apis.data.go.kr/1230000/ao/PubDataOpnStdService/getDataSetOpnStdBidPblancInfo"
    params = {
        'serviceKey': API_KEY,
        'pageNo': '1',
        'numOfRows': '100',
        'bidNtceBgnDt': start_date,
        'bidNtceEndDt': end_date,
        'type': 'json'
    }
    
    try:
        print(f"[입찰공고] 조회: {start_date} ~ {end_date}")
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        
        items = extract_items(data)
        print(f"[입찰공고] {len(items)}건 조회됨")
        return items
    except Exception as e:
        print(f"[입찰공고] 오류: {e}")
        return []


def search_pre_specifications():
    """사전규격 공사 검색 (사전규격정보서비스)"""
    if not API_KEY:
        print("[ERROR] API_KEY not set!")
        return []
    
    start_date, end_date = get_kst_dates(7)
    
    url = "https://apis.data.go.kr/1230000/ao/HrcspSsstndrdInfoService/getPublicPrcureThngInfoCnstwk"
    params = {
        'serviceKey': API_KEY,
        'pageNo': '1',
        'numOfRows': '100',
        'inqryDiv': '1',  # 1: 등록일시
        'inqryBgnDt': start_date[:8],  # YYYYMMDD
        'inqryEndDt': end_date[:8],
        'type': 'json'
    }
    
    try:
        print(f"[사전규격 공사] 조회: {start_date[:8]} ~ {end_date[:8]}")
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        
        items = extract_items(data)
        print(f"[사전규격 공사] {len(items)}건 조회됨")
        return items
    except Exception as e:
        print(f"[사전규격 공사] 오류: {e}")
        return []


def search_pre_specifications_servc():
    """사전규격 용역 검색"""
    if not API_KEY:
        return []
    
    start_date, end_date = get_kst_dates(7)
    
    url = "https://apis.data.go.kr/1230000/ao/HrcspSsstndrdInfoService/getPublicPrcureThngInfoServc"
    params = {
        'serviceKey': API_KEY,
        'pageNo': '1',
        'numOfRows': '100',
        'inqryDiv': '1',
        'inqryBgnDt': start_date[:8],
        'inqryEndDt': end_date[:8],
        'type': 'json'
    }
    
    try:
        print(f"[사전규격 용역] 조회...")
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        
        items = extract_items(data)
        print(f"[사전규격 용역] {len(items)}건 조회됨")
        return items
    except Exception as e:
        print(f"[사전규격 용역] 오류: {e}")
        return []


def extract_items(data):
    """API 응답에서 items 추출"""
    if 'response' not in data:
        return []
    
    response = data['response']
    header = response.get('header', {})
    
    if header.get('resultCode') != '00':
        print(f"  API 오류: {header.get('resultMsg', 'Unknown')}")
        return []
    
    body = response.get('body', {})
    items = body.get('items', [])
    
    if isinstance(items, dict):
        items = items.get('item', [])
        if isinstance(items, dict):
            items = [items]
    
    return items if items else []


def filter_by_keywords(items, source_type):
    """키워드로 필터링 + 링크 생성"""
    filtered = []
    
    for item in items:
        # 제목 가져오기 (API마다 필드명 다름)
        title = (item.get('bidNtceNm') or 
                 item.get('prdctNm') or 
                 item.get('bfSpecRgstNo') or '')
        
        if not title:
            continue
        
        # 키워드 매칭 (대소문자 무시)
        title_lower = title.lower()
        matched_keyword = None
        for keyword in KEYWORDS:
            if keyword.lower() in title_lower:
                matched_keyword = keyword
                break
        
        if not matched_keyword:
            continue
        
        # 공통 정보 추출
        bid_no = item.get('bidNtceNo') or item.get('bfSpecRgstNo') or ''
        institution = item.get('ntceInsttNm') or item.get('rlDminsttNm') or item.get('dminsttNm') or ''
        
        # 가격
        price = item.get('presmptPrce') or item.get('asignBdgtAmt') or ''
        
        # 상세페이지 URL 생성
        if source_type == '입찰공고':
            detail_url = item.get('bidNtceDtlUrl') or ''
            if not detail_url and bid_no:
                detail_url = f"https://www.g2b.go.kr/pt/menu/selectSubFrame.do?framesrc=/pt/menu/frameTgong.do?url=https://www.g2b.go.kr:8101/ep/tbid/tbidList.do?bidNm={bid_no}"
        else:
            # 사전규격 URL
            detail_url = item.get('specDocFileUrl1') or ''
            if not detail_url and bid_no:
                detail_url = f"https://www.g2b.go.kr/pt/menu/selectSubFrame.do?framesrc=/pt/menu/frameTgong.do?url=https://www.g2b.go.kr:8101/ep/preparation/prestd/preStdSrch.do?preStdRgstNo={bid_no}"
        
        filtered.append({
            'source': source_type,
            'title': title,
            'bid_no': bid_no,
            'institution': institution,
            'price': price,
            'url': detail_url,
            'keyword': matched_keyword
        })
    
    return filtered


def load_state():
    """상태 로드"""
    try:
        with open(STATE_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return {'sent_ids': [], 'last_check': None}


def save_state(state):
    """상태 저장"""
    try:
        state['sent_ids'] = state['sent_ids'][-1000:]
        with open(STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[State] 저장 오류: {e}")


def format_price(price):
    """가격 포맷팅"""
    if not price:
        return ""
    try:
        price_num = int(float(price))
        if price_num >= 100000000:
            return f"{price_num / 100000000:.1f}억원"
        elif price_num >= 10000:
            return f"{price_num / 10000:.0f}만원"
        else:
            return f"{price_num:,}원"
    except:
        return ""


def send_telegram(message):
    """텔레그램 발송"""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        'chat_id': TELEGRAM_CHAT_ID,
        'text': message,
        'parse_mode': 'HTML',
        'disable_web_page_preview': False  # 링크 미리보기 활성화
    }
    
    try:
        resp = requests.post(url, json=payload, timeout=10)
        resp.raise_for_status()
        print("[Telegram] 발송 성공!")
        return True
    except Exception as e:
        print(f"[Telegram] 오류: {e}")
        return False


def format_message(results):
    """메시지 포맷팅"""
    kst = timezone(timedelta(hours=9))
    now_kst = datetime.now(kst).strftime('%Y-%m-%d %H:%M KST')
    
    msg = "🏛️ <b>나라장터 알림</b>\n"
    msg += f"━━━━━━━━━━━━━━━━━━━━━\n\n"
    
    # 사전규격 먼저
    pre_specs = [r for r in results if '사전규격' in r['source']]
    bids = [r for r in results if r['source'] == '입찰공고']
    
    if pre_specs:
        msg += "📋 <b>[사전규격]</b>\n"
        for item in pre_specs[:5]:  # 최대 5개
            title = item['title'][:45] + '...' if len(item['title']) > 45 else item['title']
            msg += f"• {title}\n"
            if item['institution']:
                inst = item['institution'][:15] + '...' if len(item['institution']) > 15 else item['institution']
                msg += f"  🏢 {inst}"
                price_str = format_price(item['price'])
                if price_str:
                    msg += f" | 💰 {price_str}"
                msg += "\n"
            if item['url']:
                msg += f"  🔗 {item['url']}\n"
        msg += "\n"
    
    if bids:
        msg += "📢 <b>[입찰공고]</b>\n"
        for item in bids[:5]:  # 최대 5개
            title = item['title'][:45] + '...' if len(item['title']) > 45 else item['title']
            msg += f"• {title}\n"
            if item['institution']:
                inst = item['institution'][:15] + '...' if len(item['institution']) > 15 else item['institution']
                msg += f"  🏢 {inst}"
                price_str = format_price(item['price'])
                if price_str:
                    msg += f" | 💰 {price_str}"
                msg += "\n"
            if item['url']:
                msg += f"  🔗 {item['url']}\n"
        msg += "\n"
    
    if not results:
        msg += "오늘은 키워드에 맞는 새 공고가 없습니다. 🤷\n\n"
    
    msg += f"━━━━━━━━━━━━━━━━━━━━━\n"
    msg += f"📊 총 <b>{len(results)}건</b> (사전규격 {len(pre_specs)}건, 입찰 {len(bids)}건)\n"
    msg += f"🔍 키워드: GTX-C, 광운대, 석계, 노원구...\n"
    msg += f"⏰ {now_kst}"
    
    return msg


def main(mode='bid'):
    """메인"""
    print(f"[나라장터 모니터] {mode} 모드 실행...")
    
    # 상태 로드
    state = load_state()
    sent_ids = set(state.get('sent_ids', []))
    
    # API 호출 (입찰공고 + 사전규격 공사 + 사전규격 용역)
    all_items = []
    
    bid_items = search_bid_announcements()
    filtered_bids = filter_by_keywords(bid_items, '입찰공고')
    all_items.extend(filtered_bids)
    
    pre_cnstwk = search_pre_specifications()
    filtered_cnstwk = filter_by_keywords(pre_cnstwk, '사전규격 공사')
    all_items.extend(filtered_cnstwk)
    
    pre_servc = search_pre_specifications_servc()
    filtered_servc = filter_by_keywords(pre_servc, '사전규격 용역')
    all_items.extend(filtered_servc)
    
    print(f"\n[필터링 결과] 총 {len(all_items)}건")
    
    # 새 항목만 필터링
    new_items = []
    for item in all_items:
        item_id = f"{item['source']}_{item['bid_no']}"
        if item_id not in sent_ids:
            new_items.append(item)
            print(f"  [NEW] [{item['source']}] {item['title'][:40]}...")
    
    print(f"\n[신규] {len(new_items)}건")
    
    if mode == 'test':
        print("\n[테스트 모드] 텔레그램 발송 안 함")
        for item in new_items:
            print(f"\n[{item['source']}] {item['title']}")
            print(f"  기관: {item['institution']}")
            print(f"  URL: {item['url']}")
        return
    
    # 메시지 발송
    msg = format_message(new_items)
    send_telegram(msg)
    
    # 상태 저장
    for item in new_items:
        item_id = f"{item['source']}_{item['bid_no']}"
        sent_ids.add(item_id)
    
    state['sent_ids'] = list(sent_ids)
    state['last_check'] = datetime.now(timezone.utc).isoformat()
    save_state(state)
    
    print("\n[완료!]")


if __name__ == '__main__':
    import sys
    mode = sys.argv[1] if len(sys.argv) > 1 else 'bid'
    main(mode)
