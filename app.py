import streamlit as st
import pandas as pd
import plotly.express as px
import re
import os
import glob
import json
from datetime import datetime, timedelta

# --- 1. 비밀 장부(JSON) 로드 및 보안 설정 ---
def load_realtor_map():
    if os.path.exists("realtors.json"):
        with open("realtors.json", "r", encoding="utf-8") as f:
            try: return json.load(f)
            except: return {"a123": "더자이디엘"}
    return {"a123": "더자이디엘"}

REALTOR_MAP = load_realtor_map()
query_params = st.query_params
user_id = query_params.get("id", "a123") 

# [핵심] 데모 모드 판별 및 데이터 소싱 로직
IS_DEMO_MODE = (user_id == "demo")
# 데모 모드일 경우 '더자이디엘(a123)'의 데이터를 기반으로 블러 처리하여 보여줌
target_id = "a123" if IS_DEMO_MODE else user_id
my_realtor = REALTOR_MAP.get(target_id, "더자이디엘") 

# --- 2. 웹사이트 기본 세팅 ---
st.set_page_config(page_title="부동산 마켓 인텔리전스 리포트", page_icon="📈", layout="wide")

# --- 3. 유틸리티 함수 ---
def clean_realtor_name(name):
    pattern = r'공인중개사사무소|공인중개사|중개사무소|부동산|중개사|공인|중개|사무소'
    cleaned = re.sub(pattern, '', str(name)).strip()
    return cleaned if cleaned else str(name)

@st.cache_data(show_spinner=False)
def process_data(df):
    df['수집일시'] = pd.to_datetime(df['수집일시'])
    df = df.sort_values('수집일시')
    time_diff_mins = df['수집일시'].diff().dt.total_seconds() / 60.0
    df['새_세션'] = (time_diff_mins > 5) | time_diff_mins.isna()
    df['세션ID'] = df['새_세션'].cumsum()
    session_rep = df.groupby('세션ID')['수집일시'].min().dt.floor('min').reset_index(name='대표수집일시')
    df = pd.merge(df, session_rep, on='세션ID', how='left')
    df['수집일시'] = df['대표수집일시']
    
    df['전체순위_숫자'] = pd.to_numeric(df['전체순위'].astype(str).str.replace(r'[^0-9]', '', regex=True), errors='coerce').fillna(999).astype(int)
    df['묶음내순위_숫자'] = pd.to_numeric(df['묶음내순위'].astype(str).str.replace('단독', '1').str.replace(r'[^0-9]', '', regex=True), errors='coerce').fillna(999).astype(int)
    
    for col in ['동/호수', '층/타입', '거래방식', '가격']:
        if col in df.columns: df[col] = df[col].fillna("")
            
    df['확인일자'] = df['확인일자'].apply(lambda x: str(x).strip() if pd.notna(x) else pd.NA)
    df['확인일자_Date'] = pd.to_datetime(df['확인일자'], format='%y.%m.%d', errors='coerce')
    df['매물묶음키'] = df.apply(lambda r: f"{r['동/호수']} | {r['층/타입']} | {r['거래방식']} | {r['가격']}", axis=1)
    
    return df

@st.cache_data(ttl=600)
def load_server_data():
    current_dir = os.path.dirname(os.path.abspath(__file__))
    xlsx_files = glob.glob(os.path.join(current_dir, "data_*.xlsx"))
    if os.path.exists("data.xlsx"): xlsx_files.append("data.xlsx")
    if not xlsx_files: return None
        
    df_list = []
    for file in xlsx_files:
        try: df_list.append(pd.read_excel(file))
        except: pass
            
    if not df_list: return None
    merged_df = pd.concat(df_list, ignore_index=True)
    return merged_df.drop_duplicates()

raw_df = load_server_data()
if raw_df is None:
    st.error("🚨 서버에 데이터 파일이 없습니다. 크롤러를 실행해 주세요.")
    st.stop()

# --- 4. 메인 분석 엔진 ---
try:
    df = process_data(raw_df)
    
    # 사이드바 설정
    st.sidebar.title("📅 리포트 설정")
    min_time, max_time = df['수집일시'].min(), df['수집일시'].max()
    start_date = st.sidebar.date_input("시작일", min_time.date())
    end_date = st.sidebar.date_input("종료일", max_time.date())
    
    mask = (df['수집일시'].dt.date >= start_date) & (df['수집일시'].dt.date <= end_date)
    t_df = df[mask].copy()
    
    if t_df.empty:
        st.error("설정한 기간에 데이터가 없습니다.")
        st.stop()

    # --- 🛡️ [데모 모드] 정보 가리기 로직 ---
    display_realtor = "성우부동산(체험용)" if IS_DEMO_MODE else my_realtor
    
    if IS_DEMO_MODE:
        st.sidebar.success("🔐 체험판 모드: 핵심 정보가 마스킹 처리되었습니다.")
        # 1. 동/호수 숫자를 별표로 가림
        t_df['동/호수'] = t_df['동/호수'].apply(lambda x: re.sub(r'\d', '*', str(x)))
        # 2. 타 부동산 상호를 경쟁사 A, B... 로 변경
        competitors = [c for c in t_df['부동산명'].unique() if c != my_realtor]
        comp_map = {name: f"경쟁사 {chr(65+i % 26)}" for i, name in enumerate(competitors)}
        t_df['부동산명'] = t_df['부동산명'].apply(lambda x: my_realtor if x == my_realtor else comp_map.get(x, x))
        # 3. 매물묶음키 재갱신
        t_df['매물묶음키'] = t_df.apply(lambda r: f"{r['동/호수']} | {r['층/타입']} | {r['거래방식']} | {r['가격']}", axis=1)

    # --- 데이터 계산 섹션 ---
    global_times = t_df['수집일시'].drop_duplicates().sort_values().reset_index(drop=True)
    dataset_end_time = global_times.max()
    
    group_keys = ['단지명', '동/호수', '층/타입', '거래방식', '가격', '부동산명']
    bundle_keys = ['단지명', '동/호수', '층/타입', '거래방식', '가격']
    complex_list = sorted(t_df['단지명'].dropna().unique().tolist())
    complex_list_with_all = ["전체 단지"] + complex_list
    
    latest_t = t_df.groupby(bundle_keys)['수집일시'].max().reset_index()
    first_place_df = pd.merge(t_df, latest_t, on=bundle_keys+['수집일시'])
    first_place_df = first_place_df[first_place_df['묶음내순위_숫자']==1][bundle_keys+['부동산명']].rename(columns={'부동산명':'현재1위부동산'}).drop_duplicates(subset=bundle_keys)

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
    st.title(f"📊 {display_realtor} 대표님을 위한 시장 동향 리포트")
    
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
    else: danger_ls['현재1위부동산'] = pd.Series(dtype='str')
    col2.metric("🚨 상위 노출 실패 매물", f"{len(danger_ls)}건")
    
    bh = t_df.groupby(bundle_keys + ['수집일시']).agg(최대_확인일자=('확인일자_Date', 'max')).reset_index().sort_values(bundle_keys + ['수집일시'])
    bh['상태변경'] = bh.groupby(bundle_keys)['최대_확인일자'].shift(1).notna() & (bh['최대_확인일자'] != bh.groupby(bundle_keys)['최대_확인일자'].shift(1))
    bh['블록'] = bh.groupby(bundle_keys)['상태변경'].cumsum()
    lb = bh.groupby(bundle_keys).tail(1)
    bs = bh.groupby(bundle_keys + ['블록'])['수집일시'].min().reset_index(name='시작')
    mb = pd.merge(lb, bs, on=bundle_keys + ['블록'])
    mb['h'] = (mb['수집일시'] - mb['시작']).dt.total_seconds() / 3600
    empty_houses = pd.merge(mb[mb['h'] >= 6], my_ls[my_ls['묶음내순위_숫자'] > 1], on=bundle_keys)
    if not empty_houses.empty:
        empty_houses = pd.merge(empty_houses, first_place_df, on=bundle_keys, how='left')
        empty_houses['현재1위부동산'] = empty_houses['현재1위부동산'].fillna('알수없음')
    col3.metric("🎯 방치된 꿀매물", f"{len(empty_houses)}건")
    
    trk = t_df.sort_values(group_keys + ['수집일시']).copy()
    trk['이전_확인'] = trk.groupby(group_keys)['확인일자'].shift(1)
    boosted_df = trk[(trk['이전_확인'].notna()) & (trk['이전_확인'] != trk['확인일자'])]
    top_spender = "없음"
    if not boosted_df.empty:
        s_df = boosted_df.groupby('부동산명').size().reset_index(name='c').sort_values('c', ascending=False)
        top_spender = f"{clean_realtor_name(s_df.iloc[0]['부동산명'])} ({s_df.iloc[0]['c']}회)"
    col4.metric("🔥 최대 지출 경쟁사", top_spender)
    
    st.markdown("---")

    # --- 탭 구성 및 명칭 변경 ---
    tab_report, tab_ms, tab_danger, tab_empty, tab_rolling, tab_indexing, tab_timing, tab_stat = st.tabs([
        "📋 요약 리포트", "🏆 점유율(M/S)", "🚨 내 매물 순위 현황", "🎯 방치된 매물", 
        "📉 단지 별 노출 현황", "⏳ 인덱싱 효과 분석", "⏱️ 광고 갱신 팩트", "📊 경쟁사 요약"
    ])
    
    with tab_report:
        st.subheader("📝 서비스 신청 및 문의")
        m1, m2, m3 = st.columns(3)
        m1.metric("한 달 리포트 구독", "월 80,000원", "정가 10만원")
        m2.metric("광고 자동화 솔루션", "월 80,000원", "정가 10만원")
        m3.metric("프리미엄 통합형", "월 130,000원", "정가 16만원")
        
        st.markdown("""> **💡 광고 자동화 솔루션이란?**
> AI가 경쟁 부동산의 신규 매물 등록과 광고 갱신 시간을 24시간 감시합니다. 
> 대표님의 매물이 상위 노출(1위)에서 밀려나는 즉시 시스템이 감지하여 자동으로 재광고를 실행, 1등 자리를 탈환합니다. 
> **인건비 절감**은 물론, 고객 문의가 집중되는 **황금 시간대 노출을 100% 보장**합니다.""")
        
        st.info("💳 **결제 계좌:** 신한은행 110-388-348507 (예금주: 장성우)  \n📞 **문의:** 010-6502-2105 (장성우 소장)")
        st.markdown("---")
        briefing = f"[{start_date} ~ {end_date}]\n현재 {display_realtor} 랭킹: {rank_str if 'rank_str' in locals() else '분석중'}\n🚨 방어필요: {len(danger_ls)}건 | 🎯 공격타겟: {len(empty_houses)}건"
        st.text_area("📋 리포트 요약 내용", value=briefing, height=150)
        
    with tab_ms:
        f_comp = st.selectbox("단지 필터", complex_list_with_all, key="ms_f")
        ms_df = ms_counts.copy() if f_comp == "전체 단지" else ms_counts[ms_counts['단지명'] == f_comp]
        agg_ms = ms_df.groupby('부동산명').agg({'매물건수':'sum', '총점수':'sum'}).reset_index().sort_values('총점수', ascending=False)
        col_a, col_b = st.columns([1, 1])
        col_a.dataframe(agg_ms, use_container_width=True)
        fig = px.bar(agg_ms.head(10).sort_values('총점수', ascending=True), x='총점수', y='부동산명', orientation='h', title=f"{f_comp} TOP 10", text='총점수', color_discrete_sequence=['#3182f6'])
        col_b.plotly_chart(fig, use_container_width=True)

    with tab_danger: st.dataframe(danger_ls, use_container_width=True)
    with tab_empty: st.dataframe(empty_houses, use_container_width=True)

    with tab_rolling:
        st.subheader("📉 특정 매물의 순위 롤링 현황")
        st.write("> **💡 롤링(Rolling) 현상이란?** \n> 네이버 부동산은 모든 이용자에게 동일한 순위를 보여주지 않습니다. 광고 효율의 형평성을 위해 매번 접속할 때마다, 혹은 보는 사람마다 순위를 미세하게 조정하여 보여주는 특성이 있습니다. 본 차트는 수집 시점마다 변동되는 실제 노출 위치를 추적합니다.")
        c1, c2 = st.columns(2)
        tr_comp = c1.selectbox("단지 선택", complex_list, key="tr_c")
        b_list = sorted(t_df[t_df['단지명'] == tr_comp]['매물묶음키'].unique())
        tr_bundle = c2.selectbox("매물 묶음 선택", b_list, key="tr_b")
        if tr_comp and tr_bundle:
            bdf = t_df[(t_df['단지명'] == tr_comp) & (t_df['매물묶음키'] == tr_bundle)]
            b_hist = bdf.groupby('수집일시').first().reset_index()
            # 순위 레이블 처리
            b_hist['노출수준'] = b_hist['전체순위_숫자'].apply(lambda x: "✅ 상위 노출" if x <= 20 else "❌ 하위권")
            fig2 = px.line(b_hist, x='수집일시', y='전체순위_숫자', markers=True, title=f"'{tr_bundle}' 매물 순위 변동 추이", color_discrete_sequence=['#3182f6'])
            fig2.update_yaxes(autorange="reversed", title="네이버 전체 노출 순위", tickvals=[1, 5, 10, 15, 20, 25])
            st.plotly_chart(fig2, use_container_width=True)
            st.dataframe(b_hist[['수집일시', '전체순위_숫자', '노출수준', '부동산명']], use_container_width=True)

    with tab_indexing: st.info("광고 갱신 후 실제 반영까지 걸리는 시간적 효율을 분석하는 탭입니다.")
    with tab_timing: st.dataframe(boosted_df, use_container_width=True)
    with tab_stat:
        if not boosted_df.empty:
            fig3 = px.histogram(boosted_df, x=boosted_df['수집일시'].dt.hour, color='부동산명', title="경쟁사별 광고 갱신 주력 시간대")
            st.plotly_chart(fig3, use_container_width=True)

except Exception as e:
    st.error(f"데이터 분석 엔진 가동 중 오류 발생: {e}")
