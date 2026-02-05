import os
import json
import re
import requests
from datetime import datetime, timezone, timedelta
from urllib.parse import quote

# ===== 설정 =====
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '8209005017:AAH1IOr7h49dI3lX2TSBNOrvMsQEIcHCouM')

# 뉴스 전용 채널 (동네뉴스) - 투자방과 분리!
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_NEWS_CHAT_ID', '-1003586903490')

# 모니터링 키워드
KEYWORDS = [
    'GTX-C',
    '석계역',
    '노원구 월계동',
    '월계동신아파트',
    '광운대역세권',
    '우이천',
    '중랑천',
    '동부간선도로',
    '내부순환도로',
    '북부간선도로',
    '노원구'
]

# 상태 저장 파일
NEWS_STATE_FILE = 'news_sent.json'


def search_daum_news(keyword):
    """다음뉴스에서 키워드 검색 (정규식 사용, 의존성 없음)"""
    url = f"https://search.daum.net/search?w=news&q={quote(keyword)}&sort=recency"
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'ko-KR,ko;q=0.9,en;q=0.8'
    }
    
    try:
        resp = requests.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
        html = resp.text
        
        articles = []
        
        # 다음 뉴스 검색 결과 패턴들
        # 패턴 1: data-tiara-layer 형식
        pattern1 = r'<a[^>]+class="[^"]*tit[^"]*"[^>]+href="([^"]+)"[^>]*>([^<]+)</a>'
        
        # 패턴 2: 뉴스 제목 링크 (일반)
        pattern2 = r'<a[^>]+href="(https?://[^"]*(?:v\.daum\.net|news\.daum\.net)[^"]*)"[^>]*>([^<]{10,100})</a>'
        
        # 패턴 3: 뉴스 제목 (클래스 없는 경우)
        pattern3 = r'"url":"(https?://[^"]*(?:v\.daum|news\.daum)[^"]*)"[^}]*"title":"([^"]{10,100})"'
        
        for pattern in [pattern1, pattern2, pattern3]:
            matches = re.findall(pattern, html, re.IGNORECASE | re.DOTALL)
            for url_match, title in matches[:10]:
                title = title.strip()
                title = re.sub(r'<[^>]+>', '', title)  # HTML 태그 제거
                title = title.replace('&quot;', '"').replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
                
                if len(title) > 5 and len(title) < 200:
                    articles.append({
                        'title': title[:100],
                        'url': url_match,
                        'keyword': keyword
                    })
        
        # 중복 제거
        seen = set()
        unique = []
        for art in articles:
            key = art['url']
            if key not in seen:
                seen.add(key)
                unique.append(art)
        
        print(f"  Found {len(unique)} articles")
        return unique[:5]
        
    except Exception as e:
        print(f"[NEWS] Error searching '{keyword}': {e}")
        return []


def load_news_state():
    """이전 상태 로드"""
    try:
        with open(NEWS_STATE_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return {'sent_urls': [], 'last_check': None}


def save_news_state(state):
    """상태 저장"""
    try:
        # 최근 500개 URL만 유지 (메모리 관리)
        state['sent_urls'] = state['sent_urls'][-500:]
        with open(NEWS_STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[State] Error saving: {e}")


def send_telegram(message):
    """텔레그램 메시지 발송"""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        'chat_id': TELEGRAM_CHAT_ID,
        'text': message,
        'parse_mode': 'HTML',
        'disable_web_page_preview': True  # 링크 미리보기 비활성화
    }
    
    try:
        resp = requests.post(url, json=payload, timeout=10)
        resp.raise_for_status()
        print("[Telegram] Message sent successfully")
        return True
    except Exception as e:
        print(f"[Telegram] Error: {e}")
        return False


def format_news_message(articles_by_keyword):
    """뉴스 메시지 포맷팅"""
    kst = timezone(timedelta(hours=9))
    now_kst = datetime.now(kst).strftime('%Y-%m-%d %H:%M KST')
    
    msg = "📰 <b>오늘의 뉴스 알림</b>\n"
    msg += f"━━━━━━━━━━━━━━━━━━━━━\n\n"
    
    total_count = 0
    
    for keyword, articles in articles_by_keyword.items():
        if articles:
            msg += f"🔍 <b>[{keyword}]</b>\n"
            for art in articles:
                title = art['title']
                if len(title) > 50:
                    title = title[:47] + '...'
                msg += f"  • {title}\n"
                msg += f"    🔗 {art['url']}\n"
                total_count += 1
            msg += "\n"
    
    if total_count == 0:
        msg += "오늘은 새 뉴스가 없습니다. 🤷\n"
    else:
        msg += f"━━━━━━━━━━━━━━━━━━━━━\n"
        msg += f"📊 총 <b>{total_count}건</b>의 새 뉴스\n"
    
    msg += f"⏰ {now_kst}"
    
    return msg


def main(mode='news'):
    """메인 함수"""
    print(f"[NEWS MONITOR] Running in {mode} mode...")
    
    # 상태 로드
    state = load_news_state()
    sent_urls = set(state.get('sent_urls', []))
    
    # 키워드별 뉴스 검색
    articles_by_keyword = {}
    new_articles = []
    
    for keyword in KEYWORDS:
        print(f"[NEWS] Searching '{keyword}'...")
        articles = search_daum_news(keyword)
        
        # 새 뉴스만 필터링
        new_for_keyword = []
        for art in articles:
            if art['url'] not in sent_urls:
                new_for_keyword.append(art)
                new_articles.append(art)
        
        if new_for_keyword:
            articles_by_keyword[keyword] = new_for_keyword
            print(f"  → {len(new_for_keyword)} new articles")
        else:
            print(f"  → No new articles")
    
    # 결과 출력
    print(f"\n[NEWS] Total new articles: {len(new_articles)}")
    
    if mode == 'test':
        # 테스트 모드: 발송 안 함
        print("[TEST MODE] Not sending telegram message")
        for keyword, articles in articles_by_keyword.items():
            print(f"\n[{keyword}]")
            for art in articles:
                print(f"  - {art['title']}")
                print(f"    {art['url']}")
        return
    
    # 뉴스 알림 발송 (하루 한 번 무조건!)
    msg = format_news_message(articles_by_keyword)
    send_telegram(msg)
    
    # 발송한 URL 저장
    if new_articles:
        for art in new_articles:
            sent_urls.add(art['url'])
        state['sent_urls'] = list(sent_urls)
    
    print(f"[NEWS] Sent daily news summary ({len(new_articles)} new articles)")
    
    # 상태 저장
    state['last_check'] = datetime.now(timezone.utc).isoformat()
    save_news_state(state)
    
    print("[NEWS MONITOR] Done!")


if __name__ == '__main__':
    import sys
    mode = sys.argv[1] if len(sys.argv) > 1 else 'news'
    main(mode)
