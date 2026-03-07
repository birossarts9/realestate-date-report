import streamlit as st
import pandas as pd
import plotly.express as px
import re
import os
import glob
import json
from datetime import datetime, timedelta

# --- 1. 비밀 장부(JSON) 로드 로직 ---
def load_realtor_map():
    # GitHub 서버에 있는 realtors.json 파일을 읽습니다.
    if os.path.exists("realtors.json"):
        with open("realtors.json", "r", encoding="utf-8") as f:
            return json.load(f)
    return {"a123": "더자이디엘"} # 파일이 없을 때를 대비한 기본값

REALTOR_MAP = load_realtor_map()

# URL 파라미터 인식 (?id=a123 방식)
query_params = st.query_params
user_id = query_params.get("id", "a123") 
my_realtor = REALTOR_MAP.get(user_id, "더자이디엘") # 장부에서 상호를 가져옴

# --- 2. 웹사이트 기본 세팅 ---
st.set_page_config(page_title="이실장 시장 통계 리포트 PRO", page_icon="📈", layout="wide")

# --- 3. 유틸리티 함수 (기존 로직 유지) ---
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

# --- 4. 다중 파일 자동 병합 로직 ---
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

# --- 5. 데이터 로드 및 분석 화면 ---
raw_df = load_server_data()
if raw_df is None:
    st.error("🚨 서버에 데이터 파일이 없습니다. 크롤러를 먼저 실행해 주세요.")
    st.stop()

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

    bundle_keys = ['단지명', '동/호수', '층/타입', '거래방식', '가격']
    complex_list = sorted(t_df['단지명'].dropna().unique().tolist())
    dataset_end_time = t_df['수집일시'].max()
    
    # M/S 계산
    uniq = t_df.drop_duplicates(subset=['단지명', '부동산명', '매물묶음키', '수집일시']).copy()
    uniq['묶음_총개수'] = uniq.groupby(bundle_keys)['부동산명'].transform('count')
    uniq['파워점수'] = 10 + (10 / uniq['묶음내순위_숫자']) + (uniq['묶음_총개수'] * 0.1)
    ms_counts = uniq.groupby(['단지명', '부동산명']).agg(매물건수=('부동산명', 'count'), 총점수=('파워점수', 'sum')).reset_index()

    st.title(f"📊 {my_realtor} 대표님 마켓 인텔리전스")
    st.caption(f"분석 대상 데이터: {len(t_df)}건 | 최종 업데이트: {dataset_end_time}")

    # (이하 KPI 및 8개 탭 시각화 로직은 기존 소장님 코드를 그대로 사용하시면 됩니다)
    st.info("데이터 분석이 완료되었습니다. 아래 탭을 클릭하여 상세 리포트를 확인하세요.")

    tabs = st.tabs(["📋 요약 리포트", "🏆 점유율(M/S)", "🚨 내 순위 현황", "🎯 방치된 매물", "🌀 롤링 추적", "⏳ 인덱싱 분석", "⏱️ 광고 갱신", "📊 경쟁사 요약"])
    
    with tabs[1]:
        st.subheader("부동산별 점유율 현황")
        fig = px.bar(ms_counts.sort_values('총점수', ascending=False).head(10), x='총점수', y='부동산명', orientation='h')
        st.plotly_chart(fig, use_container_width=True)

except Exception as e:
    st.error(f"데이터 처리 중 오류 발생: {e}")
