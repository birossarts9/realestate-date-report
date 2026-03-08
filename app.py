import streamlit as st
import pandas as pd
import plotly.express as px
import re
import os
import glob
import json
from datetime import datetime, timedelta

# --- [추가] 비밀 장부(JSON) 로드 로직 ---
def load_realtor_map():
    if os.path.exists("realtors.json"):
        with open("realtors.json", "r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except:
                return {"a123": "더자이디엘"}
    return {"a123": "더자이디엘"}

REALTOR_MAP = load_realtor_map()

# URL 파라미터 인식 (id=a123 방식)
query_params = st.query_params
user_id = query_params.get("id", "a123") 

# --- [핀셋 수정] 체험판 모드 판별 및 데이터 소싱 로직 ---
# 핵심: 데모 모드일 경우 내부적으로는 'a123(더자이디엘)'의 데이터를 가져오도록 설정
IS_DEMO_MODE = (user_id == "demo")
target_id = "a123" if IS_DEMO_MODE else user_id 
my_realtor = REALTOR_MAP.get(target_id, "더자이디엘") 
# ------------------------------------------------------

# --- 1. 웹사이트 기본 세팅 (전체화면 모드) ---
st.set_page_config(page_title="이실장 시장 통계 리포트", page_icon="📈", layout="wide")

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

# --- 4. 데이터 자동 로드 (다중 파일 자동 병합 & 중복 제거) ---
@st.cache_data(ttl=600) # 10분마다 새로고침
def load_server_data():
    current_dir = os.path.dirname(os.path.abspath(__file__))
    
    xlsx_files = glob.glob(os.path.join(current_dir, "data_*.xlsx"))
    if os.path.exists("data.xlsx"):
        xlsx_files.append("data.xlsx")
    
    if not xlsx_files:
        return None
        
    df_list = []
    for file in xlsx_files:
        try:
            temp = pd.read_excel(file)
            df_list.append(temp)
        except Exception as e:
            st.error(f"파일 읽기 오류 ({file}): {e}")
            
    if not df_list:
        return None
        
    merged_df = pd.concat(df_list, ignore_index=True)
    merged_df = merged_df.drop_duplicates()
    
    return merged_df

raw_df = load_server_data()

if raw_df is None:
    st.error("🚨 서버에 엑셀(.xlsx) 파일이 없습니다.")
    st.stop()

# --- 5. 사이드바 (고객용 기간 설정 패널) ---
st.sidebar.title("📅 리포트 설정")

try:
    df = process_data(raw_df)
    
    min_time = df['수집일시'].min()
    max_time = df['수집일시'].max()
    
    st.sidebar.write("**분석 기간 설정**")
    start_date = st.sidebar.date_input("시작일", min_time.date())
    end_date = st.sidebar.date_input("종료일", max_time.date())
    
    mask = (df['수집일시'].dt.date >= start_date) & (df['수집일시'].dt.date <= end_date)
    t_df = df[mask].copy()
    
    if t_df.empty:
        st.error("설정한 기간에 데이터가 없습니다.")
        st.stop()

    # --- 🛡️ [핀셋 추가] 데모 모드 전용 마스킹 처리 엔진 🛡️ ---
    # 핵심: 데이터를 줄이지 않고 원본 데이터를 유지한 상태에서 화면 표시값만 변경
    display_realtor_name = "성우부동산(체험용)" if IS_DEMO_MODE else my_realtor
    if IS_DEMO_MODE:
        st.sidebar.success("🔐 현재 체험용(Demo) 모드로 접속 중입니다. 핵심 데이터는 블러 처리됩니다.")
        
        # 1. 동/호수 숫자를 별표(*)로 변경 (원본 process_data의 매물묶음키 수식을 고려하여 선변경)
        def mask_dong_ho(text): return re.sub(r'\d', '*', str(text))
        t_df['동/호수'] = t_df['동/호수'].apply(mask_dong_ho)
        
        # 2. 경쟁사 이름 마스킹 (경쟁사 A, B, C...)
        # 타 중개사 상호를 가명으로 변경하되, 내 상호(my_realtor)는 유지
        competitors = [c for c in t_df['부동산명'].unique() if c != my_realtor]
        comp_map = {name: f"경쟁사 {chr(65+i % 26)}" for i, name in enumerate(competitors)}
        t_df['부동산명'] = t_df['부동산명'].apply(lambda x: my_realtor if x == my_realtor else comp_map.get(x, x))
        
        # [중요] 마스킹된 데이터 기준으로 '매물묶음키' 재갱신 (그래야 이후 groupby 그룹이 맞음)
        # 원본 코드의 df.apply(...) 수식을 그대로 가져옴
        t_df['매물묶음키'] = t_df.apply(lambda r: f"{r['동/호수']} | {r['층/타입']} | {r['거래방식']} | {r['가격']}", axis=1)
    # --------------------------------------------------------------------
        
    global_times = t_df['수집일시'].drop_duplicates().sort_values().reset_index(drop=True)
    dataset_end_time = global_times.max()
    
    group_keys = ['단지명', '동/호수', '층/타입', '거래방식', '가격', '부동산명']
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
        if not my_r.empty:
            my_ranks_dict[comp] = int(my_r['순위'].iloc[0])
        else:
            my_ranks_dict[comp] = "권외"

    # --- 메인 화면 시작 ---
    # 제목 상호명 변경 반영
    st.title(f"📊 {display_realtor_name} 대표님을 위한 시장 동향")
    if IS_DEMO_MODE:
        st.info("💡 체험판 모드입니다. 경쟁사 실명과 상세 동/호수는 보호 처리되었습니다.")
    
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
    else:
        danger_ls['현재1위부동산'] = pd.Series(dtype='str')
    col2.metric("🚨 상위 노출 실패 매물", f"{len(danger_ls)}건")
    
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
    else:
        empty_houses['현재1위부동산'] = pd.Series(dtype='str')
    col3.metric("🎯 방치된 꿀매물 (최적타겟)", f"{len(empty_houses)}건")
    
    trk = t_df.sort_values(group_keys + ['수집일시', '전체순위_숫자']).copy()
    trk['쌍둥이_식별자'] = trk.groupby(group_keys + ['수집일시']).cumcount()
    fgk = group_keys + ['쌍둥이_식별자']
    trk = trk.sort_values(fgk + ['수집일시'])
    trk['이전_확인일자'] = trk.groupby(fgk)['확인일자'].shift(1)
    trk['수집일시_Date'] = trk['수집일시'].dt.normalize()
    c1 = trk['이전_확인일자'].notna() & (trk['이전_확인일자'] != trk['확인일자']) & trk['확인일자'].notna()
    c2 = trk['이전_확인일자'].isna() & ((trk['수집일시_Date'] - trk['확인일자_Date']).dt.days.between(0,1))
    boosted_df = trk[c1 | c2]
    
    top_spender = "없음"
    top_spender_raw_name = ""
    peak_hour_str = ""
    if not boosted_df.empty:
        stat_df = boosted_df.groupby('부동산명').agg(총횟수=('부동산명', 'count')).reset_index().sort_values('총횟수', ascending=False)
        top_spender_raw_name = stat_df.iloc[0]['부동산명']
        top_spender = f"{clean_realtor_name(top_spender_raw_name)} ({stat_df.iloc[0]['총횟수']}회)"
        
        top_realtor_data = boosted_df[boosted_df['부동산명'] == top_spender_raw_name]
        if not top_realtor_data.empty:
            peak_h = top_realtor_data['수집일시'].dt.hour.mode()[0]
            peak_hour_str = f", 주로 {peak_h}시에 집중적으로 갱신하고 있습니다."
    col4.metric("🔥 최대 지출 경쟁사", top_spender)
    
    st.markdown("---")

    # --- 탭 구성 및 명칭 변경 반영 ---
    tab_report, tab_ms, tab_danger, tab_empty, tab_rolling, tab_indexing, tab_timing, tab_stat = st.tabs([
        "📋 요약 리포트", "🏆 점유율(M/S)", "🚨 내 매물 순위 현황", "🎯 방치된 매물", 
        "📉 단지 별 노출 현황", "⏳ 인덱싱 효과 분석", "⏱️ 광고 갱신 팩트", "📊 경쟁사 요약"
    ])
    
    # 탭 1: 요약 리포트 & 메뉴판
    with tab_report:
        # [기능 추가] 서비스 메뉴판 및 계좌번호
        st.subheader("💳 서비스 이용 안내")
        m1, m2, m3 = st.columns(3)
        with m1:
            st.info("**📈 시장 분석 리포트**")
            st.write("~~월 100,000원~~")
            st.subheader("월 80,000원")
            st.caption("프로모션 할인가")
        with m2:
            st.info("**🤖 광고 자동화 솔루션**")
            st.write("~~월 100,000원~~")
            st.subheader("월 80,000원")
            st.caption("프로모션 할인가")
        with m3:
            st.success("**🚀 프리미엄 통합팩**")
            st.write("~~월 160,000원~~")
            st.subheader("월 130,000원")
            st.caption("최고의 효율 보장")
            
        st.markdown("""> **💡 광고 자동화란?**
> AI가 경쟁 부동산의 광고 패턴과 대표님 매물의 순위를 24시간 실시간으로 감시합니다. 
> 내 매물이 상위 노출(1위)에서 밀려나는 즉시 시스템이 자동으로 재광고를 실행, 최저 비용으로 즉각 1등 자리를 탈환합니다. 
> 인건비 절감은 물론, 고객 문의가 집중되는 시간대 노출을 완벽하게 보장합니다.""")
        
        st.info("🏦 **결제 계좌:** 신한은행 110-388-348507 (예금주: 장성우)")
        st.divider()

        # 기존 원본 브리핑 로직 그대로 유지
        st.subheader("브리핑 내용")
        
        rank_str = " / ".join([f"{k} {v}위" for k, v in my_ranks_dict.items() if v != "권외"])
        
        danger_detail = ""
        if not danger_ls.empty:
            top_danger_comps = danger_ls['단지명'].value_counts().head(2)
            danger_detail = f"\n*(특히 {', '.join([f'{k}({v}건)' for k, v in top_danger_comps.items()])}에서 1위 이탈이 가장 많이 발생했습니다. 빠른 갱신 방어가 필요합니다.)*"

        empty_detail = ""
        if not empty_houses.empty:
            top_empty_comps = empty_houses['단지명'].value_counts().head(2)
            empty_detail = f"\n*(추천 타겟: {', '.join([f'{k}({v}건)' for k, v in top_empty_comps.items()])} 위주로 우선 갱신을 추천드립니다.)*"

        briefing = f"""[📅 이실장 시장 동향 브리핑]
(기간: {start_date.strftime('%m/%d')} ~ {end_date.strftime('%m/%d')})

📊 시장 점유율 현황 (파워점수 기준):
대표님의 현재 단지별 랭킹은 [{rank_str if rank_str else "순위 없음"}] 입니다.

🚨 방어전 필요 (1위 이탈 매물):
현재 1위 자리에서 밀려나 노출이 저조한 매물이 총 {len(danger_ls)}건 있습니다.{danger_detail}

🎯 공격 타겟 (6h 이상 방치된 빈집):
경쟁사들이 돈을 쓰지 않아 최소 비용으로 1등 노출이 가능한 빈집 묶음이 {len(empty_houses)}건 발견되었습니다.{empty_detail}

🔥 경쟁사 위협 동향:
최근 가장 공격적으로 광고비를 지출하는 곳은 '{top_spender}' 입니다.
해당 부동산은{peak_hour_str if peak_hour_str else " 지속적으로 매물을 갱신하고 있습니다."} 이 시간대를 고려한 갱신 전략을 권장합니다.
"""
        st.text_area("마우스로 긁거나 터치하여 복사하세요.", value=briefing, height=450)
        
    with tab_ms:
        filter_comp = st.selectbox("단지 필터", complex_list_with_all, key="ms_comp")
        ms_df = ms_counts.copy()
        if filter_comp != "전체 단지": ms_df = ms_df[ms_df['단지명'] == filter_comp]
        
        agg_ms = ms_df.groupby('부동산명').agg({'매물건수':'sum', '총점수':'sum'}).reset_index()
        agg_ms['총점수'] = agg_ms['총점수'].round(1)
        agg_ms = agg_ms.sort_values('총점수', ascending=False)
        
        col_a, col_b = st.columns([1, 1])
        with col_a:
            st.dataframe(agg_ms, use_container_width=True)
        with col_b:
            agg_ms['부동산명_축약'] = agg_ms['부동산명'].apply(clean_realtor_name)
            top10 = agg_ms.head(10).sort_values('총점수', ascending=True)
            fig = px.bar(top10, x='총점수', y='부동산명_축약', orientation='h', title=f"{filter_comp} 점유율 Top 10", text='총점수', color_discrete_sequence=['#3182f6'])
            fig.update_layout(xaxis_title="파워 점수", yaxis_title="")
            st.plotly_chart(fig, use_container_width=True)

    with tab_danger:
        st.subheader("🚨 방어전 타겟 (1위 밀려난 매물)")
        if not danger_ls.empty:
            danger_show = danger_ls[['수집일시', '단지명', '동/호수', '층/타입', '거래방식', '묶음내순위_숫자', '현재1위부동산']].copy()
            danger_show.columns = ['확인 시간', '단지명', '동/호수', '층/타입', '거래방식', '내 순위', '현재 1위']
            st.dataframe(danger_show, use_container_width=True)
        else:
            st.info("현재 1위에서 밀려난 매물이 없습니다! 완벽한 방어 상태입니다.")

    with tab_empty:
        st.subheader("🎯 공격 타겟 (6시간 이상 방치 빈집)")
        if not empty_houses.empty:
            empty_show = empty_houses[['단지명', '동/호수', '층/타입', '거래방식', '묶음내순위_숫자', '현재1위부동산', '방치시간(시간)']].copy()
            empty_show.columns = ['단지명', '동/호수', '층/타입', '거래방식', '내 순위', '현재 1위', '방치된 시간(h)']
            empty_show['방치된 시간(h)'] = empty_show['방치된 시간(h)'].apply(lambda x: f"{int(x)}시간")
            st.dataframe(empty_show, use_container_width=True)
        else:
            st.info("현재 6시간 이상 방치된 빈집 매물이 없습니다.")

    # 탭 5: 단지 별 노출 현황 (구 매물 롤링 추적, 명칭 및 로직 개선)
    with tab_rolling:
        # [수정] 소제목 및 설명 친절하게 변경
        st.subheader("📉 특정 매물의 순위 롤링 현황")
        st.write("> **💡 롤링(Rolling) 현상이란?** \n> 네이버 부동산은 모든 이용자에게 동일한 순위를 보여주지 않습니다. 광고 효율의 형평성을 위해 접속 시점, 이용자 세션마다 순위를 미세하게 조정하여 보여주는 특성이 있습니다. 본 리포트는 이러한 롤링을 실시간 추적하여 평균적인 노출 위치를 분석합니다.")
        
        c1, c2 = st.columns(2)
        tr_comp = c1.selectbox("단지명 선택", t_df['단지명'].dropna().unique(), key="tr_comp")
        bundle_list = t_df[t_df['단지명'] == tr_comp]['매물묶음키'].dropna().unique().tolist()
        tr_bundle = c2.selectbox("매물 묶음 선택", sorted(bundle_list), key="tr_bundle")
        
        if tr_comp and tr_bundle:
            bdf = t_df[(t_df['단지명'] == tr_comp) & (t_df['매물묶음키'] == tr_bundle)]
            
            def get_bundle_state(grp):
                first_place = grp[grp['묶음내순위_숫자'] == 1]
                realtor = first_place['부동산명'].iloc[0] if not first_place.empty else grp.sort_values('묶음내순위_숫자')['부동산명'].iloc[0]
                return pd.Series({'전체순위': grp['전체순위_숫자'].min(), '1위부동산': realtor})
            
            b_hist = bdf.groupby('수집일시').apply(get_bundle_state).reset_index()
            t_hist = pd.DataFrame({'수집일시': global_times})
            t_hist = pd.merge(t_hist, b_hist, on='수집일시', how='left')
            t_hist['전체순위차트용'] = t_hist['전체순위'].fillna(21)
            
            # [수정] 그래프 타이틀 및 y축 라벨 개선
            fig2 = px.line(t_hist, x='수집일시', y='전체순위차트용', markers=True, title="🌀 특정 매물의 순위 롤링 히스토리", color_discrete_sequence=['#3182f6'])
            fig2.update_yaxes(autorange="reversed", range=[21.5, 0.5], title="노출 순위 (1~20위: 상위 노출 영역)")
            st.plotly_chart(fig2, use_container_width=True)
            
            # [수정] 데이터 표에 상위/하위 텍스트 레이블 추가
            t_hist['전체순위표시'] = t_hist['전체순위'].apply(lambda x: f"{int(x)}위" if pd.notna(x) else "이탈")
            t_hist['노출상태'] = t_hist['전체순위'].apply(lambda x: "✅ 상위 노출" if pd.notna(x) and x <= 20 else ("하위권" if pd.notna(x) else "이탈"))
            t_hist['1위부동산'] = t_hist['1위부동산'].fillna("-")
            st.dataframe(t_hist[['수집일시', '전체순위표시', '노출상태', '1위부동산']], use_container_width=True)

    with tab_indexing:
        st.subheader("⏳ 광고 갱신 후 골든타임(12h) 인덱싱 성적표")
        idx_events = []
        for (comp, bundle), grp in t_df.groupby(['단지명', '매물묶음키']):
            for realtor, r_grp in grp.groupby('부동산명'):
                r_grp = r_grp.sort_values('수집일시')
                r_grp['이전_확인일자'] = r_grp['확인일자'].shift(1)
                updates = r_grp[(r_grp['이전_확인일자'].notna()) & (r_grp['이전_확인일자'] != '-') & (r_grp['확인일자'] != r_grp['이전_확인일자'])]
                update_times = updates['수집일시'].tolist()
                
                for i, u_row in updates.iterrows():
                    u_time = u_row['수집일시']
                    past_r = r_grp[r_grp['수집일시'] < u_time]
                    pre_rank = past_r.iloc[-1]['묶음내순위_숫자'] if not past_r.empty else 21
                    
                    idx_pos = update_times.index(u_time)
                    next_u_time = update_times[idx_pos + 1] if idx_pos + 1 < len(update_times) else dataset_end_time
                    max_eval_time = min(u_time + pd.Timedelta(hours=12), next_u_time, dataset_end_time)
                    
                    eval_df = r_grp[(r_grp['수집일시'] >= u_time) & (r_grp['수집일시'] <= max_eval_time)]
                    best_eval_rank = eval_df['묶음내순위_숫자'].min() if not eval_df.empty else 21
                    
                    time_left = dataset_end_time - u_time
                    if time_left.total_seconds() < 4 * 3600 and best_eval_rank > 3:
                        status = "⏳ 판독 대기 (데이터 부족)"
                    else:
                        if pre_rank <= 3:
                            status = "🛡️ 상위권 방어" if best_eval_rank <= 3 else "⚠️ 방어 실패"
                        else:
                            if best_eval_rank <= 3: status = "🚀 상위권 진입 성공"
                            elif best_eval_rank <= 7: status = "📈 중위권 상승"
                            else: status = "🤔 누락" if eval_df.empty or best_eval_rank > 20 else "❌ 효과 미미 (돈낭비)"
                                
                    pre_str = f"{int(pre_rank)}위" if pre_rank <= 20 else "밖"
                    post_str = f"{int(best_eval_rank)}위" if best_eval_rank <= 20 else "밖"
                    rank_change = f"{pre_str} ➡️ {post_str}" if "대기" not in status else f"{pre_str} ➡️ 대기중"
                    
                    idx_events.append({'단지명': comp, '매물': bundle, '부동산명': realtor, '갱신포착': u_time, '순위변화': rank_change, '상태': status})
        
        if idx_events:
            idf = pd.DataFrame(idx_events).sort_values('갱신포착', ascending=False)
            st.dataframe(idf, use_container_width=True)
        else:
            st.info("조건에 맞는 갱신 내역이 없습니다.")

    with tab_timing:
        st.subheader("⏱️ 광고 갱신 팩트 (로그)")
        if not boosted_df.empty:
            show_boost = boosted_df[['수집일시', '부동산명', '단지명', '매물묶음키', '이전_확인일자', '확인일자']].copy()
            show_boost.columns = ['포착 시간', '부동산명', '단지명', '매물 묶음', '이전 일자', '갱신 일자']
            st.dataframe(show_boost, use_container_width=True)
        else:
            st.info("갱신 내역이 없습니다.")
            
    with tab_stat:
        st.subheader("경쟁사 갱신 트렌드 요약")
        if not boosted_df.empty:
            boosted_df['활동시간대'] = boosted_df['수집일시'].dt.hour
            stat_df = boosted_df.groupby('부동산명').agg(총횟수=('부동산명', 'count'), 주시간대=('활동시간대', lambda x: x.mode()[0] if not x.mode().empty else -1)).reset_index().sort_values('총횟수', ascending=False)
            c_a, c_b = st.columns(2)
            c_a.dataframe(stat_df, use_container_width=True)
            
            hc = boosted_df.groupby('활동시간대').size().reset_index(name='갱신건수')
            fig3 = px.line(hc, x='활동시간대', y='갱신건수', title="시장 전체 갱신 주력 시간대", markers=True)
            c_b.plotly_chart(fig3, use_container_width=True)

except Exception as e:
    st.error(f"데이터 처리 중 오류가 발생했습니다: {e}")

