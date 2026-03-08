import streamlit as st
import pandas as pd
import plotly.express as px
import re
import os
import glob
import json
from datetime import datetime, timedelta

# --- [1] 비밀 장부(JSON) 로드 로직 개선 ---
def load_realtor_map():
    if os.path.exists("realtors.json"):
        with open("realtors.json", "r", encoding="utf-8") as f:
            try:
                data = json.load(f)
                return data
            except json.JSONDecodeError:
                st.error("🚨 'realtors.json' 파일의 문법이 틀렸습니다. (쉼표 등을 확인하세요)")
                return {"a123": "더자이디엘"}
            except Exception as e:
                return {"a123": "더자이디엘"}
    return {"a123": "더자이디엘"}

REALTOR_MAP = load_realtor_map()

# URL 파라미터 인식
query_params = st.query_params
user_id = query_params.get("id", "a123") 

# --- 🚀 데모 및 사용자 매핑 로직 ---
IS_DEMO_MODE = (user_id == "demo")
# JSON에 등록된 상호명을 가져오고, 없으면 기본값 설정
my_realtor = REALTOR_MAP.get(user_id, REALTOR_MAP.get("a123", "더자이디엘"))
# 화면 표시용 이름 (demo일 때만 JSON의 'demo' 상호를 쓰거나 하드코딩된 명칭 사용)
display_realtor = REALTOR_MAP.get("demo", "성우부동산(체험용)") if IS_DEMO_MODE else my_realtor

# --- 웹사이트 기본 세팅 ---
st.set_page_config(page_title="이실장 시장 통계 리포트", page_icon="📈", layout="wide")

# --- 유틸리티 함수 ---
def clean_realtor_name(name):
    pattern = r'공인중개사사무소|공인중개사|중개사무소|부동산|중개사|공인|중개|사무소'
    cleaned = re.sub(pattern, '', str(name)).strip()
    return cleaned if cleaned else str(name)

def mask_text(text, is_agent=False):
    if not IS_DEMO_MODE: return text
    if is_agent:
        # 내 부동산 이름과 같으면 체험용 이름으로 표시
        if text == my_realtor: return display_realtor
        return f"경쟁사 {hash(str(text)) % 100}"
    return re.sub(r'\d', '*', str(text))

@st.cache_data(show_spinner=False)
def process_data(df):
    df['수집일시'] = pd.to_datetime(df['수집일시'])
    df = df.sort_values('수집일시')
    
    # 5분 단위 세션 묶기
    time_diff_mins = df['수집일시'].diff().dt.total_seconds() / 60.0
    df['새_세션'] = (time_diff_mins > 5) | time_diff_mins.isna()
    df['세션ID'] = df['새_세션'].cumsum()
    session_rep = df.groupby('세션ID')['수집일시'].min().dt.floor('min').reset_index(name='대표수집일시')
    df = pd.merge(df, session_rep, on='세션ID', how='left')
    df['수집일시'] = df['대표수집일시']
    
    # 🚨 [강화된 왜곡 방지] 2.5시간 공백 후 1시간 동안의 데이터는 모두 왜곡 영역으로 설정
    session_times = df['수집일시'].drop_duplicates().sort_values()
    gap_check = session_times.diff().dt.total_seconds() / 3600.0
    gap_starts = session_times[gap_check > 2.5].tolist()
    
    df['왜곡영역'] = False
    for start_time in gap_starts:
        # 공백 후 재개된 시점부터 1시간 이내의 모든 세션을 왜곡으로 간주
        df.loc[(df['수집일시'] >= start_time) & (df['수집일시'] < start_time + timedelta(hours=1)), '왜곡영역'] = True
    
    df['전체순위_숫자'] = pd.to_numeric(df['전체순위'].astype(str).str.replace(r'[^0-9]', '', regex=True), errors='coerce').fillna(999).astype(int)
    df['묶음내순위_숫자'] = pd.to_numeric(df['묶음내순위'].astype(str).str.replace('단독', '1').str.replace(r'[^0-9]', '', regex=True), errors='coerce').fillna(999).astype(int)
    
    for col in ['동/호수', '층/타입', '거래방식', '가격']:
        if col in df.columns: df[col] = df[col].fillna("")
            
    df['확인일자_Date'] = pd.to_datetime(df['확인일자'], format='%y.%m.%d', errors='coerce')
    df['매물묶음키'] = df.apply(lambda r: f"{r['동/호수']} | {r['층/타입']} | {r['거래방식']} | {r['가격']}", axis=1)
    
    return df

@st.cache_data(ttl=600)
def load_server_data():
    current_dir = os.path.dirname(os.path.abspath(__file__))
    xlsx_files = glob.glob(os.path.join(current_dir, "data_*.xlsx"))
    if os.path.exists("data.xlsx"): xlsx_files.append("data.xlsx")
    if not xlsx_files: return None
    df_list = [pd.read_excel(f) for f in xlsx_files]
    return pd.concat(df_list, ignore_index=True).drop_duplicates()

raw_df = load_server_data()
if raw_df is None:
    st.error("🚨 서버에 데이터 파일이 없습니다.")
    st.stop()

# --- 사이드바 설정 (정밀 시간 설정) ---
st.sidebar.title("📅 리포트 상세 설정")
df = process_data(raw_df)
min_dt, max_dt = df['수집일시'].min(), df['수집일시'].max()

st.sidebar.markdown("### 🔍 분석 기간 (정밀 설정)")
col_sd, col_st = st.sidebar.columns(2)
start_date = col_sd.date_input("시작일", min_dt.date())
start_time = col_st.time_input("시작시간", min_dt.time())
start_filter = datetime.combine(start_date, start_time)

col_ed, col_et = st.sidebar.columns(2)
end_date = col_ed.date_input("종료일", max_dt.date())
end_time = col_et.time_input("종료시간", max_time.time())
end_filter = datetime.combine(end_date, end_time)

t_df = df[(df['수집일시'] >= start_filter) & (df['수집일시'] <= end_filter)].copy()

if t_df.empty:
    st.warning("선택한 시간 범위에 데이터가 없습니다.")
    st.stop()

# --- 핵심 로직 ---
bundle_keys = ['단지명', '동/호수', '층/타입', '거래방식', '가격']
group_keys = bundle_keys + ['부동산명']

uniq = t_df.drop_duplicates(subset=['매물번호', '부동산명', '단지명']).copy()
uniq['묶음_총개수'] = uniq.groupby(bundle_keys)['부동산명'].transform('count')
uniq['파워점수'] = 10 + (10 / uniq['묶음내순위_숫자']) + (uniq['묶음_총개수'] * 0.1)
ms_counts = uniq.groupby(['단지명', '부동산명']).agg(매물건수=('부동산명', 'count'), 총점수=('파워점수', 'sum')).reset_index()

my_ranks_dict = {}
for comp in sorted(t_df['단지명'].dropna().unique()):
    cdf = ms_counts[ms_counts['단지명'] == comp].copy()
    if cdf.empty: continue
    cdf['순위'] = cdf['총점수'].rank(ascending=False, method='min')
    my_r = cdf[cdf['부동산명'].str.contains(my_realtor)]
    my_ranks_dict[comp] = int(my_r['순위'].iloc[0]) if not my_r.empty else "권외"

# 갱신 데이터 추출 및 왜곡 방지 필터링
trk = t_df.sort_values(group_keys + ['수집일시']).copy()
trk['이전_확인일자'] = trk.groupby(group_keys)['확인일자'].shift(1)
boosted_raw = trk[(trk['이전_확인일자'].notna()) & (trk['이전_확인일자'] != trk['확인일자'])]
# 왜곡 영역에 포함되지 않은 클린한 데이터만 통계에 사용
boosted_df = boosted_raw[boosted_raw['왜곡영역'] == False].copy()

# --- 화면 렌더링 ---
st.title(f"📊 {display_realtor} 시장 분석 리포트")
if IS_DEMO_MODE: st.info("💡 체험판 모드: 경쟁사 실명 및 상세 주소 마스킹 처리됨")

col1, col2, col3, col4 = st.columns(4)
with col1:
    comp_sel = st.selectbox("단지 선택", sorted(t_df['단지명'].unique()), label_visibility="collapsed")
    rank = my_ranks_dict.get(comp_sel, "권외")
    st.subheader(f"{rank}위" if rank != "권외" else "권외")

# 상단 경쟁사 Metric 마스킹
top_spender_info = "분석 불가"
ts_name_raw = ""
if not boosted_df.empty:
    stat = boosted_df.groupby('부동산명').size().reset_index(name='횟수').sort_values('횟수', ascending=False)
    ts_name_raw = stat.iloc[0]['부동산명']
    masked_name = mask_text(clean_realtor_name(ts_name_raw), True)
    top_spender_info = f"{masked_name} ({stat.iloc[0]['횟수']}회)"

with c4: st.metric("🔥 최대 지출 경쟁사", top_spender_info)

# 탭 메뉴 (인덱싱 제거)
tab_report, tab_ms, tab_danger, tab_empty, tab_rolling, tab_timing, tab_stat = st.tabs([
    "📋 요약 리포트", "🏆 점유율(M/S)", "🚨 내 매물 순위 현황", "🎯 방치된 매물", 
    "📉 단지 별 노출 현황", "⏱️ 광고 갱신 팩트", "📊 경쟁사 요약"
])

with tab_report:
    st.subheader("💳 서비스 신청 안내")
    m1, m2, m3 = st.columns(3)
    m1.metric("시장 분석 리포트", "월 80,000원", "정가 10만원")
    m2.metric("광고 자동화", "월 80,000원", "정가 10만원")
    m3.metric("프리미엄 통합형", "월 130,000원", "정가 16만원")
    st.info("🏦 **결제 계좌:** 신한은행 110-388-348507 (예금주: 장성우)  \n📞 **문의:** 010-6502-2105")
    
    st.subheader("브리핑 내용")
    rank_str = " / ".join([f"{mask_text(k)} {v}위" for k, v in my_ranks_dict.items() if v != "권외"])
    danger_ls = t_df[(t_df['부동산명'].str.contains(my_realtor)) & (t_df['묶음내순위_숫자'] > 1)].drop_duplicates(subset=bundle_keys, keep='last')
    
    # 브리핑 텍스트 내 마스킹
    masked_ts_brief = mask_text(clean_realtor_name(ts_name_raw), True) if ts_name_raw else "없음"
    ts_count = stat.iloc[0]['횟수'] if not boosted_df.empty else 0
    
    briefing = f"""[📅 이실장 시장 동향 브리핑]\n(기간: {start_filter.strftime('%m/%d %H:%M')} ~ {end_filter.strftime('%m/%d %H:%M')})\n\n📊 시장 점유율 현황:\n대표님의 현재 단지별 랭킹은 [{rank_str if rank_str else "순위 없음"}] 입니다.\n\n🚨 방어전 필요: {len(danger_ls)}건\n🔥 경쟁사 위협: {masked_ts_brief} ({ts_count}회)"""
    st.text_area("복사하여 활용하세요.", value=briefing, height=350)

with tab_ms:
    agg = ms_counts.groupby('부동산명').agg({'매물건수':'sum', '총점수':'sum'}).reset_index().sort_values('총점수', ascending=False)
    agg['부동산명'] = agg['부동산명'].apply(lambda x: mask_text(x, True))
    st.dataframe(agg, use_container_width=True)

with tab_stat:
    st.subheader("📊 경쟁사별 평균 갱신 시간대 (왜곡 제거됨)")
    if not boosted_df.empty:
        boosted_df['시'] = boosted_df['수집일시'].dt.hour
        trend = boosted_df.groupby('부동산명').agg(
            갱신횟수=('시', 'count'),
            평균시간=('시', lambda x: int(round(x.mean())))
        ).reset_index().sort_values('갱신횟수', ascending=False)
        trend['부동산명'] = trend['부동산명'].apply(lambda x: mask_text(x, True))
        trend['평균시간'] = trend['평균시간'].apply(lambda x: f"{x}시")
        
        c_l, c_r = st.columns(2)
        c_l.dataframe(trend, use_container_width=True)
        
        dist = boosted_df.groupby('시').size().reset_index(name='건수')
        fig = px.line(dist, x='시', y='건수', title="시장 전체 광고 갱신 분포", markers=True, color_discrete_sequence=['#3182f6'])
        c_r.plotly_chart(fig, use_container_width=True)
    else: st.info("분석할 클린 데이터가 부족합니다.")

with tab_timing:
    st.subheader("⏱️ 광고 갱신 실시간 기록")
    log_df = boosted_raw[['수집일시', '부동산명', '단지명', '동/호수', '확인일자', '왜곡영역']].copy()
    log_df['부동산명'] = log_df['부동산명'].apply(lambda x: mask_text(x, True))
    log_df['단지명'] = log_df['단지명'].apply(mask_text)
    log_df['동/호수'] = log_df['동/호수'].apply(mask_text)
    log_df['비고'] = log_df['왜곡영역'].apply(lambda x: "⚠️ 수집공백 분석제외" if x else "정상")
    st.dataframe(log_df.sort_values('수집일시', ascending=False), use_container_width=True)

with tab_danger:
    st.subheader("🚨 1위에서 밀려난 내 매물")
    my_recent = t_df[t_df['부동산명'].str.contains(my_realtor)].sort_values('수집일시').drop_duplicates(subset=bundle_keys, keep='last')
    danger = my_recent[my_recent['묶음내순위_숫자'] > 1]
    st.dataframe(danger[bundle_keys + ['묶음내순위_숫자']], use_container_width=True)

with tab_empty:
    st.subheader("🎯 공격 타겟 (6시간 이상 방치 빈집)")
    lb = t_df.groupby(bundle_keys).tail(1).rename(columns={'수집일시': '최종수집일시'})
    # 방치 시간 계산 로직 유지...
    st.info("최신 데이터를 기준으로 분석 중입니다.")

except Exception as e:
    st.error(f"데이터 처리 중 오류 발생: {e}")
