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
            except json.JSONDecodeError as e:
                st.session_state['json_error'] = str(e)
                return {"a123": "더자이디엘"}
            except Exception:
                return {"a123": "더자이디엘"}
    return {"a123": "더자이디엘"}

REALTOR_MAP = load_realtor_map()

# URL 파라미터 인식
query_params = st.query_params
user_id = query_params.get("id", "demo")
ref_id = query_params.get("ref", "unknown")
tracking_id = f"user:{user_id}_ref:{ref_id}"

# --- [3] 구글 시트 유입 및 활동 로깅 로직 ---
def log_visitor_to_gsheets(uid, action="접속"):
    if "ref:unknown" in uid:
        return
        
    WEB_APP_URL = "https://script.google.com/macros/s/AKfycbyUN2nh5rtcH8_ZznFhO7fee9FkjbmkOFlR4j3g4FJ356DvgOIgjPWQY6oF7aQoobx-sg/exec"
    
    def send_log():
        try:
            KST = timezone(timedelta(hours=9))
            now_str = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
            requests.get(f"{WEB_APP_URL}?timestamp={now_str}&user_id={uid}&action={action}", timeout=10)
        except:
            pass
            
    threading.Thread(target=send_log, daemon=True).start()

if not st.session_state.get('entry_logged', False):
    log_visitor_to_gsheets(tracking_id, action="입장")
    st.session_state['entry_logged'] = True

# --- 🚀 데모 모드 데이터 매핑 로직 ---
IS_DEMO_MODE = (user_id == "demo")
active_id = "a123" if IS_DEMO_MODE else user_id

raw_realtor = REALTOR_MAP.get(active_id, REALTOR_MAP.get("a123", "더자이디엘"))
if isinstance(raw_realtor, dict):
    filter_realtor_name = raw_realtor.get("name", "더자이디엘")
    target_complexes = raw_realtor.get("complexes", [])
else:
    filter_realtor_name = str(raw_realtor)
    target_complexes = []

raw_demo = REALTOR_MAP.get("demo", "성우부동산(체험용)")
demo_name = raw_demo.get("name", "성우부동산(체험용)") if isinstance(raw_demo, dict) else str(raw_demo)
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
    cleaned = re.sub(pattern, '', str(name)).strip()
    return cleaned if cleaned else str(name)

@st.cache_data(max_entries=1, show_spinner=False)
def process_data(df):
    df['수집일시'] = pd.to_datetime(df['수집일시'])
    df = df.sort_values('수집일시')
    time_diff_mins = df['수집일시'].diff().dt.total_seconds() / 60.0
    df['새_세션'] = (time_diff_mins > 5) | time_diff_mins.isna()
    df['세션ID'] = df['새_세션'].cumsum()
    
    session_rep = df.groupby('세션ID')['수집일시'].min().dt.floor('min').reset_index(name='대표수집일시')
    df = pd.merge(df, session_rep, on='세션ID', how='left')
    df['수집일시'] = df['대표수집일시']
    
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
    target_files = []

    current_file = f"naver_market_report_{now.strftime('%Y_%m')}.xlsx"
    target_files.append(current_file)
    
    if now.day <= 15:
        last_month = now.replace(day=1) - timedelta(days=1)
        last_month_file = f"naver_market_report_{last_month.strftime('%Y_%m')}.xlsx"
        target_files.append(last_month_file)
        
    if os.path.exists(os.path.join(current_dir, "data.xlsx")):
        target_files.append("data.xlsx")
        
    df_list = []
    for file_name in target_files:
        file_path = os.path.join(current_dir, file_name)
        if os.path.exists(file_path):
            try:
                df = pd.read_excel(file_path)
                df_list.append(df)
            except Exception:
                pass 
                
    if not df_list:
        return None
        
    df = pd.concat(df_list, ignore_index=True).drop_duplicates()
    cutoff_date = pd.to_datetime('today') - pd.Timedelta(days=30)
    df['수집일시'] = pd.to_datetime(df['수집일시'])
    df = df[df['수집일시'] >= cutoff_date]
    return df

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
    # 🎯 [핵심] AI 마스터 결론
    # ==========================================================
    total_my_bundles = len(my_ls)
    safe_my_bundles = len(my_ls[my_ls['묶음내순위_숫자'] <= 3])
    safe_ratio = int((safe_my_bundles / total_my_bundles) * 100) if total_my_bundles > 0 else 0
    danger_count = len(danger_ls)
    empty_count = len(my_empty)
    
    # 💡 하이라이트 색상 완벽 복구 (총 매물: 보라색, 안전 매물: 파란색)
    master_conclusion = f"현재 대표님이 관리 중인 전체 VIP 매물 <b style='color:#8b5cf6;'>{total_my_bundles}개</b> 중, 상위권(3위 이내)에 안정적으로 방어 중인 매물은 <b style='color:#3182f6;'>{safe_my_bundles}개({safe_ratio}%)</b>입니다.<br>"
    
    if danger_count > 0:
        master_conclusion += f"상위권에서 이탈한 위험 매물이 <b style='color:#ef4444;'>{danger_count}개</b> 발생했으며, "
    else:
        master_conclusion += f"현재 상위권에서 이탈한 매물 없이 방어 중이며, "
        
    master_conclusion += f"타 부동산이 집중적으로 갱신하지 않는 매물이 <b style='color:#10b981;'>{empty_count}개</b> 포착되었습니다.<br>"
    
    if not boosted_df.empty:
        master_conclusion += f"오늘 경쟁사들의 주력 갱신 시간대는 <b>오전 {global_peak_hour}시</b>로 분석됩니다. 시스템이 해당 시간을 피해 <b><span style='color:#3182f6;'>{(global_peak_hour + 1) % 24:02d}시</span></b>에 광고를 진행하면 상위권 노출에 유리합니다.<br>"
    else:
        master_conclusion += "현재 경쟁사들의 뚜렷한 타격 패턴이 집계되지 않아 데이터를 누적하고 있습니다.<br>"
        
    # 💡 안내 문구 위치 변경, 볼드 처리, 시인성(색상) 대폭 강화
    master_conclusion += "<div style='font-size:15px; color:#1e293b; font-weight:600; margin-top: 15px; line-height: 1.6; background-color: #f1f5f9; padding: 15px; border-radius: 8px; border-left: 4px solid #94a3b8;'>"
    master_conclusion += "<i>* <b>롤링(Rolling)이란?</b> 네이버 부동산에서 광고 효율을 분산하기 위해 특정 시간이나 접속자마다 매물 노출 순위를 무작위로 뒤섞는 알고리즘 현상을 뜻합니다.</i><br>"
    master_conclusion += "<i style='margin-top: 8px; display: block;'>* <b>[데이터 수집 범위 안내]</b> 본 시스템은 실질적인 고객 유입이 발생하는 <b>상위 20위 이내의 매물만을 집중 스캔</b>합니다. 20위 밖으로 밀려난 매물은 광고 효율이 현저히 떨어지는 것으로 판단하여 '순위 확인 불가(권외)'로 표기됩니다.</i>"
    master_conclusion += "</div>"

    # --- 작전 브리핑(문자 발송용) 텍스트 ---
    briefing_date = end_dt.strftime('%Y-%m-%d')
    rank_summary = " / ".join([f"{mask_text(k)} {v}위" for k, v in my_ranks_dict.items() if v != '권외'])
    if not rank_summary: rank_summary = "분석된 순위 없음"
    
    # 💡 텍스트 복사용 조건부 문구 깔끔하게 분리
    plain_danger = f"상위권에서 이탈한 위험 매물이 {danger_count}개 발생했으며, " if danger_count > 0 else "현재 상위권에서 이탈한 매물 없이 방어 중이며, "
    plain_empty = f"타 부동산이 집중적으로 갱신하지 않는 매물이 {empty_count}개 포착되었습니다."
    
    briefing_text = f"""☀️ [{briefing_date} 작전 브리핑] AI 시장 동향 리포트
안녕하세요, {display_realtor} 대표님.
TOP RANK AI가 분석한 오늘의 시장 핵심 전략을 보고드립니다.

💡 [오늘의 AI 마스터 결론]
현재 대표님이 관리 중인 전체 VIP 매물 {total_my_bundles}개 중, 상위권(3위 이내)에 안정적으로 방어 중인 매물은 {safe_my_bundles}개({safe_ratio}%)입니다.
{plain_danger}{plain_empty}

🏆 1. 단지별 점유율(M/S) 현황
- 현재 대표님의 단지별 랭킹: [{rank_summary}]

📊 2. 주요 경쟁사 광고 패턴
- 최대 활동 업체: {top_spender if top_spender_raw_name else '없음'}
- 주력 갱신 시간대: {peak_hour_str if top_spender_raw_name else '데이터 분석 중'}"""

    # --- UI 렌더링 시작 ---
    components.html(f"""
    <div style="display: flex; align-items: center; margin-bottom: 25px; font-family: sans-serif;">
    <h1 style='font-size: 42px; font-weight: 800; color: #1e3a8a; margin: 0;'>📊 {display_realtor} 대표님을 위한 시장 동향</h1>
    <button id="copyBtn" style="background: none; border: none; padding: 0; margin-left: 15px; cursor: pointer; color: #b0bec5; transition: all 0.2s; outline: none;" title="오늘의 브리핑 문구 복사">
    <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" style="width: 24px; height: 24px;"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.823a4 4 0 015.656 0l4 4a4 4 0 01-5.656 5.656l-1.102 1.101"></path></svg>
    <span id="copyMsg" style="font-size: 14px; margin-left: 8px; font-weight: 600; opacity: 0; transition: opacity 0.3s; color: #10b981;"></span>
    </button>
    </div>
    <script>
    document.getElementById('copyBtn').onmouseover = function() {{ this.style.color = '#90a4ae'; }};
    document.getElementById('copyBtn').onmouseout = function() {{ this.style.color = '#b0bec5'; }};
    document.getElementById('copyBtn').onclick = function() {{
        navigator.clipboard.writeText(`{briefing_text}`).then(function() {{
            const btn = document.getElementById('copyBtn');
            const msg = document.getElementById('copyMsg');
            btn.style.color = '#10b981';
            msg.innerText = '✅ 복사완료';
            msg.style.opacity = '1';
            setTimeout(() => {{ btn.style.color = '#b0bec5'; msg.style.opacity = '0'; }}, 2000);
        }});
    }};
    </script>
    """, height=80)

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

    # --- 메뉴 순서 변경 ---
    selected_menu = st.radio(
        "메뉴 선택",
        ["📊 오늘의 AI 성과 (핵심 요약)", "🔍 통합 매물 검색 (심층 분석)", "🎯 내 매물 방어 현황 (액션)", "📡 시장 & 경쟁사 동향 (분석)"],
        horizontal=True,
        label_visibility="collapsed"
    )

    if 'last_logged_menu' not in st.session_state:
        st.session_state['last_logged_menu'] = selected_menu
    else:
        if st.session_state['last_logged_menu'] != selected_menu:
            log_visitor_to_gsheets(tracking_id, action=f"열람_{selected_menu}")
            st.session_state['last_logged_menu'] = selected_menu

    # ==========================================================
    # 탭 1. 📊 오늘의 AI 성과 (핵심 요약)
    # ==========================================================
    if selected_menu == "📊 오늘의 AI 성과 (핵심 요약)":
        
        # 💡 [시인성 극대화] 배경은 눈이 편안한 연한 색, 글씨 크기는 22px로 시원하게 확대
        st.markdown(f"""
        <div style="background-color: #f8fafc; border: 1px solid #e2e8f0; border-left: 6px solid #3182f6; padding: 30px; border-radius: 12px; margin-bottom: 25px;">
            <div style="display: flex; align-items: center; margin-bottom: 20px;">
                <span style="font-size: 32px; margin-right: 15px;">💡</span>
                <h3 style="margin: 0; color: #1e3a8a; font-weight: 800; font-size: 28px;">오늘의 AI 마스터 결론</h3>
            </div>
            <div style="font-size: 22px; line-height: 1.8; color: #0f172a; font-weight: 600; word-break: keep-all;">
                {master_conclusion}
            </div>
        </div>
        """, unsafe_allow_html=True)
        
        st.markdown(f"""
        <div class="strategy-grid" style="margin-top: 5px;">
            <div class="briefing-strategy-card">
                <span class="strategy-tag" style="background-color:#3182f6;">🛡️ 시장 방어전</span>
                <div class="briefing-content">
                    현재 대표님의 단지별 랭킹은<br>
                    <span style="color:#3182f6;">[{rank_summary}]</span> 입니다.
                </div>
            </div>
            <div class="briefing-strategy-card">
                <span class="strategy-tag" style="background-color:#ef4444;">⚔️ 상위권 탈환 필요</span>
                <div class="briefing-content">
                    상위 노출에서 밀려난 위험 매물이 <span style="color:#ef4444;">{danger_count}건</span> 발견되었습니다.
                </div>
            </div>
            <div class="briefing-strategy-card">
                <span class="strategy-tag" style="background-color:#10b981;">🎯 경쟁이 적은 매물</span>
                <div class="briefing-content">
                    D+2일(48시간) 이상 타사가 방치한 매물이 <span style="color:#10b981;">{empty_count}건</span> 입니다.
                </div>
            </div>
        </div>
        """, unsafe_allow_html=True)

        if IS_DEMO_MODE:
            now_kst = datetime.now(timezone(timedelta(hours=9)))
            dummy_logs = [
                {"갱신시간": (now_kst - timedelta(minutes=12)).strftime("%Y-%m-%d %H:%M:%S"), "단지명": "다산자이아이비플레이스", "매물상세": "1**동 (*4A)", "상태": "✅ 성공", "갱신 전 순위": "15위 (🔴하위권)", "갱신 후 순위": "1위 (🟢상위권)", "성과 요약": "🚀 14계단 상승"},
                {"갱신시간": (now_kst - timedelta(minutes=45)).strftime("%Y-%m-%d %H:%M:%S"), "단지명": "다산한양수자인리버팰리스", "매물상세": "1**3동 (*4B)", "상태": "✅ 성공", "갱신 전 순위": "8위 (🟡중위권)", "갱신 후 순위": "2위 (🟢상위권)", "성과 요약": "🚀 6계단 상승"},
                {"갱신시간": (now_kst - timedelta(hours=1, minutes=20)).strftime("%Y-%m-%d %H:%M:%S"), "단지명": "힐스테이트다산", "매물상세": "5**9동 (*4B)", "상태": "✅ 성공", "갱신 전 순위": "5위 (🟡중위권)", "갱신 후 순위": "1위 (🟢상위권)", "성과 요약": "🚀 4계단 상승"},
                {"갱신시간": (now_kst - timedelta(hours=2, minutes=5)).strftime("%Y-%m-%d %H:%M:%S"), "단지명": "다산유승한내들센트럴", "매물상세": "2**4동 (*4A)", "상태": "✅ 성공", "갱신 전 순위": "19위 (🔴하위권)", "갱신 후 순위": "3위 (🟢상위권)", "성과 요약": "🚀 16계단 상승"},
                {"갱신시간": (now_kst - timedelta(hours=3, minutes=40)).strftime("%Y-%m-%d %H:%M:%S"), "단지명": "다산e편한세상자이", "매물상세": "1**2동 (*4A)", "상태": "✅ 성공", "갱신 전 순위": "11위 (🔴하위권)", "갱신 후 순위": "1위 (🟢상위권)", "성과 요약": "🚀 10계단 상승"},
                {"갱신시간": (now_kst - timedelta(hours=5, minutes=15)).strftime("%Y-%m-%d %H:%M:%S"), "단지명": "다산펜테리움리버테라스I", "매물상세": "7**5동 (*4A)", "상태": "✅ 성공", "갱신 전 순위": "7위 (🟡중위권)", "갱신 후 순위": "2위 (🟢상위권)", "성과 요약": "🚀 5계단 상승"},
                {"갱신시간": (now_kst - timedelta(hours=6, minutes=50)).strftime("%Y-%m-%d %H:%M:%S"), "단지명": "다산신도시센트럴에일린의뜰", "매물상세": "8**3동 (*4B)", "상태": "✅ 성공", "갱신 전 순위": "14위 (🔴하위권)", "갱신 후 순위": "1위 (🟢상위권)", "성과 요약": "🚀 13계단 상승"},
                {"갱신시간": (now_kst - timedelta(hours=8, minutes=10)).strftime("%Y-%m-%d %H:%M:%S"), "단지명": "다산자이아이비플레이스", "매물상세": "1**3동 (1**A)", "상태": "✅ 성공", "갱신 전 순위": "3위 (🟢상위권)", "갱신 후 순위": "3위 (🟢상위권)", "성과 요약": "🛡️ 상위권 유지중"},
                {"갱신시간": (now_kst - timedelta(hours=10, minutes=25)).strftime("%Y-%m-%d %H:%M:%S"), "단지명": "힐스테이트다산", "매물상세": "5**1동 (*4A)", "상태": "✅ 성공", "갱신 전 순위": "9위 (🔴하위권)", "갱신 후 순위": "2위 (🟢상위권)", "성과 요약": "🚀 7계단 상승"},
            ]
            merged_df = pd.DataFrame(dummy_logs)
            success_count = len(merged_df)
            up_defense_count = len(merged_df)
            
        else:
            df_exec = load_renewal_logs()
            merged_df = pd.DataFrame()
            
            if not df_exec.empty and len(df_exec) > 1:
                try:
                    df_exec.columns = df_exec.iloc[0]; df_exec = df_exec[1:].copy()
                    df_exec.rename(columns={df_exec.columns[0]: '갱신시간', df_exec.columns[1]: '매물번호', df_exec.columns[2]: '상태', df_exec.columns[3]: '비고'}, inplace=True)
                    
                    # 💡 [수정] 층/타입/매물묶음키 데이터 추가 추출 (번호가 바뀌어도 추적하기 위함)
                    mapping_df = df[df['고유번호'] != '기록없음'][['고유번호', '단지명', '동/호수', '층/타입', '매물묶음키']].drop_duplicates(subset=['고유번호'], keep='last')
                    mapping_df.rename(columns={'고유번호': '매물번호'}, inplace=True)
                    
                    df_exec['매물번호'] = df_exec['매물번호'].astype(str).str.strip()
                    mapping_df['매물번호'] = mapping_df['매물번호'].astype(str).str.strip()
                    
                    merged_df = pd.merge(df_exec, mapping_df, on='매물번호', how='left')
                    merged_df['단지명'] = merged_df['단지명'].fillna("정보 수집중")
                    merged_df['동/호수'] = merged_df['동/호수'].fillna("-")
                    merged_df['층/타입'] = merged_df['층/타입'].fillna("-")
                    merged_df['매물상세'] = merged_df['동/호수'] + " (" + merged_df['층/타입'] + ")"
                    
                    merged_df['갱신시간'] = pd.to_datetime(merged_df['갱신시간'], errors='coerce')
                    merged_df = merged_df[(merged_df['갱신시간'] >= start_dt) & (merged_df['갱신시간'] <= end_dt)]
                    
                    def get_tier(rank, total):
                        if pd.isna(rank): return "-"
                        rank = int(rank)
                        if total <= 3: return "🟢상위권"
                        elif 4 <= total <= 5: return "🟢상위권" if rank <= 2 else "🟡중위권"
                        else: return "🟢상위권" if rank <= 3 else "🟡중위권" if rank <= 8 else "🔴하위권"

                    tracking_results = []
                    global_latest_time = df['수집일시'].max()

                    # 💡 [핵심 수정] 매물번호(ID) 추적이 아닌, 매물묶음키(스펙) + 내 부동산 이름으로 추적
                    for idx, row in merged_df.iterrows():
                        t0 = row['갱신시간']
                        if pd.isna(t0): continue
                        
                        target_bundle_key = row.get('매물묶음키')
                        
                        # 매물묶음키를 찾지 못한 경우 (엑셀에 아예 수집된 적이 없는 번호)
                        if pd.isna(target_bundle_key) or not target_bundle_key:
                            tracking_results.append(("기록 없음", "기록 없음", "추적 불가 (스펙 미상)"))
                            continue
                            
                        # 🔍 고유번호 무시! '같은 스펙(매물묶음키)'을 가진 '내 부동산'의 매물 이력만 시간순으로 가져옴
                        m_history = df[(df['매물묶음키'] == target_bundle_key) & (df['부동산명'].str.contains(filter_realtor_name, na=False))].sort_values('수집일시')
                        
                        if m_history.empty:
                            tracking_results.append(("기록 없음", "기록 없음", "추적 불가 (이력 없음)"))
                            continue
                            
                        before_df = m_history[m_history['수집일시'] <= t0]
                        after_df = m_history[m_history['수집일시'] > t0 + pd.Timedelta(seconds=10)]
                        
                        before_rank = int(before_df.iloc[-1]['묶음내순위_숫자']) if not before_df.empty else pd.NA
                        
                        if not after_df.empty:
                            after_rank = int(after_df.iloc[0]['묶음내순위_숫자'])
                            latest_time = after_df.iloc[0]['수집일시']
                        else:
                            after_rank = pd.NA
                            latest_time = before_df.iloc[-1]['수집일시'] if not before_df.empty else t0

                        total_comp = len(df[(df['수집일시'] == latest_time) & (df['매물묶음키'] == target_bundle_key)]['부동산명'].unique()) if target_bundle_key else 0
                        
                        b_tier = get_tier(before_rank, total_comp) if pd.notna(before_rank) else "-"
                        b_str = f"{before_rank}위 ({b_tier})" if pd.notna(before_rank) else "20위 밖 (권외)"
                        
                        time_passed = global_latest_time - t0
                        
                        if pd.notna(after_rank):
                            a_tier = get_tier(after_rank, total_comp)
                            a_str = f"{after_rank}위 ({a_tier})"
                            diff = (before_rank if pd.notna(before_rank) else 21) - after_rank
                            
                            if pd.notna(before_rank) and before_rank <= 3 and after_rank <= 3:
                                res = "🛡️ 상위권 유지중"
                            elif diff > 0: 
                                res = f"🚀 {diff}계단 상승"
                            else: 
                                if time_passed <= timedelta(hours=3): res = "⏳ 인덱싱 대기중"
                                elif time_passed <= timedelta(hours=12): res = "🌀 롤링 밀림 (확인 지연)"
                                else: res = "⚠️ 변동 없음 (확인 필요)"
                        else:
                            if time_passed <= timedelta(hours=3):
                                a_str, res = "⏳ 크롤링 대기 중", "⏳ 인덱싱 대기중"
                            elif time_passed <= timedelta(hours=12):
                                a_str, res = "🌀 20위 밖 (권외)", "🌀 롤링으로 인한 순위 확인 지연"
                            else:
                                a_str, res = "🔴 20위 밖 (권외)", "⚠️ 변동 없음 (확인 필요)"
                                
                        tracking_results.append((b_str, a_str, res))
                        
                    merged_df['갱신 전 순위'] = [x[0] for x in tracking_results]
                    merged_df['갱신 후 순위'] = [x[1] for x in tracking_results]
                    merged_df['성과 요약'] = [x[2] for x in tracking_results]
                    
                    merged_df = merged_df.sort_values(by='갱신시간', ascending=False)
                    
                    # 💡 여기서 표를 바로 그리지 않고 데이터만 저장합니다.
                    success_count = len(merged_df[merged_df['상태'].str.contains('성공', na=False)])
                    up_defense_count = len(merged_df[merged_df['성과 요약'].str.contains('상승|유지', na=False)])
                except Exception as e:
                    st.error(f"데이터 표시 중 오류: {e}")
                    success_count, up_defense_count = 0, 0
            else:
                success_count, up_defense_count = 0, 0
                
        pm_briefing_text = f"""🌙 [{end_dt.strftime('%Y-%m-%d')} 성과 브리핑] 자동 갱신 결과 보고

오늘 하루도 중개하시느라 고생 많으셨습니다, {display_realtor} 대표님.
시스템이 자동으로 갱신한 광고 현황 보고드립니다.

🚀 1. 자동 갱신 처리 결과
- 오늘 시스템이 자동으로 갱신 처리한 매물: 총 {success_count}건

📈 2. 순위 방어 및 상승 성과
- 갱신 직후 상위권 방어 및 탈환 성공: 총 {up_defense_count}건 
- 타사에 밀려났던 매물들을 최적의 타이밍에 복구하였습니다.

👉 오늘 자동 갱신된 매물 목록 확인하기
https://realestate-date-report.streamlit.app/?id={user_id}&ref={ref_id}"""

        # 💡 [순서 정상화] 1. 제목과 복사 버튼 출력 (이 아래 코드는 그대로 유지)
        components.html(f"""
        <div style="display: flex; align-items: center; font-family: sans-serif; padding: 15px 0;">
            <h3 style='color:#1e3a8a; margin: 0; font-size: 24px; font-weight: bold;'>🚀 AI 자동 갱신 성과</h3>
            <button id="copyBtnPm" style="background: none; border: none; padding: 0; margin-left: 15px; cursor: pointer; color: #94a3b8; outline: none;" title="오후 브리핑 복사">
                <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" style="width: 24px; height: 24px;"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.823a4 4 0 015.656 0l4 4a4 4 0 01-5.656 5.656l-1.102 1.101"></path></svg>
                <span id="copyMsgPm" style="font-size: 14px; margin-left: 8px; font-weight: 600; opacity: 0; transition: opacity 0.3s; color: #10b981;"></span>
            </button>
        </div>
        <script>
        document.getElementById('copyBtnPm').onclick = function() {{
            navigator.clipboard.writeText(`{pm_briefing_text}`).then(function() {{
                const msg = document.getElementById('copyMsgPm');
                msg.innerText = '✅ 복사완료';
                msg.style.opacity = '1';
                setTimeout(() => {{ msg.style.opacity = '0'; }}, 2000);
            }});
        }};
        </script>
        """, height=80)

        # 💡 [순서 정상화] 2. 안내 멘트 출력
        st.info("💡 **자동화 엔진 성과:** 시스템이 자동으로 광고를 갱신하여 상위권을 탈환한 내역입니다.")
        
        # 💡 [순서 정상화] 3. 표 출력!
        if not merged_df.empty:
            st.dataframe(merged_df[['갱신시간', '단지명', '매물상세', '상태', '갱신 전 순위', '갱신 후 순위', '성과 요약']], use_container_width=True)
        else:
            st.info("아직 수집된 자동 갱신 성과 로그가 없습니다.")

# 표와 결제 배너 사이에 넉넉한 여백(줄바꿈 2번)을 추가합니다.
        st.markdown("<br><br>", unsafe_allow_html=True)

        

    # 1-3. 하단: 서비스 결제 안내 (🚀 단일 9만원 배너로 변경)
        st.markdown("<br><hr>", unsafe_allow_html=True)
        st.markdown("<br><br>", unsafe_allow_html=True)
        pricing_card = """
        <div style="background: linear-gradient(135deg, #ffffff 0%, #f0f7ff 100%); border: 2px solid #3182f6; border-radius: 20px; padding: 40px 20px; text-align: center; box-shadow: 0 10px 30px rgba(49, 130, 246, 0.12); max-width: 800px; margin: 0 auto;">
            <div style="display: inline-block; background-color: #ef4444; color: white; padding: 6px 15px; border-radius: 20px; font-weight: 800; font-size: 14px; margin-bottom: 15px;">🚀 한정 특가 오픈</div>
            <h2 style="color: #1e3a8a; margin-bottom: 15px; font-weight: 800; font-size: 28px;">TOP RANK 광고 자동화 솔루션</h2>
            <p style="font-size: 22px; color: #334155; margin-bottom: 25px; font-weight: 700;">
                월 <span style="font-size: 32px; color: #3182f6;">90,000원</span>, 하루 단 <span style="font-size: 32px; color: #3182f6;">3,000원</span>으로<br>상위 노출 스트레스에서 완벽하게 해방되세요!
            </p>
            <div style="display: flex; justify-content: center; gap: 15px; margin-bottom: 30px; flex-wrap: wrap;">
                <span style="background-color: white; padding: 10px 20px; border-radius: 12px; border: 1px solid #dbeafe; color: #1e3a8a; font-weight: bold; box-shadow: 0 2px 4px rgba(0,0,0,0.02);">✔️ 24시간 무인 순위 방어</span>
                <span style="background-color: white; padding: 10px 20px; border-radius: 12px; border: 1px solid #dbeafe; color: #1e3a8a; font-weight: bold; box-shadow: 0 2px 4px rgba(0,0,0,0.02);">✔️ AI 시장 분석 리포트</span>
                <span style="background-color: white; padding: 10px 20px; border-radius: 12px; border: 1px solid #dbeafe; color: #1e3a8a; font-weight: bold; box-shadow: 0 2px 4px rgba(0,0,0,0.02);">✔️ 불량 매물 누수 진단</span>
            </div>
            <div style="background-color: #f8fafc; padding: 20px; border-radius: 15px; max-width: 500px; margin: 0 auto; border: 1px solid #e2e8f0;">
                <p style="font-size: 16px; color: #475569; margin: 0; line-height: 1.6;">
                    🏦 <b>결제 계좌:</b> 기업은행 174-117603-01-012 (예금주: 신성우)<br>
                    📞 <b>가입 문의:</b> 010-8416-2806
                </p>
            </div>
        </div>
        """
        st.markdown(pricing_card, unsafe_allow_html=True)

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
                
                if total_renews == 0: renew_status, renew_col = "🧊 갱신 없음 (빈집)", "#10b981"
                elif daily_renews >= 3: renew_status, renew_col = f"🔥 일평균 {daily_renews:.1f}회 (초경쟁)", "#ef4444"
                elif daily_renews >= 1: renew_status, renew_col = f"⚠️ 일평균 {daily_renews:.1f}회 (보통)", "#f59e0b"
                else: renew_status, renew_col = f"💧 주기적 갱신 (일 {daily_renews:.1f}회)", "#3b82f6"

                rec_time = "-"
                rec_desc = "데이터 누적 중"
                if total_renews >= 3:
                    peak_hour = int(b_boosted['수집일시'].dt.hour.mode()[0])
                    rec_time = f"⏰ {(peak_hour + 1) % 24:02d}:00"
                    rec_desc = f"타사 주력 갱신({peak_hour}시) 포착. 직후 선점 권장"
                
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
                t_hist = pd.merge(pd.DataFrame({'수집일시': global_times}), b_hist, on='수집일시', how='left')
                t_hist['전체순위차트용'] = t_hist['전체순위'].fillna(21)

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
                
                fig2.update_yaxes(autorange="reversed", range=[21.5, 0.5])
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
            st.markdown("#### 🌀 단지별 노출 롤링 및 갱신 성과 진단")
            st.caption("🔍 **[도출 원리]** 선택된 분석 기간 동안 해당 매물의 전체 노출 순위 변동폭을 바탕으로 롤링 심각도를 진단하며, 네이버 매물 진정성 점수를 역추산하여 타격 효율(ROI)을 판별합니다.")
            
            all_valid_ranks = t_df.dropna(subset=['전체순위_숫자'])
            if not all_valid_ranks.empty:
                market_volatility = all_valid_ranks.groupby('단지명')['전체순위_숫자'].std().mean()
                if market_volatility >= 4: m_status, m_col = "🌋 매우 극심", "#ef4444"
                elif market_volatility >= 2: m_status, m_col = "🌊 변동 주의", "#f59e0b"
                else: m_status, m_col = "💧 비교적 안정", "#10b981"
                
                st.markdown(f"""
                <div style="background-color: {m_col}; padding: 10px 20px; border-radius: 10px; color: white; font-weight: bold; margin-bottom: 20px;">
                    📡 현재 시장 전체 롤링 지수: {m_status} (평균 변동폭: {market_volatility:.1f}계단)
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
                        if sr >= 80: return "🟢 집중 타격 (예산 집중)"
                        elif sr >= 40: return "🟡 가성비 방어 (틈새 공략)"
                        else: return "🔴 광고 중단 (인증 재등록)"
                        
                    def get_reason(sr):
                        if sr >= 80: return "네이버 우대 매물 (갱신 시 1위 고정 확정적)"
                        elif sr >= 40: return "일반 매물 (롤링 치열, 지속적 봇 관리 필요)"
                        else: return "페널티 매물 (갱신해도 알고리즘에 의해 강제 누락됨)"

                    bp_df['AI 추천 액션'] = bp_df['생존율_num'].apply(get_action_plan)
                    bp_df['진단 사유'] = bp_df['생존율_num'].apply(get_reason)
                    
                    my_bp = bp_df[bp_df['내 매물'] == "✅"]
                    if not my_bp.empty:
                        waste_count = len(my_bp[my_bp['생존율_num'] < 40])
                        focus_count = len(my_bp[my_bp['생존율_num'] >= 80])
                        
                        st.markdown(f"""
                        <div style="background-color: #f8fafc; border: 1px solid #e2e8f0; border-radius: 10px; padding: 15px; margin-bottom: 20px;">
                            <strong style="color:#1e3a8a; font-size: 16px;">💡 AI 대표님 매물 예산 컨설팅 요약</strong><br>
                            <span style="color:#ef4444; font-weight:bold;">🚨 광고비 누수 경고:</span> 현재 대표님 매물 중 <b>{waste_count}개</b>는 알고리즘 점수가 낮아 봇을 돌려도 20위 밖으로 튕겨나갑니다. 즉시 갱신을 멈추고 집주인 인증을 다시 받으세요.<br>
                            <span style="color:#10b981; font-weight:bold;">🎯 집중 타격 추천:</span> 반면 <b>{focus_count}개</b>는 상위권 안착률이 매우 높은 S급 매물입니다. 이 매물들에 자동 갱신(봇)을 집중하시면 1위를 독식할 수 있습니다.
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
            agg_ms = ms_df.groupby('부동산명').agg({'매물건수':'sum', '총점수':'sum'}).reset_index().sort_values('총점수', ascending=False)
            
            c_m1, c_m2 = st.columns([1, 1])
            with c_m1:
                ms_show = agg_ms.copy()
                ms_show['부동산명'] = ms_show['부동산명'].apply(lambda x: mask_text(x, True))
                st.dataframe(ms_show, use_container_width=True)
            with c_m2:
                agg_ms['부동산명_축약'] = agg_ms['부동산명'].apply(lambda x: mask_text(clean_realtor_name(x), True))
                top10 = agg_ms.head(10).sort_values('총점수', ascending=True)
                fig = px.bar(top10, x='총점수', y='부동산명_축약', orientation='h', title=f"{mask_text(filter_comp)} 점유율 Top 10", text='총점수', color_discrete_sequence=['#3182f6'])
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

                realtor_stats = boosted_df.groupby('부동산명').agg(
                    총횟수=('부동산명', 'count'),
                    평균시간=('활동시간대', lambda x: int(round(x.mean()))),
                    갱신빈도=('수집일시', calc_freq) 
                ).reset_index()
                
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
