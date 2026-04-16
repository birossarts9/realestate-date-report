import streamlit as st
import pandas as pd
import plotly.express as px
import re
import gspread
import os
import glob
import json
from datetime import datetime, timedelta, timezone
import requests
import threading
from streamlit_gsheets import GSheetsConnection
import streamlit.components.v1 as components
from oauth2client.service_account import ServiceAccountCredentials
import json
from PIL import Image, ImageDraw, ImageFont
import io

# 1. 시트 접근 권한 설정
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]

# 2. 파일 대신 st.secrets(금고)에서 키 뭉치를 가져오기
creds_dict = st.secrets["gcp_service_account"]
creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)

# 3. 인증 진행
client = gspread.authorize(creds)

# 첫 실행 여부 확인을 위한 가드
if 'is_initialized' not in st.session_state:
    st.session_state['is_initialized'] = False

# --- [2] 비밀 장부(JSON) 로드 로직 ---
def load_realtor_map():
    if os.path.exists("realtors.json"):
        with open("realtors.json", "r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except Exception:
                pass
    # 파일이 없거나 에러 시 최소한의 demo 데이터 반환
    return {"demo": {"name": "체험용 부동산", "complexes": ["다산e편한세상자이", "힐스테이트다산", "다산한양수자인리버팰리스"]}}

REALTOR_MAP = load_realtor_map()

# URL 파라미터 인식
query_params = st.query_params
user_id = query_params.get("id", "demo")
ref_id = query_params.get("ref", "unknown")
tracking_id = f"user:{user_id}_ref:{ref_id}"

# 💡 [핵심 안전장치] URL로 들어온 id가 realtors.json에 아예 없으면 무조건 'demo'로 강제 고정!
if user_id not in REALTOR_MAP:
    user_id = "demo"

# --- 🚀 데모 모드 데이터 매핑 로직 ---
IS_DEMO_MODE = (user_id == "demo")

# 최종 확정된 user_id로 부동산 정보 세팅
current_realtor = REALTOR_MAP.get(user_id)

if isinstance(current_realtor, dict):
    filter_realtor_name = current_realtor.get("name", "체험용 부동산")
    target_complexes = current_realtor.get("complexes", [])
else:
    filter_realtor_name = str(current_realtor)
    target_complexes = []

raw_demo = REALTOR_MAP.get("demo", {"name": "체험용 부동산"})
demo_name = raw_demo.get("name", "체험용 부동산") if isinstance(raw_demo, dict) else str(raw_demo)
display_realtor = demo_name if IS_DEMO_MODE else filter_realtor_name

def mask_text(text, is_agent=False):
    if not IS_DEMO_MODE: return text
    if is_agent:
        if filter_realtor_name in str(text): return display_realtor
        stable_id = sum(ord(c) * (i + 1) for i, c in enumerate(str(text))) % 1000
        return f"경쟁사 {stable_id:03d}"
    return re.sub(r'\d', '*', str(text))

# --- 1. 웹사이트 기본 세팅 및 UI 스타일링 ---
st.set_page_config(
    page_title="TOP RANK 솔루션 | 프리미엄 부동산 자동화",
    page_icon="LOGO.png", # 👑 대신 로고 파일명 입력
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
<style>
button[data-baseweb="tab"] {
    transition: all 0.3s ease !important;
}
button[data-baseweb="tab"]:hover {
    background-color: #f0f7ff !important;
    transform: translateY(-2px);
}
button[data-baseweb="tab"] p {
    font-size: 20px !important;
    font-weight: bold !important;
}
.strategy-grid {
    display: flex;
    gap: 20px;
    margin-top: 30px;
    margin-bottom: 25px;
    flex-wrap: wrap;
}
.briefing-strategy-card {
    background-color: white;
    padding: 25px;
    border-radius: 20px;
    border: 1px solid #e2e8f0;
    flex: 1;
    min-width: 300px;
    transition: all 0.3s ease;
}
.briefing-strategy-card:hover {
    border-color: #3182f6;
    transform: translateY(-5px);
    box-shadow: 0 10px 20px rgba(49, 130, 246, 0.08);
}
.strategy-tag {
    display: inline-block;
    padding: 5px 14px;
    border-radius: 10px;
    font-size: 14px;
    font-weight: 800;
    margin-bottom: 15px;
    color: white;
}
.briefing-content {
    font-size: 21px !important;
    line-height: 1.8 !important;
    font-weight: 600 !important;
    color: #334155;
}
.pricing-card {
    position: relative; padding: 25px 15px; border-radius: 20px; background-color: white;
    border: 1px solid #e5e8eb; box-shadow: 0 10px 20px rgba(0,0,0,0.03); text-align: center;
    height: 100%; transition: all 0.3s ease; cursor: default; margin-top: 15px;
}
.pricing-card:hover {
    transform: translateY(-10px) scale(1.03);
    border: 2px solid #3182f6 !important;
    box-shadow: 0 20px 35px rgba(49, 130, 246, 0.12);
}
@keyframes shimmerBg {
    0% { background-position: 200% 0; }
    100% { background-position: -200% 0; }
}
@keyframes borderPulse {
    0% { border-color: rgba(49, 130, 246, 0.3); box-shadow: 0 0 15px rgba(49, 130, 246, 0.1); }
    50% { border-color: rgba(49, 130, 246, 1); box-shadow: 0 0 25px rgba(49, 130, 246, 0.5); }
    100% { border-color: rgba(49, 130, 246, 0.3); box-shadow: 0 0 15px rgba(49, 130, 246, 0.1); }
}
.focus-card {
    transform: scale(1.05);
    z-index: 5;
    border: 2px solid #3182f6;
    background: linear-gradient(120deg, #ffffff 30%, #eef2ff 50%, #ffffff 70%);
    background-size: 200% 100%;
    animation: shimmerBg 3s infinite linear, borderPulse 2s infinite ease-in-out;
}
.focus-card:hover { transform: translateY(-10px) scale(1.08) !important; }
div[data-baseweb="select"] > div {
    transition: all 0.3s ease !important;
}
div[data-baseweb="select"] > div:hover {
    border-color: #3182f6 !important;
    box-shadow: 0 0 8px rgba(49, 130, 246, 0.2) !important;
}
.stDateInput > div > div > input:hover, .stTimeInput > div > div > input:hover {
    border-color: #3182f6 !important;
    transition: all 0.3s ease !important;
}
[data-testid="stDataFrame"] {
    transition: all 0.3s ease !important;
    border-radius: 10px;
}
[data-testid="stDataFrame"]:hover {
    box-shadow: 0 5px 15px rgba(0,0,0,0.06) !important;
}
div[data-testid="stExpander"] summary p {
    font-size: 18px !important;
    font-weight: 700 !important;
}
div[data-testid="stExpander"] {
    margin-bottom: 20px !important;
}

div[data-testid="stRadio"] label {
    align-items: center !important; /* 동그라미와 텍스트를 수직 중앙으로 완벽하게 정렬 */
}
div[data-testid="stRadio"] label p {
    font-size: 24px !important;
    font-weight: 900 !important;
    color: #1e3a8a !important;
    padding: 0px 10px !important; /* 위아래 패딩을 지워 아래로 처지는 현상 차단 */
    margin: 0 !important; 
    line-height: 1.2 !important; /* 줄 간격 최적화 */
    transition: all 0.2s ease !important;
}
div[data-testid="stRadio"] label p:hover {
    color: #3182f6 !important;
}
div[data-testid="stRadio"] > div {
    gap: 30px !important;
    flex-wrap: wrap !important;
    padding-bottom: 10px !important;
    align-items: center !important;
}
</style>
""", unsafe_allow_html=True)

# --- 3. 유틸리티 함수 ---
@st.cache_data(ttl=600, max_entries=1, show_spinner=False)
def load_renewal_logs():
    try:
        SHEET_ID = "1yEllJWWNwsd5FMvvgwSIvA46j10XU_8MxpRAWcs-ba8"
        doc = client.open_by_key(SHEET_ID)
        df_exec = pd.DataFrame(doc.worksheet("실행로그").get_all_values())
        return df_exec
    except Exception as e:
        st.error(f"시트 데이터를 불러오지 못했습니다: {e}")
        return pd.DataFrame()

def clean_realtor_name(name):
    pattern = r'공인중개사사무소|공인중개사|중개사무소|부동산|중개사|공인|중개|사무소'
    cleaned = re.sub(pattern, '', str(name))
    
    # ⭐ [핵심 추가] 글자 사이의 모든 띄어쓰기(공백)를 흔적도 없이 날려버립니다.
    cleaned = re.sub(r'\s+', '', cleaned)
    
    return cleaned if cleaned else str(name)

@st.cache_data(max_entries=1, show_spinner=False)
def process_data(df):
    df['수집일시'] = pd.to_datetime(df['수집일시'])
    
    # ⭐ [핵심 해결] 전체 시간이 아닌 '단지명' 기준으로 먼저 정렬합니다.
    df = df.sort_values(['단지명', '수집일시'])
    
    # ⭐ '같은 단지' 내에서 앞뒤 데이터의 시간 차이를 계산합니다.
    time_diff_mins = df.groupby('단지명')['수집일시'].diff().dt.total_seconds() / 60.0
    
    # 간격이 40분 이상 차이나면 새로운 세션(회차)으로 간주합니다.
    df['새_세션'] = (time_diff_mins > 40) | time_diff_mins.isna()
    
    # 단지별로 1회차, 2회차 세션 번호를 매깁니다.
    df['세션ID'] = df.groupby('단지명')['새_세션'].cumsum()
    
    # 각 단지의 세션별 대표 시간을 구해서 오차를 통일시킵니다.
    session_rep = df.groupby(['단지명', '세션ID'])['수집일시'].min().dt.floor('min').reset_index(name='대표수집일시')
    df = pd.merge(df, session_rep, on=['단지명', '세션ID'], how='left')
    df['수집일시'] = df['대표수집일시']
    
    # 전체 데이터를 다시 시간순으로 정렬하여 차트가 정상적으로 그려지게 합니다.
    df = df.sort_values('수집일시')
    
    # (이하 기존 왜곡 영역 및 파싱 로직 동일 유지)
    session_times = df['수집일시'].drop_duplicates().sort_values()
    gap_check = session_times.diff().dt.total_seconds() / 3600.0
    gap_starts = session_times[gap_check > 2.5].tolist()

    df['왜곡영역'] = False
    for start_time in gap_starts:
        df.loc[(df['수집일시'] >= start_time) & (df['수집일시'] < start_time + timedelta(hours=1)), '왜곡영역'] = True
        
    df['전체순위_숫자'] = pd.to_numeric(df['전체순위'].astype(str).str.replace(r'[^0-9]', '', regex=True), errors='coerce').fillna(999).astype(int)
    df['묶음내순위_숫자'] = pd.to_numeric(df['묶음내순위'].astype(str).str.replace('단독', '1').str.replace(r'[^0-9]', '', regex=True), errors='coerce').fillna(999).astype(int)
    
    for col in ['동/호수', '층/타입', '거래방식', '가격']:
        if col in df.columns: 
            df[col] = df[col].fillna("")
            
    df['확인일자'] = df['확인일자'].apply(lambda x: str(x).strip() if pd.notna(x) else pd.NA)
    df['확인일자_Date'] = pd.to_datetime(df['확인일자'], format='%y.%m.%d', errors='coerce')

    if '고유번호' not in df.columns:
        df['고유번호'] = '기록없음'
    df['고유번호'] = df['고유번호'].fillna('기록없음')

    def make_bundle_key(row):
        return f"{row['동/호수']} | {row['층/타입']} | {row['거래방식']} | {row['가격']}"
        
    df['매물묶음키'] = df.apply(make_bundle_key, axis=1)
    return df

@st.cache_data(ttl=600, max_entries=1, show_spinner=False)
def load_server_data():
    current_dir = os.path.dirname(os.path.abspath(__file__))
    KST = timezone(timedelta(hours=9))
    now = datetime.now(KST)
    base_names = []

    # 1. 이번 달 데이터 이름 (확장자 제외)
    base_names.append(f"naver_market_report_{now.strftime('%Y_%m')}")
    
    # 2. 지난 달 데이터 (15일 이전인 경우)
    if now.day <= 15:
        last_month = now.replace(day=1) - timedelta(days=1)
        base_names.append(f"naver_market_report_{last_month.strftime('%Y_%m')}")
        
    # 3. 구형 데이터 (data)
    base_names.append("data")
        
    df_list = []
    for base_name in base_names:
        parquet_path = os.path.join(current_dir, f"{base_name}.parquet")
        excel_path = os.path.join(current_dir, f"{base_name}.xlsx")
        
        try:
            # 💡 핵심: 파케이 파일이 존재하면 초고속으로 읽고, 없으면 엑셀을 읽습니다.
            if os.path.exists(parquet_path):
                df = pd.read_parquet(parquet_path)
                df_list.append(df)
            elif os.path.exists(excel_path):
                df = pd.read_excel(excel_path)
                df_list.append(df)
        except Exception:
            pass 
                
    if not df_list:
        return None
        
    df = pd.concat(df_list, ignore_index=True).drop_duplicates()
    cutoff_date = pd.to_datetime('today') - pd.Timedelta(days=7)   # 🚨 긴급 조치: 30일 -> 7일로 축소
    df['수집일시'] = pd.to_datetime(df['수집일시'])
    df = df[df['수집일시'] >= cutoff_date]
    
    # 💡 덤으로 메모리 찌꺼기 즉각 청소 (선택사항)
    import gc
    del df_list
    gc.collect()
    
    return df

def generate_kakao_report_image(realtor_name, top_count, top_avg, mid_count, mid_avg, low_count, low_avg, selected_days, my_ranks_dict, top_comp_list, item_data):
    from PIL import Image, ImageDraw, ImageFont
    import io

    # 1. 도화지 세팅 (매물 5개 기준, 동적 세로 길이 계산)
    base_height = 820
    for key in ["top", "mid", "low"]:
        base_height += 85  # 카드 타이틀 여백
        items = item_data.get(key, [])[:5] 
        base_height += len(items) * 85 if items else 60
        base_height += 30  # 카드 하단 여백

    width = 1000
    height = base_height + 50
    img = Image.new('RGB', (width, height), color=(248, 250, 252)) 
    draw = ImageDraw.Draw(img)
    
    # 폰트 세팅 (나눔고딕 고정)
    try:
        f_title = ImageFont.truetype("NanumGothic.ttf", 52) 
        f_desc = ImageFont.truetype("NanumGothic.ttf", 26)  
        f_tier_title = ImageFont.truetype("NanumGothic.ttf", 28)
        f_tier_num = ImageFont.truetype("NanumGothic.ttf", 44)
        f_label = ImageFont.truetype("NanumGothic.ttf", 24)
        f_small = ImageFont.truetype("NanumGothic.ttf", 20)
        f_badge = ImageFont.truetype("NanumGothic.ttf", 18) 
    except:
        f_title = f_desc = f_tier_title = f_tier_num = f_label = f_small = f_badge = ImageFont.load_default()

    # ------------------------------------------------------
    # [헤더 영역] - 글자 폭에 맞춰 TOP RANK AI 박스 자동 연장
    # ------------------------------------------------------
    draw.rounded_rectangle([(40, 40), (960, 240)], radius=25, fill=(37, 99, 235))
    
    # 마스터 대시보드 제목
    t1 = "마스터 대시보드"
    t1w = draw.textlength(t1, font=f_title)
    draw.text(((width - t1w) / 2, 75), t1, font=f_title, fill=(255, 255, 255))
    
    # TOP RANK AI 뱃지 (글자 폭 계산하여 완벽하게 감싸기)
    badge_text = "TOP RANK AI"
    bw = draw.textlength(badge_text, font=f_badge)
    draw.rounded_rectangle([(960 - bw - 40, 75), (960, 120)], radius=22, fill=(60, 130, 246))
    draw.text((960 - bw - 20, 86), badge_text, font=f_badge, fill=(255, 255, 255))
    
    # 서브 텍스트
    d1 = f"네이버 부동산 실시간 분석 : {realtor_name} 전용 리포트"
    d2 = "매물 등급별 AI 처방에 맞춰 광고비를 스마트하게 지출하세요."
    d1w = draw.textlength(d1, font=f_desc)
    d2w = draw.textlength(d2, font=f_desc)
    draw.text(((width - d1w) / 2, 155), d1, font=f_desc, fill=(191, 219, 254))
    draw.text(((width - d2w) / 2, 195), d2, font=f_desc, fill=(255, 255, 255))

    def draw_section_title(text, y_pos):
        tw = draw.textlength(text, font=f_tier_title)
        draw.text(((width - tw)/2, y_pos), text, font=f_tier_title, fill=(15, 23, 42))
        draw.rectangle([((width)/2 - 25, y_pos + 45), ((width)/2 + 25, y_pos + 50)], fill=(59, 130, 246))

    # ------------------------------------------------------
    # [전략 분석 지표] - Top 6 및 비율 완벽 조정
    # ------------------------------------------------------
    draw_section_title("전략 분석 지표", 290)

    # 좌측 박스 (단지별 순위)
    draw.rounded_rectangle([(40, 360), (490, 680)], radius=20, outline=(226, 232, 240), width=2)
    l1 = "단지별 최고 순위"
    l1w = draw.textlength(l1, font=f_label)
    draw.text((40 + (450 - l1w)/2, 385), l1, font=f_label, fill=(30, 41, 59))
    
    y_off = 435
    if my_ranks_dict:
        for i, (name, rank) in enumerate(list(my_ranks_dict.items())[:6]):
            r_str = f"{rank}위" if isinstance(rank, int) else str(rank)
            draw.text((70, y_off), f"{i+1}. {name[:12]}", font=f_small, fill=(71, 85, 105))
            draw.text((460, y_off), r_str, font=f_tier_title, fill=(37, 99, 235), anchor="ra")
            draw.line([(70, y_off+38), (460, y_off+38)], fill=(241, 245, 249), width=1)
            y_off += 40

    # 우측 박스 (시장 점유율)
    draw.rounded_rectangle([(510, 360), (960, 680)], radius=20, outline=(226, 232, 240), width=2)
    l2 = "시장 점유율 TOP 6"
    l2w = draw.textlength(l2, font=f_label)
    draw.text((510 + (450 - l2w)/2, 385), l2, font=f_label, fill=(30, 41, 59))
    
    y_off = 435
    if top_comp_list:
        max_s = max([s for _, s in top_comp_list]) if top_comp_list else 1
        for i, (name, score) in enumerate(top_comp_list[:6]):
            draw.text((540, y_off), f"{i+1}. {name[:9]}", font=f_small, fill=(71, 85, 105))
            bar_w = int((score/max_s) * 130) if max_s > 0 else 0
            draw.rounded_rectangle([(710, y_off+3), (710+bar_w, y_off+20)], radius=4, fill=(219, 234, 254))
            draw.text((930, y_off), f"{int(score)}점", font=f_small, fill=(30, 41, 59), anchor="ra")
            draw.line([(540, y_off+38), (930, y_off+38)], fill=(241, 245, 249), width=1)
            y_off += 40

    # ------------------------------------------------------
    # [실시간 매물 노출 등급] - 대시보드와 동일한 5개 데이터 수령
    # ------------------------------------------------------
    draw_section_title("실시간 매물 노출 등급", 730)

    tiers = [
        {"t": "상위권 매물 (1~5위)", "c": top_count, "a": top_avg, "color": (29, 78, 216), "bg": (239, 246, 255), "key": "top"},
        {"t": "중위권 매물 (6~15위)", "c": mid_count, "a": mid_avg, "color": (21, 128, 61), "bg": (240, 253, 244), "key": "mid"},
        {"t": "하위권 경고 (16위 밖)", "c": low_count, "a": low_avg, "color": (185, 28, 28), "bg": (254, 242, 242), "key": "low"}
    ]
    
    y_cursor = 800
    for t in tiers:
        items = item_data.get(t["key"], [])[:5] 
        box_h = 85 + (len(items) * 85 if items else 60)
        
        draw.rounded_rectangle([(40, y_cursor), (960, y_cursor + box_h)], radius=16, fill=(255, 255, 255), outline=(226, 232, 240), width=2)
        draw.rounded_rectangle([(40, y_cursor), (960, y_cursor + 75)], radius=16, fill=t["bg"])
        draw.text((70, y_cursor + 25), t["t"], font=f_tier_title, fill=t["color"])
        
        count_text = f"전체 {t['c']}건 중 5건 (단지 평균 {t['a']}위)" if t['c'] > 5 else f"{t['c']}건 (단지 평균 {t['a']}위)"
        cw = draw.textlength(count_text, font=f_small)
        draw.text((930 - cw, y_cursor + 30), count_text, font=f_small, fill=(15, 23, 42))
        
        c_y = y_cursor + 75
        if not items:
            none_txt = "해당 매물이 없습니다."
            nw = draw.textlength(none_txt, font=f_label)
            draw.text(((width - nw)/2, c_y + 25), none_txt, font=f_label, fill=(148, 163, 184))
        else:
            for item in items:
                draw.text((70, c_y + 20), item["spec"], font=f_label, fill=(51, 65, 85))
                
                # 뱃지 폭 자동 조정 및 우측 밀착 정렬
                clean_badge = item["badge"].replace("🚨 ", "").replace("⚡ ", "").replace("✅ ", "")
                bw = draw.textlength(clean_badge, font=f_badge)
                
                bg_color = (254, 226, 226) if "중단" in clean_badge else ((219, 234, 254) if "타격" in clean_badge else (220, 252, 231))
                text_color = (220, 38, 38) if "중단" in clean_badge else ((37, 99, 235) if "타격" in clean_badge else (22, 163, 74))
                
                draw.rounded_rectangle([(930 - bw - 24, c_y + 16), (930, c_y + 44)], radius=8, fill=bg_color)
                draw.text((930 - bw - 12, c_y + 24), clean_badge, font=f_badge, fill=text_color)
                
                draw.text((70, c_y + 55), item["rank_str"], font=f_small, fill=(100, 116, 139))
                draw.line([(40, c_y + 85), (960, c_y + 85)], fill=(241, 245, 249), width=1)
                c_y += 85
                
        y_cursor += box_h + 30

    footer = "본 리포트는 TOP RANK AI에 의해 실시간 생성되었습니다."
    fw = draw.textlength(footer, font=f_small)
    draw.text(((width - fw) / 2, y_cursor), footer, font=f_small, fill=(148, 163, 184))

    img_buffer = io.BytesIO()
    img.save(img_buffer, format="PNG")
    return img_buffer.getvalue()
    
# 💡 [로딩 화면 최적화] 프로그레스 바 + 인트로 영상 스플래시 스크린 적용
splash_placeholder = st.empty()

with splash_placeholder.container():
    # 1. 안내 문구
    st.markdown("""
        <div style='text-align: center; padding: 20px 0 10px 0;'>
            <h2 style='color: #1e3a8a; font-weight: 800; font-size: 28px;'>🚀 최신 네이버 부동산 데이터를 동기화 중입니다...</h2>
            <p style='color: #64748b; font-size: 18px; margin-top: 10px;'>수만 개의 시장 데이터를 분석 중입니다. 잠시만 기다려주세요.</p>
        </div>
    """, unsafe_allow_html=True)
    
    # 2. 프로그레스 바 (가짜 애니메이션)
    import time
    my_bar = st.progress(0)
    
    # 3. 인트로 영상 (프로그레스 바 바로 아래에 배치)
    try:
        st.video("intro.mp4", autoplay=True, muted=True)
    except:
        pass
        
    # 4. 바 차오르는 애니메이션 (85%까지)
    for percent_complete in range(0, 85, 15):
        time.sleep(0.1)
        my_bar.progress(percent_complete)

# 실제 데이터 로딩 (이 구간에서 실제 시간 3~5초가 소요됨)
raw_df = load_server_data()

# 로딩이 완료되면 100%로 채우고 화면에서 싹 지움
if splash_placeholder:
    my_bar.progress(100)
    time.sleep(0.2)
    splash_placeholder.empty()
    
if raw_df is None:
    st.error("🚨 서버에 데이터 파일이 없습니다.")
    st.stop()

st.sidebar.title("📅 리포트 상세 설정")

try:
    df = process_data(raw_df)
    min_time, max_time = df['수집일시'].min(), df['수집일시'].max()
    st.sidebar.subheader("📅 분석 기간 설정")
    
    default_start_date = max(min_time.date(), max_time.date() - timedelta(days=7))
    s_d = st.sidebar.date_input("시작일", default_start_date, key="sd_input")
    e_d = st.sidebar.date_input("종료일", max_time.date(), key="ed_input")
    
    start_dt = pd.to_datetime(s_d)
    end_dt = pd.to_datetime(e_d) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
    mask = (df['수집일시'] >= start_dt) & (df['수집일시'] <= end_dt)
    t_df = df[mask].copy()
    
    if target_complexes:
        t_df = t_df[t_df['단지명'].isin(target_complexes)].copy()
        
    if t_df.empty:
        st.error(f"🚨 설정한 기간에 데이터가 없습니다.")
        st.warning(f"🔍 [시스템 디버그]\n- 대표님이 선택한 기간: {start_dt.strftime('%m/%d %H:%M')} ~ {end_dt.strftime('%m/%d %H:%M')}\n- 서버가 읽은 데이터 기간: {min_time.strftime('%m/%d %H:%M')} ~ {max_time.strftime('%m/%d %H:%M')}")
        st.info("💡 깃허브에 방금 파일이 올라갔다면 Streamlit 서버가 파일을 내려받는 데 1~3분 정도 지연될 수 있습니다. 잠시 후 새로고침(F5) 해주세요!")
        st.stop()
        
    global_times = t_df['수집일시'].drop_duplicates().sort_values().reset_index(drop=True)
    bundle_keys = ['단지명', '동/호수', '층/타입', '거래방식', '가격']
    group_keys = bundle_keys + ['부동산명']
    complex_list = sorted(t_df['단지명'].dropna().unique().tolist())
    complex_list_with_all = ["전체 단지"] + complex_list
    
    latest_t = t_df.groupby(bundle_keys)['수집일시'].max().reset_index()
    first_place_df = pd.merge(t_df, latest_t, on=bundle_keys+['수집일시'])
    first_place_df = first_place_df[first_place_df['묶음내순위_숫자']==1][bundle_keys+['부동산명']].rename(columns={'부동산명':'최상단부동산'}).drop_duplicates(subset=bundle_keys)
    
    uniq = t_df.drop_duplicates(subset=['매물번호', '부동산명', '단지명']).copy()
    uniq['묶음_총개수'] = uniq.groupby(bundle_keys)['부동산명'].transform('count')
    uniq['파워점수'] = 10 + (10 / uniq['묶음내순위_숫자']) + (uniq['묶음_총개수'] * 0.1)
    ms_counts = uniq.groupby(['단지명', '부동산명']).agg(매물건수=('부동산명', 'count'), 총점수=('파워점수', 'sum')).reset_index()
    ms_counts['총점수'] = ms_counts['총점수'].round().astype(int)
    
    my_ranks_dict = {}
    for comp in complex_list:
        cdf = ms_counts[ms_counts['단지명'] == comp].copy()
        if cdf.empty: continue
        cdf['순위'] = cdf['총점수'].rank(ascending=False, method='min')
        my_r = cdf[cdf['부동산명'].str.contains(filter_realtor_name)]
        my_ranks_dict[comp] = int(my_r['순위'].iloc[0]) if not my_r.empty else "권외"
        
    MASTER_ADMIN_ID = "a123"
    if user_id == MASTER_ADMIN_ID:
        KST = timezone(timedelta(hours=9))
        now_kst = datetime.now(KST).replace(tzinfo=None)
        last_update_dt = df['수집일시'].max()
        if (now_kst - last_update_dt) > timedelta(hours=2.5):
            st.error(f"🚨 **[관리자 알림] 크롤러 중단!** 최종수집: {last_update_dt.strftime('%m/%d %H:%M')}")

    # ==========================================================
    # 🧠 [데이터 통합 계산] AI 마스터 결론 및 브리핑을 위한 전역 데이터
    # ==========================================================
    now_date = datetime.now(timezone(timedelta(hours=9))).replace(tzinfo=None)
    my_ls = t_df[t_df['부동산명'].str.contains(filter_realtor_name, na=False)].sort_values('수집일시', ascending=False).drop_duplicates(subset=bundle_keys)
    
    danger_ls = my_ls[my_ls['묶음내순위_숫자'] > 3].copy()
    if not danger_ls.empty:
        danger_ls = pd.merge(danger_ls, first_place_df, on=bundle_keys, how='left')
        danger_ls['최상단부동산'] = danger_ls['최상단부동산'].fillna('알수없음')
    else: 
        danger_ls['최상단부동산'] = pd.Series(dtype='str')
        
    all_valid_ranks = t_df.dropna(subset=['전체순위_숫자'])
    market_volatility = all_valid_ranks.groupby('단지명')['전체순위_숫자'].std().mean() if not all_valid_ranks.empty else 0
    
    bundle_info = t_df[['매물묶음키', '단지명', '동/호수', '층/타입']].drop_duplicates('매물묶음키')
    my_bundles = t_df[t_df['부동산명'].str.contains(filter_realtor_name, na=False)]['매물묶음키'].unique()
    bundle_latest_update = t_df.dropna(subset=['확인일자_Date']).groupby('매물묶음키')['확인일자_Date'].max().reset_index()
    bundle_latest_update['방치시간'] = (now_date - bundle_latest_update['확인일자_Date']).dt.total_seconds() / 3600
    
    # 💡 [수정] 방치 기준을 48시간 이상으로 상향 조치
    real_empty_houses = bundle_latest_update[bundle_latest_update['방치시간'] >= 48].copy()
    my_empty = real_empty_houses[real_empty_houses['매물묶음키'].isin(my_bundles)]
    
    trk = df.sort_values(group_keys + ['수집일시', '전체순위_숫자']).copy()
    trk['이전_확인일자'] = trk.groupby(group_keys)['확인일자'].shift(1)
    c1 = trk['이전_확인일자'].notna() & (trk['이전_확인일자'] != trk['확인일자']) & trk['확인일자'].notna()
    boosted_raw = trk[c1]
    boosted_raw = boosted_raw[(boosted_raw['수집일시'] >= start_dt) & (boosted_raw['수집일시'] <= end_dt)]
    boosted_df = boosted_raw[boosted_raw['왜곡영역'] == False].copy()
    
    # 👇 [추가할 코드] 경쟁사 갱신 데이터도 현재 고객의 타겟 단지 안에서만 찾도록 자물쇠를 채웁니다!
    if target_complexes:
        boosted_df = boosted_df[boosted_df['단지명'].isin(target_complexes)].copy()
    
    if not boosted_df.empty:
        battle_grounds = boosted_df.groupby('매물묶음키').size().reset_index(name='경쟁사_갱신횟수')
        real_red_oceans = battle_grounds[battle_grounds['경쟁사_갱신횟수'] >= 3].sort_values('경쟁사_갱신횟수', ascending=False)
        my_red = real_red_oceans[real_red_oceans['매물묶음키'].isin(my_bundles)]
    else:
        my_red = pd.DataFrame(columns=['매물묶음키', '경쟁사_갱신횟수'])
        
    top_spender, top_spender_raw_name, peak_hour_str = "없음", "", ""
    global_peak_hour = 12
    
    if not boosted_df.empty:
        stat_df = boosted_df.groupby('부동산명').agg(총횟수=('부동산명', 'count')).reset_index().sort_values('총횟수', ascending=False)
        top_spender_raw_name = stat_df.iloc[0]['부동산명']
        masked_ts_name = mask_text(clean_realtor_name(top_spender_raw_name), True)
        top_spender = f"{masked_ts_name} ({stat_df.iloc[0]['총횟수']}회)"
        global_peak_hour = int(boosted_df['수집일시'].dt.hour.mode()[0])
        peak_hour_str = f"평균적으로 {global_peak_hour}시 부근에 갱신이 집중됩니다."

    # ==========================================================
    # 🎯 [핵심] AI 마스터 결론 (사용자 설정 기간 기반 성적표)
    # ==========================================================
    empty_count = len(my_empty)

    # 1. 3일 고정 로직 제거! 사용자가 사이드바에서 설정한 기간(t_df)을 그대로 사용합니다.
    selected_days = max(1, (end_dt.date() - start_dt.date()).days + 1)
    recent_my_df = t_df[t_df['부동산명'].str.contains(filter_realtor_name, na=False)]
    
    if not recent_my_df.empty:
        avg_ranks = recent_my_df.groupby(['단지명', '동/호수', '층/타입', '매물묶음키'])['묶음내순위_숫자'].mean().reset_index()
        
        safe_df = avg_ranks[avg_ranks['묶음내순위_숫자'] <= 5]
        mid_df = avg_ranks[(avg_ranks['묶음내순위_숫자'] > 5) & (avg_ranks['묶음내순위_숫자'] <= 10)]
        danger_df = avg_ranks[avg_ranks['묶음내순위_숫자'] > 10]
    else:
        safe_df = mid_df = danger_df = pd.DataFrame()

    total_my_bundles = len(avg_ranks) if not recent_my_df.empty else 0
    safe_my_bundles = len(safe_df)
    mid_my_bundles = len(mid_df)
    danger_count = len(danger_df) # 전략 카드용 에러 방지 재할당
    safe_ratio = int((safe_my_bundles / total_my_bundles) * 100) if total_my_bundles > 0 else 0

    # 2. UI 및 문자용 텍스트/HTML 생성
    def build_ui_html(df):
        if df.empty: return "해당 없음"
        html_str = ""
        for danji, grp in df.groupby('단지명'):
            danji_masked = mask_text(danji)
            html_str += f"<div style='margin-bottom: 12px;'><b style='color:#0f172a; font-size: 15px;'>🏢 [{danji_masked}]</b><br>"
            for _, row in grp.iterrows():
                spec_masked = mask_text(row['매물묶음키'])
                html_str += f"&nbsp;&nbsp;&nbsp;&nbsp;🔹 {spec_masked} <span style='color:#64748b; font-size:12px;'>(평균 {row['묶음내순위_숫자']:.1f}위)</span><br>"
            html_str += "</div>"
        return html_str

    def build_sms_text(df):
        if df.empty: return "해당 없음"
        items = []
        for danji, grp in df.groupby('단지명'):
            danji_masked = mask_text(danji)
            for _, row in grp.iterrows():
                spec_masked = mask_text(row['매물묶음키'])
                items.append(f" - [{danji_masked}] {spec_masked} (평균 {row['묶음내순위_숫자']:.1f}위)")
        
        if len(items) > 3:
            return "\n".join(items[:3]) + f"\n   ...외 {len(items)-3}건 (상세 내역은 대시보드 접속 확인)"
        else:
            return "\n".join(items)

    safe_ui_html = build_ui_html(safe_df)
    mid_ui_html = build_ui_html(mid_df)
    danger_ui_html = build_ui_html(danger_df)

    safe_sms_text = build_sms_text(safe_df)
    mid_sms_text = build_sms_text(mid_df)
    danger_sms_text = build_sms_text(danger_df)

    # ⭐ 3. 화면 UI 렌더링 (대시보드에서도 클릭 전부터 설명이 바로 보이도록 제목에 고정!)
    # [수정 완료] "최근 3일간" -> "선택하신 기간({selected_days}일) 동안" 으로 변경했습니다.
    master_conclusion = f"선택하신 기간(<b style='color:#8b5cf6;'>{selected_days}일</b>) 동안 대표님이 관리 중인 활동 매물 <b style='color:#8b5cf6;'>{total_my_bundles}개</b> 중, 상위권(평균 5위 이내)에 방어 중인 매물은 <b style='color:#3182f6;'>{safe_my_bundles}개({safe_ratio}%)</b>입니다.<br><br>"

    master_conclusion += f"<details style='background-color:#eff6ff; padding: 15px; border-radius: 10px; margin-bottom: 10px; border-left: 5px solid #3b82f6; outline: none;'><summary style='font-size: 16px; color: #1e3a8a; font-weight: bold; cursor: pointer; outline: none; list-style: none;'>▶ 🟢 상위권 (평균 1~5위) : 📞 고객에게 인기가 많은 매물 (예산 집중) - 총 {safe_my_bundles}개</summary><div style='margin-top: 15px; font-size: 14px; color: #334155; line-height: 1.6;'>{safe_ui_html}</div></details>"

    master_conclusion += f"<details style='background-color:#fffbeb; padding: 15px; border-radius: 10px; margin-bottom: 10px; border-left: 5px solid #f59e0b; outline: none;'><summary style='font-size: 16px; color: #b45309; font-weight: bold; cursor: pointer; outline: none; list-style: none;'>▶ 🟡 중위권 (평균 6~10위) : 🚀 고객에게 인기가 적은 매물 (선택 집중) - 총 {mid_my_bundles}개</summary><div style='margin-top: 15px; font-size: 14px; color: #334155; line-height: 1.6;'>{mid_ui_html}</div></details>"

    master_conclusion += f"<details style='background-color:#fef2f2; padding: 15px; border-radius: 10px; border-left: 5px solid #ef4444; outline: none;'><summary style='font-size: 16px; color: #991b1b; font-weight: bold; cursor: pointer; outline: none; list-style: none;'>▶ 🔴 하위권 (평균 11위 밖) : 💸 고객에게 거의 보여지지 않는 매물 (예산 보류) - 총 {danger_count}개</summary><div style='margin-top: 15px; font-size: 14px; color: #334155; line-height: 1.6;'>{danger_ui_html}</div></details>"

    # --- 작전 브리핑(문자 발송용) 텍스트 ---
    briefing_date = end_dt.strftime('%Y-%m-%d')
    
    if not t_df.empty:
        actual_start_dt = t_df['수집일시'].min().date()
        actual_end_dt = t_df['수집일시'].max().date()
    else:
        actual_start_dt = start_dt.date()
        actual_end_dt = end_dt.date()

    analysis_period_str = f"{actual_start_dt.strftime('%Y.%m.%d')} ~ {actual_end_dt.strftime('%Y.%m.%d')}"
    analysis_days = max(1, (actual_end_dt - actual_start_dt).days + 1)
    
    rank_summary = " / ".join([f"{mask_text(k)} {v}위" for k, v in my_ranks_dict.items() if v != '권외'])
    if not rank_summary: rank_summary = "분석된 상위 노출 순위 없음"
    
    top3_str = "분석된 타사 데이터 없음"
    
    if not boosted_df.empty:
        temp_boosted = boosted_df.copy()
        temp_boosted['부동산명_정제'] = temp_boosted['부동산명'].apply(clean_realtor_name)
        top_competitors = temp_boosted.groupby('부동산명_정제').size().reset_index(name='갱신횟수')
        top_competitors = top_competitors.sort_values('갱신횟수', ascending=False).head(3)
        
        if not top_competitors.empty:
            top_list = []
            total_top3_renews = 0
            for i, row in enumerate(top_competitors.itertuples(), 1):
                masked_name = mask_text(row.부동산명_정제, True) 
                top_list.append(f"{i}위 {masked_name}")
                total_top3_renews += row.갱신횟수
                
            top_names_str = ", ".join(top_list)
            comp_count = len(top_competitors)
            avg_per_comp = total_top3_renews / comp_count
            daily_avg_per_comp = avg_per_comp / analysis_days
            
            top3_str = f"현재 {top_names_str} 입니다.\n이 {comp_count}곳은 최근 {analysis_days}일 동안 1곳당 평균 {avg_per_comp:.1f}회 (일평균 {daily_avg_per_comp:.1f}회)를 갱신하며 시장을 과열시키고 있습니다."

    # ⭐ 브리핑 텍스트 완성 (요청하신 워딩 100% 반영)
    briefing_text = f"""☀️ [{briefing_date} 작전 브리핑] AI 시장 동향 리포트
안녕하세요, {display_realtor} 대표님.
TOP RANK AI가 분석한 오늘의 시장 핵심 전략을 보고드립니다.
(분석 기간: {analysis_period_str})

🏆 1. 내 부동산 단지별 랭킹 현황
- 현재 대표님의 단지별 랭킹은 [{rank_summary}] 입니다.

⚔️ 2. 경계해야 할 타사 활동 패턴 (타겟 단지 기준)
- {top3_str}

💡 3. [오늘의 AI 마스터 결론]
분석 기간({selected_days}일) 기준 관리 매물 {total_my_bundles}개 중, 상위권 방어 매물은 {safe_my_bundles}개({safe_ratio}%)입니다.

🟢 [상위권 (평균 1~5위)] : 📞 고객에게 인기가 많은 매물 (집중)
{safe_sms_text}

🟡 [중위권 (평균 6~10위)] : 🚀 고객에게 인기가 있는 매물 (유지)
{mid_sms_text}

🔴 [하위권 (평균 11위 밖)] : 💸 고객에게 거의 보여지지 않는 매물 (보류)
{danger_sms_text}"""

# --- UI 렌더링 시작 ---
    # 1. 깔끔한 대형 제목 (중복 방지)
    st.markdown(f"<h1 style='font-size: 42px; font-weight: 800; color: #1e3a8a; margin-bottom: 25px;'>📊 {display_realtor} 대표님을 위한 시장 동향</h1>", unsafe_allow_html=True)
    
    if IS_DEMO_MODE:
        with st.expander("🚀 **체험판 200% 활용 가이드 (처음 오셨다면 클릭하세요!)**", expanded=False):
            st.markdown("""
            **안녕하세요! 본 대시보드는 네이버 부동산 광고 효율을 극대화하기 위한 '시장 작전판'입니다.**
            1. **📊 오늘의 AI 성과:** 자동 갱신 엔진이 방어해 낸 성과와 AI 마스터 전략을 확인하세요.
            2. **🎯 내 매물 방어 현황:** 상위권에서 밀린 매물, 경쟁사가 집중하지 않는 빈집, AI 추천 타격 시간을 점검하세요.
            3. **📡 시장 & 경쟁사 동향:** 단지별 롤링 심각도와 라이벌 부동산의 갱신 주기(예산) 패턴을 딥하게 분석합니다.
            """)

    # 💡 (이사 온 위치) 여기에 함수를 미리 정의해 둡니다.
    @st.cache_data(max_entries=2, show_spinner=False)
    def get_cached_bp_df(_comp_df, _b_boosted_comp, total_sessions):
        b_ranks = _comp_df.groupby(['매물묶음키', '수집일시'])['전체순위_숫자'].min().reset_index()
        appearances = b_ranks.groupby('매물묶음키')['수집일시'].nunique()
        avg_ranks = b_ranks.groupby('매물묶음키')['전체순위_숫자'].mean()
        
        bp = pd.DataFrame({
            '매물묶음키': appearances.index,
            '생존율_num': (appearances / total_sessions) * 100,
            '평균 순위': avg_ranks
        }).reset_index(drop=True)
        
        def get_action_plan(sr):
            if sr >= 80: return "🟢 S급 (집중 타격)"
            elif sr >= 40: return "🟡 A급 (가성비 방어)"
            else: return "🔴 불량 (광고 중단)"
        bp['AI 추천 액션'] = bp['생존율_num'].apply(get_action_plan)
        
        renew_counts = _b_boosted_comp.groupby('매물묶음키').size()
        bp['갱신횟수'] = bp['매물묶음키'].map(renew_counts).fillna(0)
        return bp

    # 사이드바 또는 상단 메뉴 선택기
    selected_menu = st.radio(
        "메뉴 선택",
        [
            "📊 오늘의 AI 성과 (핵심 요약)", 
            "🔍 통합 매물 검색 (심층 분석)", 
            "🎯 내 매물 방어 현황 (액션)", 
            "📡 시장 & 경쟁사 동향 (분석)",
            "🎯 AI 매물 정밀 진단 (Beta)"  # <-- 여기에 추가!
        ],
        horizontal=True,
        label_visibility="collapsed"
    )
    if 'last_logged_menu' not in st.session_state:
        st.session_state['last_logged_menu'] = selected_menu
    else:
        if st.session_state['last_logged_menu'] != selected_menu:
            st.session_state['last_logged_menu'] = selected_menu

    # ==========================================================
    # 탭 1. 📊 마스터 대시보드 - 🚀 파이썬 이미지 엔진 완벽 연동본
    # ==========================================================
    if selected_menu == "📊 오늘의 AI 성과 (핵심 요약)":
        
        recent_my_df = t_df[t_df['부동산명'].str.contains(filter_realtor_name, na=False)] if 't_df' in locals() else pd.DataFrame()

        item_data_for_image = {"top": [], "mid": [], "low": []}
        diag_dict = {"top": "", "mid": "", "low": ""}
        summary_stats = {"top": [0, 0], "mid": [0, 0], "low": [0, 0]}

        if not recent_my_df.empty:
            for b_key, b_grp in recent_my_df.groupby('매물묶음키'):
                parts = [p.strip() for p in b_key.split('|')]
                if len(parts) >= 3:
                    masked_danji = mask_text(parts[0])
                    masked_dong = mask_text(parts[1])
                    rest_spec = " · ".join(parts[2:]) 
                    html_spec = f"{masked_danji} {masked_dong} <span style='color:#64748b; font-weight:normal;'>[{rest_spec}]</span>"
                    raw_spec = f"{masked_danji} {masked_dong} [{rest_spec}]"
                else:
                    html_spec = raw_spec = b_key
                
                try:
                    b_grp_numeric = b_grp.copy()
                    b_grp_numeric['전체순위_숫자'] = pd.to_numeric(b_grp_numeric['전체순위'], errors='coerce')
                    avg_total_rank = b_grp_numeric.groupby('수집일시')['전체순위_숫자'].min().mean()
                except: avg_total_rank = 20.0

                avg_my_rank = b_grp.groupby('수집일시')['묶음내순위_숫자'].min().mean()
                comp_renews = len(boosted_df[boosted_df['매물묶음키'] == b_key]) if 'boosted_df' in locals() else 0

                # ------------------------------------------------------------------
                # 💡 [핵심 수정] 뱃지 로직에 심야(00~07시) 유령 트래픽 배제 로직 적용
                # ------------------------------------------------------------------
                if avg_total_rank > 15.0 and comp_renews >= 2:
                    raw_badge = "광고 중단"
                    html_badge = f"<div style='padding:4px 10px; border-radius:6px; font-size:12px; font-weight:800; white-space:nowrap; letter-spacing:-0.5px; background-color:#fff1f0; color:#ef4444;'>🚨 {raw_badge}</div>"
                elif comp_renews > 0:
                    b_boosted = boosted_df[boosted_df['매물묶음키'] == b_key]
                    active_hours = sorted(b_boosted['수집일시'].dt.hour.unique().tolist())
                    
                    if len(active_hours) <= 1:
                        best_hour = (active_hours[0] + 1) % 24 if active_hours else 12
                        # 💡 계산된 시간이 심야면 아침 8시 영업시작 시간으로 고정
                        if 0 <= best_hour <= 7: best_hour = 8
                    else:
                        max_effective_gap = -1
                        best_hour = 12
                        
                        for i in range(len(active_hours)):
                            curr_h = active_hours[i]
                            next_h = active_hours[(i + 1) % len(active_hours)]
                            raw_gap = (next_h - curr_h) % 24
                            if raw_gap == 0: raw_gap = 24 
                            
                            strike_hour = (curr_h + 1) % 24
                            
                            effective_gap = 0
                            # 💡 00시~07시는 유효 방어 시간 점수에서 아예 제외!
                            for h in range(strike_hour, strike_hour + raw_gap):
                                real_h = h % 24
                                if 8 <= real_h <= 23:
                                    effective_gap += 1
                                    
                            if effective_gap > max_effective_gap:
                                max_effective_gap = effective_gap
                                best_hour = strike_hour
                        
                        # 💡 최종 채택된 타격 시간조차 심야(00~07시)에 걸려있다면 아침 8시로 밀어버림
                        if 0 <= best_hour <= 7:
                            best_hour = 8

                    ampm = "오후" if best_hour >= 12 else "오전"
                    disp_h = best_hour if best_hour <= 12 else best_hour - 12
                    if disp_h == 0: disp_h = 12 # 0시는 12시로 표기
                    
                    raw_badge = f"{ampm} {disp_h}시 타격"
                    html_badge = f"<div style='padding:4px 10px; border-radius:6px; font-size:12px; font-weight:800; white-space:nowrap; letter-spacing:-0.5px; background-color:#eff6ff; color:#3b82f6;'>⚡ {raw_badge}</div>"
                else:
                    raw_badge = "자유 갱신"
                    html_badge = f"<div style='padding:4px 10px; border-radius:6px; font-size:12px; font-weight:800; white-space:nowrap; letter-spacing:-0.5px; background-color:#f0fdf4; color:#10b981;'>✅ {raw_badge}</div>"

                # ------------------------------------------------------------------

                raw_rank_str = f"내 순위: {avg_my_rank:.1f}등  |  단지 노출: {avg_total_rank:.1f}위"
                html_rank_str = f"내 순위: <span style='font-weight:700; color:#0f172a;'>{avg_my_rank:.1f}등</span> <span style='margin:0 8px; color:#cbd5e1;'>|</span> 단지 노출: <span style='font-weight:700; color:#0f172a;'>{avg_total_rank:.1f}위</span>"

                item_html = f"<div style='padding:16px 25px; border-bottom:1px solid #f1f5f9;'><div style='display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;'><div style='font-size:15px; font-weight:700; color:#334155; line-height:1.4;'>{html_spec}</div><div>{html_badge}</div></div><div style='font-size:13px; color:#64748b;'>{html_rank_str}</div></div>"
                
                item_dict = {"spec": raw_spec, "badge": raw_badge, "rank_str": raw_rank_str}

                if avg_total_rank <= 5.0:
                    diag_dict["top"] += item_html
                    if len(item_data_for_image["top"]) < 5: item_data_for_image["top"].append(item_dict)
                    summary_stats["top"][0] += 1; summary_stats["top"][1] += avg_total_rank
                elif avg_total_rank <= 15.0:
                    diag_dict["mid"] += item_html
                    if len(item_data_for_image["mid"]) < 5: item_data_for_image["mid"].append(item_dict)
                    summary_stats["mid"][0] += 1; summary_stats["mid"][1] += avg_total_rank
                else:
                    diag_dict["low"] += item_html
                    if len(item_data_for_image["low"]) < 5: item_data_for_image["low"].append(item_dict)
                    summary_stats["low"][0] += 1; summary_stats["low"][1] += avg_total_rank

        # --- [웹 대시보드 UI 렌더링] ---
        st.markdown(f"""
        <div style="background: linear-gradient(135deg, #2563eb 0%, #1e3a8a 100%); padding: 30px 40px; border-radius: 16px; color: white; margin-bottom: 30px; box-shadow: 0 10px 25px rgba(30, 58, 138, 0.15);">
            <div style="display:flex; justify-content:space-between; align-items:center;">
                <h1 style="margin: 0; font-size: 34px; font-weight: 800; letter-spacing: -0.5px;">🚀 마스터 대시보드</h1>
                <span style="background:rgba(255,255,255,0.2); padding:6px 16px; border-radius:20px; font-size:13px; font-weight:700;">TOP RANK AI</span>
            </div>
            <div style="margin-top: 15px; font-size: 19px; line-height: 1.6; opacity: 0.95; word-break: keep-all; font-weight: 500;">
                네이버 부동산 검색 알고리즘과 경쟁사 활동을 실시간 분석한 <b style="color:#bfdbfe;">{display_realtor}</b> 전용 리포트입니다.<br>
                매물별 노출 등급에 따른 AI 처방을 확인하고, <b>권장 타격 시간에 맞춰 상위 노출을 관리하세요.</b>
            </div>
        </div>
        """, unsafe_allow_html=True)

        def build_section_header(title, icon):
            return f"<div style='text-align:center; margin: 45px 0 20px 0;'><h3 style='font-weight:900; color:#0f172a; font-size:24px; margin:0;'>{icon} {title}</h3><div style='width:40px; height:4px; background-color:#3b82f6; margin:5px auto 0 auto; border-radius:2px;'></div></div>"

        st.markdown(build_section_header("전략 분석 지표", "🛡️"), unsafe_allow_html=True)
        col_rank, col_ms = st.columns([1, 1.2])
        
        with col_rank:
            st.markdown("<div style='text-align:center; font-weight:800; color:#334155; font-size:16px; padding-bottom:10px;'>🥇 우리 부동산 단지별 순위</div>", unsafe_allow_html=True)
            if not recent_my_df.empty:
                my_complex_rank = recent_my_df.groupby('단지명')['묶음내순위_숫자'].min().reset_index()
                my_complex_rank.columns = ['단지명', '최고순위']
                my_complex_rank['단지명'] = my_complex_rank['단지명'].apply(mask_text)
                st.dataframe(my_complex_rank.sort_values('최고순위'), hide_index=True, use_container_width=True)

        with col_ms:
            st.markdown("<div style='text-align:center; font-weight:800; color:#334155; font-size:16px; padding-bottom:10px;'>🏆 시장 점유율 (Top 5)</div>", unsafe_allow_html=True)
            top_comp_list = []
            if 'ms_counts' in locals() and not ms_counts.empty:
                import plotly.express as px
                ms_df = ms_counts.copy()
                ms_df['부동산명_축약'] = ms_df['부동산명'].apply(lambda x: mask_text(clean_realtor_name(x), True))
                agg_ms = ms_df.groupby('부동산명_축약')['총점수'].sum().reset_index()
                top_df = agg_ms.sort_values('총점수', ascending=False).head(5)
                top_comp_list = [(row.부동산명_축약, row.총점수) for row in top_df.itertuples()]
                
                fig_ms = px.bar(top_df, x='총점수', y='부동산명_축약', orientation='h', color_discrete_sequence=['#3182f6'], text='총점수', template='plotly_white')
                fig_ms.update_yaxes(autorange="reversed")
                fig_ms.update_layout(height=210, margin=dict(t=0, b=0, l=0, r=0), xaxis_visible=False, yaxis_title="")
                st.plotly_chart(fig_ms, use_container_width=True)

        st.markdown("<br><hr style='margin:10px 0 30px 0; border-color:#e2e8f0;'>", unsafe_allow_html=True)
        st.markdown(build_section_header("실시간 매물 등급 및 처방", "🎯"), unsafe_allow_html=True)

        t_cnt = summary_stats["top"][0]; t_avg = round(summary_stats["top"][1]/t_cnt, 1) if t_cnt > 0 else 0
        m_cnt = summary_stats["mid"][0]; m_avg = round(summary_stats["mid"][1]/m_cnt, 1) if m_cnt > 0 else 0
        l_cnt = summary_stats["low"][0]; l_avg = round(summary_stats["low"][1]/l_cnt, 1) if l_cnt > 0 else 0

        def build_card_html(title, icon, count, avg, color, bg_color, border_color, items_html):
            empty_msg = "<div style='color:#94a3b8; font-size:15px; text-align:center; padding:40px 0;'>해당 매물이 없습니다.</div>"
            html = f"<div style='background-color:white; border-radius:16px; border:1px solid {border_color}; box-shadow:0 4px 6px -1px rgba(0,0,0,0.05); margin-bottom:30px; overflow:hidden;'>"
            html += f"<div style='background-color:{bg_color}; padding:20px 25px; border-bottom:1px solid {border_color}; display:flex; justify-content:space-between; align-items:center;'>"
            html += f"<div style='display:flex; align-items:center; gap:8px;'><span style='font-size:22px;'>{icon}</span><span style='font-weight:800; color:{color}; font-size:18px; margin-top:2px;'>{title}</span></div>"
            html += f"<span style='font-weight:900; color:#1e293b; font-size:20px;'>{count}건 <span style='font-weight:500; color:#64748b; font-size:14px; margin-left:5px;'>(단지 평균 {avg}위)</span></span>"
            html += f"</div><div style='max-height:400px; overflow-y:auto;'>"
            html += f"{items_html if items_html else empty_msg}</div></div>"
            return html

        st.markdown(build_card_html("상위권 매물 (1~5위)", "🏆", t_cnt, t_avg, "#1d4ed8", "#eff6ff", "#bfdbfe", diag_dict["top"]), unsafe_allow_html=True)
        st.markdown(build_card_html("중위권 매물 (6~15위)", "🚀", m_cnt, m_avg, "#15803d", "#f0fdf4", "#bbf7d0", diag_dict["mid"]), unsafe_allow_html=True)
        st.markdown(build_card_html("하위권 경고 (16위 밖)", "🚨", l_cnt, l_avg, "#b91c1c", "#fef2f2", "#fecaca", diag_dict["low"]), unsafe_allow_html=True)

        # ------------------------------------------------------
        # 📸 [버그 픽스 완료] 완벽한 파이썬 이미지 생성 버튼
        # ------------------------------------------------------
        st.markdown("<br>", unsafe_allow_html=True)
        selected_days = max(1, (end_dt.date() - start_dt.date()).days + 1)
        ranks_dict_val = my_ranks_dict if 'my_ranks_dict' in locals() else {}
        
        # 💡 드디어 item_data_for_image(순수 텍스트)를 이미지 함수로 전달!
        report_image_bytes = generate_kakao_report_image(
            display_realtor, t_cnt, t_avg, m_cnt, m_avg, l_cnt, l_avg, selected_days, ranks_dict_val, top_comp_list, item_data_for_image
        )
        
        c_btn1, c_btn2, c_btn3 = st.columns([1, 2, 1])
        with c_btn2:
            st.download_button(
                label="📸 실시간 작전 리포트 다운로드 (카톡 전송용)",
                data=report_image_bytes,
                file_name=f"TOP_RANK_리포트_{display_realtor}_{datetime.now().strftime('%m%d')}.png",
                mime="image/png",
                type="primary",
                use_container_width=True
            )

        # ------------------------------------------------------
        # 6. [AI 자동 갱신 성과 영역] 
        # ------------------------------------------------------
        st.markdown("<br><hr>", unsafe_allow_html=True)
        components.html(f"<div style='padding: 15px 0;'><h3 style='color:#1e3a8a; margin: 0; font-size: 24px; font-weight: bold;'>🚀 AI 자동 갱신 성과</h3></div>", height=60)
        # (이하 기존 자동 갱신 표 및 하단 결제 배너 코드는 그대로 유지하시면 됩니다)
        
        total_defense_seconds = 0  
        
        if IS_DEMO_MODE:
            now_kst = datetime.now(timezone(timedelta(hours=9)))
            dummy_logs = [
                {"갱신시간": (now_kst - timedelta(minutes=18)).strftime("%Y-%m-%d %H:%M:%S"), "단지명": "다산자이아이비플레이스", "매물상세": "1**동 (*4A)", "상태": "✅ 성공", "갱신 전 순위": "14위 (🔴하위권)", "갱신 후 최고순위": "🏆 최고 1위 (현재 1위)", "상위(3위) 방어시간": "1시간 20분", "순위 궤적": [20, 20, 19, 20, 19], "성과 요약": "🚀 13계단 상승"},
                {"갱신시간": (now_kst - timedelta(hours=1, minutes=45)).strftime("%Y-%m-%d %H:%M:%S"), "단지명": "다산한양수자인리버팰리스", "매물상세": "1**3동 (*4B)", "상태": "✅ 성공", "갱신 전 순위": "9위 (🟡중위권)", "갱신 후 최고순위": "🏆 최고 2위 (현재 4위)", "상위(3위) 방어시간": "45분", "순위 궤적": [19, 19, 18, 15, 17, 16], "성과 요약": "🚀 7계단 상승"}
            ]
            merged_df = pd.DataFrame(dummy_logs)
            success_count = len(merged_df)
            up_defense_count = len(merged_df)
            total_defense_seconds = 15300
        else:
            df_exec = load_renewal_logs()
            merged_df = pd.DataFrame()
            if not df_exec.empty and len(df_exec) > 1:
                try:
                    df_exec.columns = df_exec.iloc[0]; df_exec = df_exec[1:].copy()
                    merged_df = df_exec.astype(str)
                    time_col = '일시' if '일시' in merged_df.columns else '갱신시간' if '갱신시간' in merged_df.columns else merged_df.columns[0]
                    merged_df['갱신시간'] = pd.to_datetime(merged_df[time_col], errors='coerce')
                    merged_df = merged_df[merged_df['상태'].astype(str).str.contains('성공|완료', na=False)]
                    realtor_col = '부동산명' if '부동산명' in merged_df.columns else '부동산' if '부동산' in merged_df.columns else merged_df.columns[1]
                    merged_df = merged_df[merged_df[realtor_col].astype(str).str.contains(filter_realtor_name, na=False)].copy()
        
                    if not merged_df.empty:
                        spec_col = '매물스펙' if '매물스펙' in merged_df.columns else '매물상세'
                        merged_df = merged_df.sort_values('갱신시간', ascending=False).drop_duplicates(subset=[spec_col], keep='first')
                        tracking_results, trend_data, display_danji, display_detail = [], [], [], []
                        total_defense_seconds = 0 
        
                        for idx, row in merged_df.iterrows():
                            t0 = row['갱신시간']
                            raw_key = str(row.get(spec_col, '')).strip()
                            parts = [p.strip() for p in raw_key.split('|')]
                            
                            target_bundle_key = f"{parts[1]} | {parts[2]} | {parts[3]} | {parts[4]}" if len(parts) >= 5 else raw_key
                            danji_cond = (df['단지명'] == parts[0]) if len(parts) >= 5 else True
                            m_history = df[danji_cond & (df['매물묶음키'] == target_bundle_key) & (df['부동산명'].astype(str).str.contains(filter_realtor_name, na=False))].sort_values('수집일시')
        
                            if m_history.empty:
                                tracking_results.append(("기록 없음", "기록 없음", "추적 불가", "-")); trend_data.append([]); display_danji.append("정보 없음"); display_detail.append("-")
                                continue
        
                            display_danji.append(m_history.iloc[-1]['단지명'])
                            display_detail.append(f"{m_history.iloc[-1]['동/호수']} ({m_history.iloc[-1]['층/타입']})")
        
                            before_df, after_df = m_history[m_history['수집일시'] <= t0], m_history[m_history['수집일시'] > t0]
                            before_rank = int(before_df.iloc[-1]['묶음내순위_숫자']) if not before_df.empty else None
                            b_str = f"{before_rank}위" if pd.notna(before_rank) else "30위 밖"
        
                            if not after_df.empty:
                                best_rank, current_rank = int(after_df['묶음내순위_숫자'].min()), int(after_df.iloc[-1]['묶음내순위_숫자'])
                                base_rank = before_rank if before_rank is not None else int(after_df['묶음내순위_숫자'].max())
                                trend = [(base_rank - int(r)) for r in after_df['묶음내순위_숫자'].tolist()]
                                a_str = f"🏆 최고 {best_rank}위 (현재 {current_rank}위)"
        
                                if current_rank > best_rank: res = "🔄 네이버 롤링 중"
                                elif best_rank <= 3: res = "🚀 상위권 진입 방어"
                                elif before_rank is None or best_rank < before_rank: res = "🔼 순위 상승"
                                else: res = "➖ 순위 유지"
        
                                item_defense_seconds = 0
                                sorted_after = after_df.sort_values('수집일시'); prev_time = pd.to_datetime(t0)
                                for _, r in sorted_after.iterrows():
                                    curr_time = pd.to_datetime(r['수집일시'])
                                    if int(r['묶음내순위_숫자']) <= 3: item_defense_seconds += (curr_time - prev_time).total_seconds()
                                    prev_time = curr_time
                                total_defense_seconds += item_defense_seconds
        
                                h = int(item_defense_seconds // 3600); m = int((item_defense_seconds % 3600) // 60)
                                time_str = f"{h}시간 {m}분" if h > 0 else f"{m}분" if m > 0 else "-"
                            else:
                                a_str, res, trend, time_str = "⏳ 대기 중", "대기 중", [], "-"
        
                            tracking_results.append((b_str, a_str, res, time_str)); trend_data.append(trend)
        
                        merged_df['단지명'], merged_df['매물상세'] = display_danji, display_detail
                        merged_df['갱신 전 순위'] = [x[0] for x in tracking_results]
                        merged_df['갱신 후 최고순위'] = [x[1] for x in tracking_results]
                        merged_df['성과 요약'] = [x[2] for x in tracking_results]
                        merged_df['상위(3위) 방어시간'] = [x[3] for x in tracking_results]
                        merged_df['순위 궤적'] = trend_data
        
                        merged_df = merged_df.sort_values('갱신시간', ascending=False)
                        success_count = len(merged_df); up_defense_count = len(merged_df[merged_df['성과 요약'].astype(str).str.contains('상승|진입|롤링', na=False)])
                    else: success_count, up_defense_count = 0, 0
                except Exception as e:
                    success_count, up_defense_count, total_defense_seconds = 0, 0, 0
            else: success_count, up_defense_count, total_defense_seconds = 0, 0, 0

        total_h = int(total_defense_seconds // 3600)
        total_m = int((total_defense_seconds % 3600) // 60)
        
        st.success(f"🛡️ **오늘 상위 노출(3위 이내) 총 방어 시간: {f'{total_h}시간 {total_m}분' if total_h > 0 else f'{total_m}분'}**")
        st.info("💡 **자동화 엔진 성과:** 시스템이 자동으로 갱신하여 상위권을 탈환하고 방어한 내역입니다.")

        if not merged_df.empty:
            st.dataframe(
                merged_df[['갱신시간', '단지명', '매물상세', '상태', '갱신 전 순위', '갱신 후 최고순위', '순위 궤적', '성과 요약']],
                use_container_width=True,
                column_config={"순위 궤적": st.column_config.LineChartColumn("순위 흐름", y_min=0, y_max=31)}
            )
        else:
            st.info("아직 수집된 자동 갱신 성과 로그가 없습니다.")

        # ------------------------------------------------------
        # 7. [하단 서비스 결제 안내 배너] - (캡처 시 자동 숨김 처리됨)
        # ------------------------------------------------------
        st.markdown("<br><hr><br><br>", unsafe_allow_html=True)
        st.markdown("""
        <div style="background: linear-gradient(135deg, #ffffff 0%, #f0f7ff 100%); border: 2px solid #3182f6; border-radius: 20px; padding: 40px 20px; text-align: center; box-shadow: 0 10px 30px rgba(49, 130, 246, 0.12); max-width: 800px; margin: 0 auto;">
            <div style="display: inline-block; background-color: #ef4444; color: white; padding: 6px 15px; border-radius: 20px; font-weight: 800; font-size: 14px; margin-bottom: 15px;">🚀 한정 특가 오픈</div>
            <h2 style="color: #1e3a8a; margin-bottom: 15px; font-weight: 800; font-size: 28px;">TOP RANK 광고 자동화 솔루션</h2>
            <p style="font-size: 22px; color: #334155; margin-bottom: 25px; font-weight: 700;">월 <span style="font-size: 32px; color: #3182f6;">90,000원</span>, 하루 단 <span style="font-size: 32px; color: #3182f6;">3,000원</span>으로 상위 노출 스트레스에서 해방되세요!</p>
            <div style="background-color: #f8fafc; padding: 20px; border-radius: 15px; max-width: 500px; margin: 0 auto; border: 1px solid #e2e8f0;">
                <p style="font-size: 16px; color: #475569; margin: 0; line-height: 1.6;">🏦 <b>결제 계좌:</b> 기업은행 174-117603-01-012 (예금주: 신성우)<br>📞 <b>가입 문의:</b> 010-8416-2806</p>
            </div>
        </div>
        """, unsafe_allow_html=True)
            
    # ==========================================================
    # 탭 2. 🔍 통합 매물 검색 (심층 분석)
    # ==========================================================

    elif selected_menu == "🔍 통합 매물 검색 (심층 분석)":
        st.info("💡 **개별 매물 심층 차트:** 단지와 매물을 선택하면 현재 내 순위, 갱신 빈도, 최적 타격 시간, 그리고 랭킹 차트(ROI)를 종합 진단합니다.")

        c_search1, c_search2 = st.columns(2)
        search_comp = c_search1.selectbox("🏢 단지명 선택", sorted(t_df['단지명'].dropna().unique()), key="search_comp")
        
        if search_comp:
            bundle_list = sorted(t_df[t_df['단지명'] == search_comp]['매물묶음키'].dropna().unique().tolist())
            display_bundle_list = [mask_text(b) for b in bundle_list]
            
            comp_df = t_df[t_df['단지명'] == search_comp]
            total_sessions = max(comp_df['수집일시'].nunique(), 1)
            b_boosted_comp = boosted_df[boosted_df['단지명'] == search_comp]
            
            # 💡 기존의 무거웠던 반복문을 지우고 캐시 함수 호출
            bp_df = get_cached_bp_df(comp_df, b_boosted_comp, total_sessions)
            bp_df['매물 스펙 (동/호수/가격)'] = bp_df['매물묶음키'].apply(mask_text)
            
            # 💡 [스마트 기본값 로직] 생존율 70% 이상 & 갱신횟수 3회 이상
            valid_candidates = bp_df[(bp_df['생존율_num'] >= 70) & (bp_df['갱신횟수'] >= 3)]
            
            if not valid_candidates.empty:
                valid_candidates = valid_candidates.sort_values(by=['생존율_num', '갱신횟수'], ascending=[False, False])
                best_bundle = valid_candidates.iloc[0]['매물묶음키']
            else:
                best_bundle = bp_df.loc[bp_df['생존율_num'].idxmax()]['매물묶음키'] if not bp_df.empty else bundle_list[0]
            
            if 'clicked_bundle' in st.session_state and st.session_state['clicked_bundle'] in bundle_list:
                target_bundle = st.session_state['clicked_bundle']
            else:
                target_bundle = best_bundle
                
            default_idx = bundle_list.index(target_bundle) if target_bundle in bundle_list else 0
            
            search_bundle_display = c_search2.selectbox("🏠 상세 매물 선택 (동/호수/스펙)", display_bundle_list, index=default_idx, key="search_bundle_select")
            search_bundle = bundle_list[display_bundle_list.index(search_bundle_display)]

            if search_bundle != st.session_state.get('clicked_bundle'):
                st.session_state['clicked_bundle'] = search_bundle

            if search_bundle:
                st.markdown("---")
                bdf = t_df[(t_df['단지명'] == search_comp) & (t_df['매물묶음키'] == search_bundle)]
                b_boosted = boosted_df[boosted_df['매물묶음키'] == search_bundle]
                
                latest_data = bdf[bdf['수집일시'] == bdf['수집일시'].max()]
                my_latest = latest_data[latest_data['부동산명'].str.contains(filter_realtor_name, na=False)]
                my_rank = int(my_latest['묶음내순위_숫자'].min()) if not my_latest.empty else "권외"
                
                top_realtor_row = latest_data.sort_values('묶음내순위_숫자').iloc[0] if not latest_data.empty else None
                top_realtor = top_realtor_row['부동산명'] if top_realtor_row is not None else "정보 없음"
                top_realtor_masked = mask_text(top_realtor, True)
                
                analysis_days = max(1, (end_dt.date() - start_dt.date()).days + 1)
                total_renews = len(b_boosted)
                daily_renews = total_renews / analysis_days
                
                # 갱신 빈도 워딩 수정
                if total_renews == 0: renew_status, renew_col = "🧊 방치됨 (빈집 털이 찬스)", "#10b981"
                elif daily_renews >= 3: renew_status, renew_col = f"🔥 일평균 {daily_renews:.1f}회 (초경쟁 격전지)", "#ef4444"
                elif daily_renews >= 1: renew_status, renew_col = f"⚠️ 일평균 {daily_renews:.1f}회 (일반적 경쟁)", "#f59e0b"
                else: renew_status, renew_col = f"💧 일평균 {daily_renews:.1f}회 (느슨한 경쟁)", "#3b82f6"

                # AI 추천 타격 시간 설명 수정
                rec_time = "-"
                rec_desc = "데이터 누적 중"
                if total_renews >= 3:
                    active_hours = sorted(b_boosted['수집일시'].dt.hour.unique().tolist())
                
                    if len(active_hours) <= 1:
                        # 갱신이 한 시간대에만 몰려있으면 그 직후를 추천
                        best_hour = (active_hours[0] + 1) % 24 if active_hours else 12
                        rec_time = f"⏰ {best_hour:02d}:00"
                        rec_desc = f"경쟁사 활동이 {active_hours[0]}시에 집중됩니다. 직후 무혈입성을 권장합니다."
                    else:
                        # [수정 후] - '심야(00~08시) 제외 실제 유효 노출 시간' 계산 로직 적용
                        max_effective_gap = -1
                        best_hour = 12
                        real_gap_len = 0
                        
                        for i in range(len(active_hours)):
                            curr_h = active_hours[i]
                            next_h = active_hours[(i + 1) % len(active_hours)]
                            raw_gap = (next_h - curr_h) % 24
                            if raw_gap == 0: raw_gap = 24  # 하루 종일 안 누르는 경우
                            
                            strike_hour = (curr_h + 1) % 24
                            
                            # ⭐ [핵심] 타격 시간부터 빈집 끝날 때까지 1시간씩 돌면서 '심야'인지 '영업시간'인지 검사
                            effective_gap = 0
                            for h in range(strike_hour, strike_hour + raw_gap):
                                real_h = h % 24
                                # 00시 ~ 07시(새벽)는 유효 시간에서 제외, 08시부터 23시까지만 +1점
                                if 8 <= real_h <= 23:
                                    effective_gap += 1
                                    
                            # 유효 시간이 가장 큰 구간을 승자로 채택!
                            if effective_gap > max_effective_gap:
                                max_effective_gap = effective_gap
                                best_hour = strike_hour
                                real_gap_len = raw_gap
                                
                        if max_effective_gap >= 3:
                            rec_time = f"⏰ {best_hour:02d}:00"
                            rec_desc = f"심야(00~08시)를 제외한 '순수 영업 유효시간'이 가장 긴 구간입니다. (총 {real_gap_len}시간 단독 노출)"
                        else:
                            rec_time = "🔥 분산 타격"
                            rec_desc = "경쟁사가 쉴 새 없이 갱신 중입니다. 고정 시간 대신 봇을 통한 수시 방어가 필수입니다."
                
                b_ranks_hist = bdf.groupby('수집일시')['전체순위_숫자'].min()
                survival_rate = (len(b_ranks_hist) / total_sessions) * 100 if total_sessions > 0 else 0
                
                if survival_rate >= 80: roi_status, roi_col = "🟢 S급 (집중 타격)", "#10b981"
                elif survival_rate >= 40: roi_status, roi_col = "🟡 A급 (가성비 방어)", "#f59e0b"
                else: roi_status, roi_col = "🔴 불량 (광고 중단)", "#ef4444"

                st.markdown(f"""
                <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 15px; margin-bottom: 30px;">
                    <div style="background-color: #f8fafc; padding: 20px; border-radius: 12px; border-top: 4px solid #3182f6; box-shadow: 0 2px 4px rgba(0,0,0,0.02);">
                        <div style="font-size: 13px; color: #64748b; font-weight: bold; margin-bottom: 5px;">🏆 현재 내 순위 및 1위 업체</div>
                        <div style="font-size: 26px; font-weight: 800; color: #1e3a8a;">{my_rank}{'위' if isinstance(my_rank, int) else ''}</div>
                        <div style="font-size: 13px; color: #475569; margin-top: 5px;">현재 1위: {top_realtor_masked}</div>
                    </div>
                    <div style="background-color: #f8fafc; padding: 20px; border-radius: 12px; border-top: 4px solid {renew_col}; box-shadow: 0 2px 4px rgba(0,0,0,0.02);">
                        <div style="font-size: 13px; color: #64748b; font-weight: bold; margin-bottom: 5px;">🔥 타사 광고 갱신 빈도</div>
                        <div style="font-size: 24px; font-weight: 800; color: {renew_col};">{renew_status}</div>
                        <div style="font-size: 13px; color: #475569; margin-top: 5px;">분석 기간 내 총 {total_renews}회 갱신됨</div>
                    </div>
                    <div style="background-color: #f8fafc; padding: 20px; border-radius: 12px; border-top: 4px solid #8b5cf6; box-shadow: 0 2px 4px rgba(0,0,0,0.02);">
                        <div style="font-size: 13px; color: #64748b; font-weight: bold; margin-bottom: 5px;">🎯 AI 추천 타격 시간대</div>
                        <div style="font-size: 26px; font-weight: 800; color: #8b5cf6;">{rec_time}</div>
                        <div style="font-size: 13px; color: #475569; margin-top: 5px;">{rec_desc}</div>
                    </div>
                    <div style="background-color: #f8fafc; padding: 20px; border-radius: 12px; border-top: 4px solid {roi_col}; box-shadow: 0 2px 4px rgba(0,0,0,0.02);">
                        <div style="font-size: 13px; color: #64748b; font-weight: bold; margin-bottom: 5px;">📊 네이버 노출 생존율 (ROI)</div>
                        <div style="font-size: 26px; font-weight: 800; color: {roi_col};">{survival_rate:.1f}%</div>
                        <div style="font-size: 13px; color: #475569; margin-top: 5px;">알고리즘 평가: {roi_status}</div>
                    </div>
                </div>
                """, unsafe_allow_html=True)

                def get_bundle_state(grp):
                    first_place = grp[grp['묶음내순위_숫자'] == 1]
                    realtor = first_place['부동산명'].iloc[0] if not first_place.empty else grp.sort_values('묶음내순위_숫자')['부동산명'].iloc[0]
                    return pd.Series({'전체순위': grp['전체순위_숫자'].min(), '최상단부동산': realtor})
                
                b_hist = bdf.groupby('수집일시').apply(get_bundle_state, include_groups=False).reset_index()
        
                # ⭐ [핵심 해결] 엉뚱한 단지 시간이 섞이지 않도록, 현재 선택된 단지(comp_df)의 시간만 뼈대로 씁니다.
                comp_times = comp_df['수집일시'].drop_duplicates().sort_values().reset_index(drop=True)
                t_hist = pd.merge(pd.DataFrame({'수집일시': comp_times}), b_hist, on='수집일시', how='left')
                
                t_hist['전체순위차트용'] = t_hist['전체순위'].fillna(31)

                df_exec = load_renewal_logs()
                renew_times = []
                if not df_exec.empty and len(df_exec) > 1:
                    df_exec.columns = df_exec.iloc[0]; df_exec = df_exec[1:].copy()
                    m_id = str(bdf['고유번호'].iloc[0]).strip()
                    m_renews = df_exec[df_exec.iloc[:, 1].astype(str).str.strip() == m_id]
                    renew_times = pd.to_datetime(m_renews.iloc[:, 0]).tolist()

                fig2 = px.line(t_hist, x='수집일시', y='전체순위차트용', markers=True, title=f"📈 [{mask_text(search_bundle)}] 롤링 순위 추적 (🚀 AI 갱신 시점)", color_discrete_sequence=['#3182f6'])
                
                for rt in renew_times:
                    if start_dt <= rt <= end_dt:
                        fig2.add_vline(x=rt, line_dash="dash", line_color="#ef4444", annotation_text="🚀갱신")
                
                fig2.update_yaxes(autorange="reversed", range=[31.5, 0.5])
                st.plotly_chart(fig2, use_container_width=True)

                # 💡 강제 로딩 일으키던 클릭 연동 기능 영구 삭제, 단순 뷰어로만 제공
                st.markdown("<br><hr>", unsafe_allow_html=True)
                st.markdown("#### **📊 단지 내 전체 매물 분포도 요약**")
                st.caption("오른쪽 위에 있을수록 네이버 알고리즘 점수가 높은 S급 매물입니다. (해당 차트는 전체 현황 참고용입니다.)")
                
                if not bp_df.empty:
                    fig_scatter = px.scatter(
                        bp_df, x='생존율_num', y='평균 순위', 
                        color='AI 추천 액션', 
                        hover_data=['매물 스펙 (동/호수/가격)'],
                        color_discrete_map={
                            "🟢 S급 (집중 타격)": "#10b981", 
                            "🟡 A급 (가성비 방어)": "#f59e0b", 
                            "🔴 불량 (광고 중단)": "#ef4444"
                        }
                    )
                    fig_scatter.update_yaxes(autorange="reversed")
                    fig_scatter.update_layout(xaxis_title="매물 생존율 (%)", yaxis_title="평균 노출 순위")
                    
                    st.plotly_chart(fig_scatter, use_container_width=True)

            # --- (기존 개별 매물 차트 코드 아래에 추가) ---
            st.markdown("<br><hr>", unsafe_allow_html=True)
            st.markdown(f"#### 🌀 **[{search_comp}] 단지 전체 매물 롤링 궤적 (스파게티 차트)**")
            st.caption("💡 단지 내 매물의 순위 변동을 봅니다. 선들이 넓게 퍼질수록 네이버의 롤링이 극심하다는 뜻입니다.")

            if not comp_df.empty:
                all_lines_df = comp_df.copy()
                # 💡 21에서 31로 변경
                all_lines_df['전체순위_시각화'] = all_lines_df['전체순위_숫자'].fillna(31) 
                all_lines_df['매물명_축약'] = all_lines_df['매물묶음키'].apply(mask_text)

                unique_bundles = sorted(all_lines_df['매물명_축약'].unique())
                selected_bundles = st.multiselect(
                    "🔎 비교할 매물을 선택하세요 (여러 개 선택 가능, 비워두면 단지 전체 표시)",
                    options=unique_bundles,
                    default=[]
                )

                if selected_bundles:
                    plot_df = all_lines_df[all_lines_df['매물명_축약'].isin(selected_bundles)].copy()
                else:
                    plot_df = all_lines_df.copy()
    
                # ⭐ [핵심 추가] MultiIndex 에러 방지: 동일 시간, 동일 매물 중복 데이터 제거
                plot_df = plot_df.drop_duplicates(subset=['수집일시', '매물명_축약'])
    
                # 이빨 빠진 시간에 선이 가로지르지 않고 '권외(31위)'로 내리꽂히도록 빈 시간 채워넣기
                all_times = comp_df['수집일시'].drop_duplicates()
                plot_items = plot_df['매물명_축약'].unique()
                
                idx = pd.MultiIndex.from_product([all_times, plot_items], names=['수집일시', '매물명_축약'])
                full_plot_df = plot_df.set_index(['수집일시', '매물명_축약']).reindex(idx).reset_index()
                
                full_plot_df['전체순위_시각화'] = full_plot_df['전체순위_시각화'].fillna(31)
                full_plot_df['부동산명'] = full_plot_df['부동산명'].fillna('권외 (30위 밖)')
    
                fig_spaghetti = px.line(
                    full_plot_df, # plot_df 대신 그리드가 채워진 full_plot_df 사용
                    x='수집일시', 
                    y='전체순위_시각화', 
                    color='매물명_축약', 
                    markers=True,
                    hover_data=['부동산명']
                )
                
                # 💡 Y축 범위를 31.5로 늘림
                fig_spaghetti.update_yaxes(autorange="reversed", range=[31.5, 0.5])
                
                fig_spaghetti.update_layout(
                    height=600, 
                    legend=dict(
                        title="매물 리스트",
                        orientation="v",
                        yanchor="top", y=1,
                        xanchor="left", x=1.02 
                    ),
                    margin=dict(r=250) 
                )
                
                st.plotly_chart(fig_spaghetti, use_container_width=True)
    # ==========================================================
    # 탭 3. 🎯 내 매물 방어 현황 (액션)
    # ==========================================================
    elif selected_menu == "🎯 내 매물 방어 현황 (액션)":
        st.info("💡 **내 매물 집중 관리:** 현재 상위권에서 밀려난 매물, 공략하기 좋은 빈집, AI 추천 시간, 그리고 매물별 알고리즘 진단표를 확인하세요.")
        
        act_tab1, act_tab2, act_tab3, act_tab4 = st.tabs(["🚨 상위권 탈환 필요 매물", "🎯 경쟁이 적은 매물", "⚔️ AI 맞춤 갱신 전략", "📉 단지별 노출 롤링 진단"])
        
        with act_tab1:
            st.markdown("#### 경쟁 부동산에 밀려 상위권에서 이탈한 매물")
            st.caption("🔍 **[도출 원리]** 묶음 규모별 상위권 노출 기준(최대 3위) 밖으로 밀려나 즉각적인 재광고 조치가 필요한 매물만 필터링합니다.")
            if not danger_ls.empty:
                danger_show = danger_ls[['수집일시', '단지명', '동/호수', '층/타입', '거래방식', '묶음내순위_숫자', '최상단부동산']].copy()
                danger_show['동/호수'] = danger_show['동/호수'].apply(mask_text)
                danger_show['단지명'] = danger_show['단지명'].apply(mask_text)
                danger_show['최상단부동산'] = danger_show['최상단부동산'].apply(lambda x: mask_text(x, True))
                st.dataframe(danger_show, use_container_width=True)
            else: st.success("현재 모든 매물이 상위 안전권에 있습니다!")
            
        with act_tab2:
            st.markdown("#### 🧊 방치된 빈집 vs 🔥 피 튀기는 격전지")
            st.caption("🔍 **[도출 원리]** 롤링에 의한 일시적 누락 착시를 필터링하고, 경쟁사들이 실제로 포인트를 지불한 '확인일자' 변동 내역만을 추적하여 진짜 방치된 매물과 과열된 매물을 구분합니다.")

            c_empty, c_red = st.columns(2)
            with c_empty:
                st.markdown("""
                <div style="background-color: #f0fdf4; padding: 15px; border-radius: 10px; border-top: 4px solid #10b981; margin-bottom: 15px;">
                    <h5 style="color:#047857; margin:0;">🧊 방치된 빈집 (블루오션)</h5>
                    <p style="font-size:13px; color:#475569; margin:5px 0 0 0;">48시간 이상 경쟁사가 갱신하지 않는 매물입니다. 최소 비용으로 장시간 노출이 가능합니다.</p>
                </div>
                """, unsafe_allow_html=True)
                
                if not my_empty.empty:
                    df_empty_show = pd.merge(my_empty, bundle_info, on='매물묶음키', how='left')
                    df_empty_show['방치일수'] = df_empty_show['방치시간'].apply(lambda x: f"D+{int(x // 24)}일")
                    df_empty_show['단지명'] = df_empty_show['단지명'].apply(mask_text)
                    df_empty_show['동/호수'] = df_empty_show['동/호수'].apply(mask_text)
                    df_empty_show['층/타입'] = df_empty_show['층/타입'].apply(mask_text)
                    st.dataframe(df_empty_show[['단지명', '동/호수', '층/타입', '방치일수']], use_container_width=True)
                else:
                    st.info("현재 분석된 48시간 이상 빈집이 없습니다.")

            with c_red:
                st.markdown("""
                <div style="background-color: #fef2f2; padding: 15px; border-radius: 10px; border-top: 4px solid #ef4444; margin-bottom: 15px;">
                    <h5 style="color:#b91c1c; margin:0;">🔥 초경쟁 격전지 (레드오션)</h5>
                    <p style="font-size:13px; color:#475569; margin:5px 0 0 0;">경쟁사들이 쉴 새 없이 광고를 갱신하며 치고받는 매물입니다. 자동화 봇을 통한 집중 방어가 필수적입니다.</p>
                </div>
                """, unsafe_allow_html=True)
                
                if not my_red.empty:
                    df_red_show = pd.merge(my_red, bundle_info, on='매물묶음키', how='left')
                    df_red_show['단지명'] = df_red_show['단지명'].apply(mask_text)
                    df_red_show['동/호수'] = df_red_show['동/호수'].apply(mask_text)
                    st.dataframe(df_red_show[['단지명', '동/호수', '층/타입', '경쟁사_갱신횟수']], use_container_width=True)
                else:
                    st.info("현재 과열된 경쟁 격전지가 없습니다.")
            
        with act_tab3:
            st.markdown("#### 매물별 AI 최적 갱신 시간 추천")
            st.caption("🔍 **[도출 원리]** 해당 매물에 등록한 경쟁사들의 과거 갱신 기록을 분석하여 '가장 많이 갱신한 시간대(최빈값)'를 구한 뒤, 그 광고 집중 기간이 끝나는 직후 시간을 추천합니다.")
            
            vip_current = t_df[t_df['부동산명'].str.contains(filter_realtor_name, na=False)]
            vip_bundles = vip_current['매물묶음키'].dropna().unique()
            battle_data = []

            for b_key in vip_bundles:
                b_history = t_df[t_df['매물묶음키'] == b_key]
                if b_history.empty: continue

                danji, dongho, floor_type = b_history['단지명'].iloc[0], b_history['동/호수'].iloc[0], b_history['층/타입'].iloc[0]
                full_dongho_str = f"{dongho} ({floor_type})"
                
                latest_b = b_history[b_history['수집일시'] == b_history['수집일시'].max()]
                comp_count = len(latest_b['부동산명'].unique())
                
                b_boosted = boosted_df[boosted_df['매물묶음키'] == b_key]
                
                if len(b_boosted) < 3:
                    market_status = "⏳ 분석 중"
                    rec_time = "-"
                    rec_reason = "패턴 도출을 위한 데이터 부족 (최소 3~5일치 누적 필요)"
                else:
                    freq = len(b_boosted)
                    if freq >= 10: market_status = "🔥 과열 (빈번한 갱신)"
                    elif freq >= 5: market_status = "⚠️ 보통 (주기적 갱신)"
                    else: market_status = "💧 안정 (갱신 적음)"
                    
                    peak_hour = int(b_boosted['수집일시'].dt.hour.mode()[0])
                    rec_time = f"⏰ {(peak_hour + 1) % 24:02d}:00"
                    rec_reason = f"경쟁사 주력 타격시간({peak_hour}시) 감지. 이후 시간대 선점 권장"

                battle_data.append({
                    "단지명": mask_text(danji), 
                    "동/호수 및 스펙": mask_text(full_dongho_str), 
                    "경쟁사 수": f"{comp_count}곳", 
                    "시장 상태": market_status, 
                    "⭐ 추천 갱신시간": rec_time, 
                    "전략 사유": rec_reason, 
                    "원래키": b_key 
                })

            if battle_data:
                battle_df = pd.DataFrame(battle_data)
                st.dataframe(battle_df[["단지명", "동/호수 및 스펙", "경쟁사 수", "시장 상태", "⭐ 추천 갱신시간", "전략 사유"]], use_container_width=True)

        with act_tab4:
            st.markdown("#### 🌀 단지별 알고리즘 변동성 진단")
            st.caption("해당 단지에서 네이버 노출 순위가 얼마나 요동치고 있는지 진단합니다.")
            
            all_valid_ranks = t_df.dropna(subset=['전체순위_숫자'])
            if not all_valid_ranks.empty:
                market_volatility = all_valid_ranks.groupby('단지명')['전체순위_숫자'].std().mean()
                # ⭐ 롤링 지수라는 말 대신 '순위 요동/경쟁 과열'로 표현
                if market_volatility >= 4: m_status, m_col = "🌋 순위 변화 심함", "#ef4444"
                elif market_volatility >= 2: m_status, m_col = "🌊 변동 잦음", "#f59e0b"
                else: m_status, m_col = "💧 비교적 안정", "#10b981"
                
                st.markdown(f"""
                <div style="background-color: {m_col}; padding: 10px 20px; border-radius: 10px; color: white; font-weight: bold; margin-bottom: 20px;">
                    📡 현재 이 단지의 알고리즘 변동 상태: {m_status} (평균 {market_volatility:.1f}계단씩 뒤섞임)
                </div>
                """, unsafe_allow_html=True)

            tr_comp = st.selectbox("진단할 단지명 선택", sorted(t_df['단지명'].dropna().unique()), key="tr_comp_act")
            
            if tr_comp:
                comp_df = t_df[t_df['단지명'] == tr_comp]
                
                st.markdown(f"##### 🔍 [{mask_text(tr_comp)}] 매물별 광고 타산성(ROI) 진단")
                
                total_sessions = comp_df['수집일시'].nunique()
                bundle_power = []
                
                for b_key, b_grp in comp_df.groupby('매물묶음키'):
                    b_ranks = b_grp.groupby('수집일시')['전체순위_숫자'].min()
                    appearances = len(b_ranks)
                    survival_rate = (appearances / total_sessions) * 100 if total_sessions > 0 else 0
                    avg_rank = b_ranks.mean()
                    
                    is_mine = "✅" if filter_realtor_name in b_grp['부동산명'].values else ""
                    
                    bundle_power.append({
                        '내 매물': is_mine,
                        '매물 스펙 (동/호수/가격)': mask_text(b_key),
                        '평균 순위': round(avg_rank, 1) if appearances > 0 else 999,
                        '생존율': f"{round(survival_rate, 1)}%",
                        '생존율_num': survival_rate,
                        '원래키': b_key
                    })
                    
                bp_df = pd.DataFrame(bundle_power)
                if not bp_df.empty:
                    bp_df = bp_df.sort_values(by=['생존율_num', '평균 순위'], ascending=[False, True])
                    
                    def get_action_plan(sr):
                        if sr >= 80: return "🟢 S급 매물 (투자 대비 효율이 좋음. 예산 집중 추천)"
                        elif sr >= 40: return "🟡 A급 매물 (투자 대비 효율이 적음. 선택적 집중 추천)"
                        else: return "🔴 F급 매물 (투자 대비 효율이 없음. 잠시 중단 추천)"
                        
                    def get_reason(sr):
                        # ⭐ '1위' 단어 삭제 및 '롤링' 등 난해한 용어를 직관적인 결과로 치환
                        if sr >= 80: return "네이버 알고리즘 우대 매물 (네이버 부동산에서 상단 노출될 확률이 높음)"
                        elif sr >= 40: return "순위 변동이 잦은 일반 매물 (네이버 부동산에서 상단 노출될 확률이 적음)"
                        else: return "거의 노출이 되지 않는 불량 매물 (광고비를 써도 노출되지 않을 확률이 높)"

                    bp_df['AI 추천 액션'] = bp_df['생존율_num'].apply(get_action_plan)
                    bp_df['진단 사유'] = bp_df['생존율_num'].apply(get_reason)
                    
                    my_bp = bp_df[bp_df['내 매물'] == "✅"]
                    if not my_bp.empty:
                        waste_count = len(my_bp[my_bp['생존율_num'] < 40])
                        focus_count = len(my_bp[my_bp['생존율_num'] >= 80])
                        
                        st.markdown(f"""
                        <div style="background-color: #f8fafc; border: 1px solid #e2e8f0; border-radius: 10px; padding: 15px; margin-bottom: 20px;">
                            <strong style="color:#1e3a8a; font-size: 16px;">💡 AI 대표님 매물 예산 컨설팅 요약</strong><br>
                            <span style="color:#ef4444; font-weight:bold;">🚨 광고비 누수 경고:</span> 현재 대표님 매물 중 <b>{waste_count}개</b>는 알고리즘 점수가 낮아 봇을 돌려도 20위 밖으로 튕겨나갑니다.<br>
                            <span style="color:#10b981; font-weight:bold;">🎯 집중 타격 추천:</span> 반면 <b>{focus_count}개</b>는 상위권 안착률이 매우 높은 S급 매물입니다. 이 매물들에 자동 갱신(봇)을 집중하시면 상위권을 차지할 수 있습니다.
                        </div>
                        """, unsafe_allow_html=True)

                    st.dataframe(bp_df[['내 매물', '매물 스펙 (동/호수/가격)', '생존율', '평균 순위', 'AI 추천 액션', '진단 사유']], use_container_width=True)
                    
                    st.markdown("**📊 매물 분포도 (오른쪽 위에 있을수록 S급 매물입니다)**")
                    fig_scatter = px.scatter(
                        bp_df, x='생존율_num', y='평균 순위', 
                        color='AI 추천 액션', 
                        hover_data=['매물 스펙 (동/호수/가격)'],
                        color_discrete_map={
                            "🟢 집중 타격 (예산 집중)": "#10b981", 
                            "🟡 가성비 방어 (틈새 공략)": "#f59e0b", 
                            "🔴 광고 중단 (인증 재등록)": "#ef4444"
                        }
                    )
                    fig_scatter.update_yaxes(autorange="reversed")
                    fig_scatter.update_layout(xaxis_title="매물 생존율 (%)", yaxis_title="평균 노출 순위")
                    st.plotly_chart(fig_scatter, use_container_width=True)

    # ==========================================================
    # 탭 4. 📡 시장 & 경쟁사 동향 (분석)
    # ==========================================================
    elif selected_menu == "📡 시장 & 경쟁사 동향 (분석)":
        st.info("💡 **심층 분석:** 단지별 점유율과 경쟁사의 평균 갱신 빈도(예산 지출) 등 딥한 시장 분석을 확인합니다.")
        
        ana_tab1, ana_tab2 = st.tabs(["🏆 단지별 점유율(M/S)", "📊 경쟁사 활동 패턴"])
        
        with ana_tab1:
            st.caption(r"🔍 **[도출 원리]** 단지별 파워 점수 공식: $10 + \left(\frac{10}{\text{묶음내 순위}}\right) + (\text{묶음 총 개수} \times 0.1)$ (순위가 높고 묶음 규모가 큰 매물일수록 높은 가중치 부여)")
            filter_comp = st.selectbox("단지 필터", complex_list_with_all, key="ms_comp")
            ms_df = ms_counts.copy()
            if filter_comp != "전체 단지": ms_df = ms_df[ms_df['단지명'] == filter_comp]
            
            # 💡 [핵심 수정] 먼저 이름을 축약한 뒤에 그룹(groupby)으로 묶어야 겹치는 막대기 없이 깔끔하게 합산됩니다.
            ms_df['부동산명_축약'] = ms_df['부동산명'].apply(lambda x: mask_text(clean_realtor_name(x), True))
            agg_ms = ms_df.groupby('부동산명_축약').agg({'매물건수':'sum', '총점수':'sum'}).reset_index().sort_values('총점수', ascending=False)
            
            c_m1, c_m2 = st.columns([1, 1])
            with c_m1:
                st.dataframe(agg_ms.rename(columns={'부동산명_축약': '부동산명'}), use_container_width=True)
            with c_m2:
                top10 = agg_ms.head(10).sort_values('총점수', ascending=True)
                fig = px.bar(top10, x='총점수', y='부동산명_축약', orientation='h', title=f"{mask_text(filter_comp)} 점유율 Top 10", text='총점수', color_discrete_sequence=['#3182f6'])
                fig.update_layout(barmode='group') # 만약을 위한 겹침 방지 레이아웃 강제 설정
                st.plotly_chart(fig, use_container_width=True)
                
        with ana_tab2:
            st.markdown("경쟁 업체들이 주로 광고비를 지출하여 매물을 갱신하는 집중 시간대와 **평균 갱신 빈도(주기)**를 파악합니다.")
            st.caption("🔍 **[도출 원리]** 분석 기간(일수)을 경쟁사가 실제로 '확인일자'를 갱신한 날짜 수로 나누어 평균 갱신 주기(빈도)를 계산합니다.")
            
            if not boosted_df.empty:
                boosted_df['활동시간대'] = boosted_df['수집일시'].dt.hour
                analysis_days = max(1, (end_dt.date() - start_dt.date()).days + 1)
                
                def calc_freq(dates):
                    active_days = dates.dt.date.nunique()
                    if active_days == 0: return "알수없음"
                    freq = analysis_days / active_days
                    
                    if freq <= 1.3: return "🔥 매일 갱신"
                    elif freq <= 2.5: return "⚡ 2일에 1번"
                    elif freq <= 4.0: return "🚶 3~4일에 1번"
                    elif freq <= 8.0: return "🐢 주 1~2회"
                    else: return "💤 비정기적 (월 1~2회)"

                boosted_df['부동산명_정제'] = boosted_df['부동산명'].apply(clean_realtor_name)
                
                realtor_stats = boosted_df.groupby('부동산명_정제').agg(
                    총횟수=('부동산명_정제', 'count'),
                    평균시간=('활동시간대', lambda x: int(round(x.mean()))),
                    갱신빈도=('수집일시', calc_freq) 
                ).reset_index()
                
                # 아래 출력 코드가 그대로 작동하도록 컬럼명을 원래대로(부동산명) 돌려놓습니다.
                realtor_stats = realtor_stats.rename(columns={'부동산명_정제': '부동산명'})
                
                stat_df_final = realtor_stats.sort_values('총횟수', ascending=False)
                
                c_a, c_b = st.columns([1.2, 1])
                with c_a:
                    stat_show = stat_df_final.copy()
                    stat_show['부동산명'] = stat_show['부동산명'].apply(lambda x: mask_text(x, True))
                    stat_show['평균시간'] = stat_show['평균시간'].apply(lambda x: f"{x}시")
                    st.dataframe(stat_show[['부동산명', '총횟수', '평균시간', '갱신빈도']], use_container_width=True)
                with c_b:
                    hc = stat_df_final.groupby('평균시간').size().reset_index(name='부동산수')
                    fig3 = px.line(hc, x='평균시간', y='부동산수', title="시장 전체 광고 갱신 주력 시간대", markers=True, color_discrete_sequence=['#3182f6'])
                    st.plotly_chart(fig3, use_container_width=True)
            else:
                st.warning("선택한 기간 내에 경쟁사들의 갱신 활동이 없습니다.")

    # ==========================================================
    # 탭 5. 🎯 AI 매물 정밀 진단 (Beta)
    # ==========================================================
    elif selected_menu == "🎯 AI 매물 정밀 진단 (Beta)":
        st.info("💡 **3D 전략 매트릭스:** 매물의 단지 내 전체 순위(Y축)와 타사 경쟁 강도(X축)를 분석합니다. (점의 크기는 내 매물의 묶음 내 순위 방어력을 의미합니다)")

        if 't_df' in locals() and not t_df.empty:
            my_all = t_df[t_df['부동산명'].str.contains(filter_realtor_name, na=False)]
            if not my_all.empty:
                matrix_data = []
                for b_key, b_grp in my_all.groupby('매물묶음키'):
                    danji_name = b_grp['단지명'].iloc[0]
                    
                    # ⭐ Y축: 엑셀 D열 '전체순위' (매물 자체의 단지 내 노출도)
                    # 데이터에 '전체순위' 컬럼이 문자열일 수 있으므로 숫자로 변환
                    try:
                        b_grp_numeric = b_grp.copy()
                        b_grp_numeric['전체순위_숫자'] = pd.to_numeric(b_grp_numeric['전체순위'], errors='coerce')
                        avg_total_rank = b_grp_numeric.groupby('수집일시')['전체순위_숫자'].min().mean()
                    except:
                        avg_total_rank = 20 # 에러 시 기본값 처리
                        
                    # ⭐ Z축: '묶음내순위_숫자' (내 부동산이 이 묶음 안에서 몇 등인지)
                    avg_my_rank = b_grp.groupby('수집일시')['묶음내순위_숫자'].min().mean()
                    
                    # X축: 타사 갱신 빈도 (경쟁 강도)
                    comp_renews = len(boosted_df[boosted_df['매물묶음키'] == b_key]) if 'boosted_df' in locals() else 0
                    
                    # 💡 구간 분류 (기준: 전체노출 10위 / 갱신 3회)
                    if avg_total_rank <= 10.0 and comp_renews < 3:
                        cat, action = "🏆 상위권 - 블루오션", "매물 노출 훌륭함. 자유 갱신으로 상단 유지 권장"
                    elif avg_total_rank <= 10.0 and comp_renews >= 3:
                        cat, action = "🔥 상위권 - 격전지", "노출도 높고 경쟁 치열. AI 추천 시간에 방어 필수"
                    elif avg_total_rank > 10.0 and comp_renews >= 3:
                        cat, action = "💸 하위권 - 밑 빠진 독", "🚨 갱신해도 단지 하위권. 즉시 광고 중단 및 퀄리티 재점검!"
                    else:
                        cat, action = "🧊 하위권 - 악성 재고", "노출 안됨 + 경쟁 없음. 집주인 연락 및 조건 변경 요망"

                    # 버블 크기 계산 (1등일수록 50으로 가장 큼, 5등 밖이면 10으로 작음)
                    bubble_size = max(10, 60 - (avg_my_rank * 10))

                    matrix_data.append({
                        "매물명": f"{mask_text(danji_name)} {mask_text(b_key.split('|')[0].replace(danji_name, '').strip())}",
                        "전체순위": round(avg_total_rank, 1), # Y축
                        "타사갱신": comp_renews, # X축
                        "내_묶음내순위": round(avg_my_rank, 1), # Z축 툴팁용
                        "버블크기": bubble_size, # Z축 시각화용
                        "분류": cat,
                        "AI처방": action
                    })

                df_mx = pd.DataFrame(matrix_data)

                # 2. 시각화 (3D 버블 차트)
                import plotly.express as px
                fig_mx = px.scatter(
                    df_mx, x="타사갱신", y="전체순위", size="버블크기", color="분류",
                    hover_name="매물명", 
                    hover_data={"분류": False, "버블크기": False, "AI처방": True, "전체순위": True, "내_묶음내순위": True, "타사갱신": True},
                    color_discrete_map={
                        "🏆 상위권 - 블루오션": "#10b981", "🔥 상위권 - 격전지": "#3b82f6",
                        "💸 하위권 - 밑 빠진 독": "#ef4444", "🧊 하위권 - 악성 재고": "#94a3b8"
                    },
                    size_max=25
                )
                
                # Y축 뒤집기 (1위가 맨 위로)
                max_rank = max(20, df_mx['전체순위'].max() + 2)
                fig_mx.update_yaxes(autorange="reversed", title="매물 전체 노출 순위 (상단일수록 1등 ☝️)", range=[max_rank, 0])
                fig_mx.update_xaxes(title="타사 갱신 빈도 (우측일수록 경쟁 치열 👉)")
                
                fig_mx.add_hline(y=10.5, line_dash="dot", line_color="#cbd5e1", annotation_text="1페이지 노출 기준선 (10위)", annotation_position="bottom right")
                fig_mx.add_vline(x=2.5, line_dash="dot", line_color="#cbd5e1", annotation_text="경쟁 과열선 (3회)", annotation_position="top left")
                
                fig_mx.update_layout(height=550, margin=dict(t=20, b=20), legend_title_text="매물 효율 등급")
                st.plotly_chart(fig_mx, use_container_width=True)

                # 3. 처방 리스트 아코디언 정리
                st.markdown("### 📋 AI 실시간 진단 처방 요약")
                
                categories = [
                    ("💸 하위권 - 밑 빠진 독", "🚨 [광고 중단 권고] 돈을 써도 1페이지 밖입니다. 네이버 알고리즘 점수가 낮으니 즉시 광고를 멈추세요.", True),
                    ("🔥 상위권 - 격전지", "⚔️ [정밀 방어] 1페이지 노출 중이며 타사 갱신도 치열합니다. 주력 방어 매물입니다.", False),
                    ("🏆 상위권 - 블루오션", "🎯 [비용 절감] 1페이지 노출 중인데 타사 경쟁도 없습니다. 가성비 최고 매물입니다.", False),
                    ("🧊 하위권 - 악성 재고", "🔍 [점검 필요] 노출도 안 되고 경쟁도 없습니다. 조건 변경이 필요합니다.", False)
                ]

                for cat_name, desc, is_expanded in categories:
                    cat_df = df_mx[df_mx['분류'] == cat_name].sort_values('전체순위')
                    if not cat_df.empty:
                        with st.expander(f"{cat_name} ({len(cat_df)}건)", expanded=is_expanded):
                            st.caption(desc)
                            for _, row in cat_df.iterrows():
                                st.markdown(f"- **{row['매물명']}**: {row['AI처방']} (내 순위: {row['내_묶음내순위']}등 / 갱신: {row['타사갱신']}회)")
            else:
                st.warning("분석할 내 매물 데이터가 없습니다.")

    # ----------------------------------------------------------
    # 💡 모든 메뉴(if/elif)가 끝난 뒤 공통 실행되는 코드
    # ----------------------------------------------------------
    st.session_state['is_initialized'] = True

    WEB_APP_URL = "https://script.google.com/macros/s/AKfycbyUN2nh5rtcH8_ZznFhO7fee9FkjbmkOFlR4j3g4FJ356DvgOIgjPWQY6oF7aQoobx-sg/exec"
    log_script = f"""
    <script>
    window.addEventListener('beforeunload', function (event) {{
        const exitUrl = "{WEB_APP_URL}?timestamp=" + new Date().toLocaleString() + "&user_id={tracking_id}&action=퇴장";
        navigator.sendBeacon(exitUrl);
    }});
    </script>
    """
    components.html(log_script, height=0)

except Exception as e:
    st.error(f"🚨 데이터 처리 중 치명적 오류 발생: {e}")
