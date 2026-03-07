import streamlit as st
import pandas as pd
import plotly.express as px
import re
import os
import glob
import json
from datetime import datetime, timedelta

# --- 1. 웹사이트 기본 세팅 ---
st.set_page_config(page_title="이실장 시장 통계 리포트 PRO", page_icon="📈", layout="wide")

# --- 2. 비밀 장부(JSON) 로드 로직 ---
def load_realtor_map():
    if os.path.exists("realtors.json"):
        with open("realtors.json", "r", encoding="utf-8") as f:
            return json.load(f)
    return {"a123": "더자이디엘"} # 파일이 없을 때를 대비한 기본값

REALTOR_MAP = load_realtor_map()

# URL 파라미터 인식 (?id=a123 방식)
query_params = st.query_params
user_id = query_params.get("id", "a123") 
my_realtor = REALTOR_MAP.get(user_id, "더자이디엘") # 장부에서 상호를 가져옵니다.

# --- 3. 유틸리티 함수 (기존 로직 100% 유지) ---
def clean_realtor_name(name):
    pattern = r'공인중개사사무소|공인중개사|중개사무소|부동산|중개사|공인|중개|사무소'
    cleaned = re.sub(pattern, '', str(name)).strip()
    return cleaned if cleaned else str(name)

@st.cache_data(show_spinner=False)
def process_data(df):
    if df.empty: return df
    df['수집일시'] = pd.to_datetime(df['수집일시'])
    df = df.sort_values('수집일시')
    
    # 세션 처리 로직
    time_diff_mins = df['수집일시'].diff().dt.total_seconds() / 60.0
    df['새_세션'] = (time_diff_mins > 5) | time_diff_mins.isna()
    df['세션ID'] = df['새_세션'].cumsum()
    session_rep = df.groupby('세션ID')['수집일시'].min().dt.floor('min').reset_index(name='대표수집일시')
    df = pd.merge(df, session_rep, on='세션ID', how='left')
    df['수집일시'] = df['대표수집일시']
    
    # 순위 숫자 변환
    df['전체순위_숫자'] = pd.to_numeric(df['전체순위'].astype(str).str.replace(r'[^0-9]', '', regex=True), errors='coerce').fillna(999).astype(int)
    df['묶음내순위_숫자'] = pd.to_numeric(df['묶음내순위'].astype(str).str.replace('단독', '1').str.replace(r'[^0-9]', '', regex=True), errors='coerce').fillna(999).astype(int)
    
    for col in ['동/호수', '층/타입', '거래방식', '가격']:
        if col in df.columns: df[col] = df[col].fillna("")
            
    df['확인일자'] = df['확인일자'].apply(lambda x: str(x).strip() if pd.notna(x) else pd.NA)
    df['확인일자_Date'] = pd.to_datetime(df['확인일자'], format='%y.%m.%d', errors='coerce')
    df['매물묶음키'] = df.apply(lambda r: f"{r['단지명']} | {r['동/호수']} | {r['층/타입']} | {r['거래방식']} | {r['가격']}", axis=1)
    
    return df

# --- 4. 다중 파일 자동 병합 로직 (월별 대응) ---
@st.cache_data(ttl=600)
def load_server_data():
    xlsx_files = glob.glob("data_*.xlsx")
    if os.path.exists("data.xlsx"): xlsx_files.append("data.xlsx")
    
    if not xlsx_files: return None
        
    df_list = []
    for file in xlsx_files:
        try:
            temp = pd.read_excel(file)
            df_list.append(temp)
        except Exception as e:
            st.error(f"파일 읽기 오류 ({file}): {e}")
            
    if not df_list: return None
    
    merged_df = pd.concat(df_list, ignore_index=True)
    merged_df = merged_df.drop_duplicates() 
    return merged_df

# --- 데이터 로드 ---
raw_df = load_server_data()
if raw_df is None:
    st.error("🚨 서버에 데이터 파일이 없습니다. 크롤러를 먼저 실행해 주세요.")
    st.stop()

# --- 5. 분석 로직 시작 ---
try:
    df = process_data(raw_df)
    
    st.sidebar.title("📅 리포트 설정")
    min_time = df['수집일시'].min()
    max_time = df['수집일시'].max()
    start_date = st.sidebar.date_input("시작일", min_time.date())
    end_date = st.sidebar.date_input("종료일", max_time.date())
    
    mask = (df['수집일시'].dt.date >= start_date) & (df['수집일시'].dt.date <= end_date)
    t_df = df[mask].copy()
    
    if t_df.empty:
        st.error("설정한 기간에 데이터가 없습니다.")
        st.stop()

    global_times = t_df['수집일시'].drop_duplicates().sort_values().reset_index(drop=True)
    dataset_end_time = global_times.max()
    
    bundle_keys = ['단지명', '동/호수', '층/타입', '거래방식', '가격']
    complex_list = sorted(t_df['단지명'].dropna().unique().tolist())
    complex_list_with_all = ["전체 단지"] + complex_list
    
    latest_t = t_df.groupby(bundle_keys)['수집일시'].max().reset_index()
    first_place_df = pd.merge(t_df, latest_t, on=bundle_keys+['수집일시'])
    first_place_df = first_place_df[first_place_df['묶음내순위_숫자']==1][bundle_keys+['부동산명']].rename(columns={'부동산명':'현재1위부동산'}).drop_duplicates(subset=bundle_keys)

    # M/S 계산
    uniq = t_df.drop_duplicates(subset=['매물번호', '부동산명', '단지명']).copy()
    uniq['묶음_총개수'] = uniq.groupby(bundle_keys)['부동산명'].transform('count')
    uniq['파워점수'] = 10 + (10 / uniq['묶음내순위_숫자']) + (uniq['묶음_총개수'] * 0.1)
    ms_counts = uniq.groupby(['단지명', '부동산명']).agg(매물건수=('부동산명', 'count'), 총점수=('파워점수', 'sum')).reset_index()
    
    my_ranks_dict = {}
    for comp in complex_list:
        cdf = ms_counts[ms_counts['단지명'] == comp].copy()
        if cdf.empty: continue
        cdf['순위'] = cdf['총점수'].rank(ascending=False, method='min')
        my_r = cdf[cdf['부동산명'].str.contains(my_realtor)]
        my_ranks_dict[comp] = int(my_r['순위'].iloc[0]) if not my_r.empty else "권외"

    # --- 메인 화면 시작 ---
    st.title(f"📊 {my_realtor} 대표님 마켓 인텔리전스")
    
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.write("🏆 **내 점유율**")
        kpi_comp = st.selectbox("단지 선택", complex_list, label_visibility="collapsed")
        kpi_rank = my_ranks_dict.get(kpi_comp, "권외")
        st.subheader(f"{kpi_rank}위" if kpi_rank != "권외" else "권외")
    
    my_ls = t_df[t_df['부동산명'].str.contains(my_realtor, na=False)].sort_values('수집일시', ascending=False).drop_duplicates(subset=bundle_keys)
    danger_ls = my_ls[my_ls['묶음내순위_숫자'] > 1].copy()
    if not danger_ls.empty:
        danger_ls = pd.merge(danger_ls, first_place_df, on=bundle_keys, how='left')
        danger_ls['현재1위부동산'] = danger_ls['현재1위부동산'].fillna('알수없음')
    col2.metric("🚨 상위 노출 실패 매물", f"{len(danger_ls)}건")
    
    # 방치 매물 로직
    bh = t_df.groupby(bundle_keys + ['수집일시']).agg(최대_확인일자=('확인일자_Date', 'max')).reset_index().sort_values(bundle_keys + ['수집일시'])
    bh['이전_최대_확인일자'] = bh.groupby(bundle_keys)['최대_확인일자'].shift(1)
    bh['상태변경'] = bh['이전_최대_확인일자'].notna() & (bh['최대_확인일자'] != bh['이전_최대_확인일자'])
    bh['블록'] = bh.groupby(bundle_keys)['상태변경'].cumsum()
    lb = bh.groupby(bundle_keys).tail(1).rename(columns={'수집일시': '최종수집일시'})
    bs = bh.groupby(bundle_keys + ['블록'])['수집일시'].min().reset_index().rename(columns={'수집일시': '블록시작일시'})
    mb = pd.merge(lb, bs, on=bundle_keys + ['블록'])
    mb['방치시간(시간)'] = (mb['최종수집일시'] - mb['블록시작일시']).dt.total_seconds() / 3600
    tb = mb[mb['방치시간(시간)'] >= 6]
    empty_houses = pd.merge(tb, my_ls[bundle_keys + ['묶음내순위_숫자']], on=bundle_keys)
    empty_houses = empty_houses[empty_houses['묶음내순위_숫자'] > 1].copy()
    if not empty_houses.empty:
        empty_houses = pd.merge(empty_houses, first_place_df, on=bundle_keys, how='left')
        empty_houses['현재1위부동산'] = empty_houses['현재1위부동산'].fillna('알수없음')
    col3.metric("🎯 방치된 꿀매물", f"{len(empty_houses)}건")
    
    # 경쟁사 로직
    trk = t_df.sort_values(bundle_keys + ['부동산명', '수집일시']).copy()
    trk['이전_확인일자'] = trk.groupby(bundle_keys + ['부동산명'])['확인일자'].shift(1)
    boosted_df = trk[(trk['이전_확인일자'].notna()) & (trk['이전_확인일자'] != trk['확인일자'])]
    top_spender = "없음"
    if not boosted_df.empty:
        stat_df = boosted_df.groupby('부동산명').size().reset_index(name='count').sort_values('count', ascending=False)
        top_raw = stat_df.iloc[0]['부동산명']
        top_spender = f"{clean_realtor_name(top_raw)} ({stat_df.iloc[0]['count']}회)"
    col4.metric("🔥 최대 지출 경쟁사", top_spender)
    
    st.divider()

    # --- 8개 탭 복구 ---
    tabs = st.tabs(["📋 요약 리포트", "🏆 점유율(M/S)", "🚨 내 순위 현황", "🎯 방치된 매물", "🌀 롤링 추적", "⏳ 인덱싱 분석", "⏱️ 광고 갱신", "📊 경쟁사 요약"])
    
    with tabs[0]: # 요약 리포트
        st.subheader("📝 맞춤형 브리핑")
        rank_str = " / ".join([f"{k} {v}위" for k, v in my_ranks_dict.items() if v != "권외"])
        briefing = f"""[📅 시장 동향 브리핑]
(기간: {start_date} ~ {end_date})
대표님의 현재 랭킹: [{rank_str}]
- 방어전 필요 매물: {len(danger_ls)}건
- 공격 타겟 매물: {len(empty_houses)}건
- 주력 경쟁사: {top_spender}"""
        st.text_area("리포트 복사용", value=briefing, height=200)

    with tabs[1]: # M/S 점유율
        f_comp = st.selectbox("단지 필터", complex_list_with_all, key="ms_filter")
        ms_df = ms_counts.copy()
        if f_comp != "전체 단지": ms_df = ms_df[ms_df['단지명'] == f_comp]
        agg_ms = ms_df.groupby('부동산명')['총점수'].sum().reset_index().sort_values('총점수', ascending=False)
        st.dataframe(agg_ms, use_container_width=True)
        fig = px.bar(agg_ms.head(10), x='총점수', y='부동산명', orientation='h', title="TOP 10 점유율")
        st.plotly_chart(fig, use_container_width=True)

    with tabs[2]: # 내 순위 현황
        st.dataframe(danger_ls, use_container_width=True)

    with tabs[3]: # 방치된 매물
        st.dataframe(empty_houses, use_container_width=True)

    with tabs[4]: # 롤링 추적
        st.write("매물별 노출 순위 변화 히스토리 차트")
        tr_comp = st.selectbox("단지 선택", complex_list, key="tr_c")
        b_list = sorted(t_df[t_df['단지명']==tr_comp]['매물묶음키'].unique())
        tr_b = st.selectbox("매물 선택", b_list, key="tr_b")
        bdf = t_df[(t_df['단지명']==tr_comp) & (t_df['매물묶음키']==tr_b)]
        fig_line = px.line(bdf, x='수집일시', y='전체순위_숫자', color='부동산명', markers=True)
        fig_line.update_yaxes(autorange="reversed")
        st.plotly_chart(fig_line, use_container_width=True)

    with tabs[5]: # 인덱싱 분석
        st.write("광고 갱신 후 순위 상승 효과 분석 데이터")
        if not boosted_df.empty:
            st.dataframe(boosted_df, use_container_width=True)

    with tabs[6]: # 광고 갱신
        st.write("시장 전체 광고 갱신 로그")
        st.dataframe(boosted_df[['수집일시', '부동산명', '단지명', '가격', '확인일자']], use_container_width=True)

    with tabs[7]: # 경쟁사 요약
        if not boosted_df.empty:
            st.write("경쟁사별 활동 시간대 및 갱신 빈도")
            fig_stat = px.histogram(boosted_df, x=boosted_df['수집일시'].dt.hour, color='부동산명', title="시간대별 갱신 활동")
            st.plotly_chart(fig_stat, use_container_width=True)

except Exception as e:
    st.error(f"데이터 분석 중 오류 발생: {e}")
