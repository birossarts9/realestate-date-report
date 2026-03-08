import streamlit as st
import pandas as pd
import plotly.express as px
import re
import os
import glob
import json
from datetime import datetime, timedelta, timezone

# --- [수정] 비밀 장부(JSON) 로드 로직 ---
def load_realtor_map():
    if os.path.exists("realtors.json"):
        with open("realtors.json", "r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError as e:
                # 관리자 전용 에러 메시지 저장
                st.session_state['json_error'] = str(e)
                return {"a123": "더자이디엘"}
            except:
                return {"a123": "더자이디엘"}
    return {"a123": "더자이디엘"}

REALTOR_MAP = load_realtor_map()

# URL 파라미터 인식
query_params = st.query_params
user_id = query_params.get("id", "a123") 

# --- 🚀 데모 및 사용자 매핑 로직 ---
IS_DEMO_MODE = (user_id == "demo")
# 장부에서 상호명을 찾고, 없으면 기본값(a123) 상호 사용
my_realtor = REALTOR_MAP.get(user_id, REALTOR_MAP.get("a123", "더자이디엘"))
# 화면 표시용 이름
display_realtor = REALTOR_MAP.get("demo", "성우부동산(체험용)") if IS_DEMO_MODE else my_realtor

# --- 1. 웹사이트 기본 세팅 ---
st.set_page_config(page_title="이실장 시장 통계 리포트", page_icon="📈", layout="wide")

# --- 3. 유틸리티 함수 ---
def clean_realtor_name(name):
    pattern = r'공인중개사사무소|공인중개사|중개사무소|부동산|중개사|공인|중개|사무소'
    cleaned = re.sub(pattern, '', str(name)).strip()
    return cleaned if cleaned else str(name)

def mask_text(text, is_agent=False):
    if not IS_DEMO_MODE: return text
    if is_agent:
        if text == my_realtor: return display_realtor
        return f"경쟁사 {hash(str(text)) % 100}"
    return re.sub(r'\d', '*', str(text))

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
    
    # [왜곡 방지] 2.5시간 공백 발생 시 이후 1시간 데이터는 분석 제외 설정
    session_times = df['수집일시'].drop_duplicates().sort_values()
    gap_check = session_times.diff().dt.total_seconds() / 3600.0
    gap_starts = session_times[gap_check > 2.5].tolist()
    
    df['왜곡영역'] = False
    for start_time in gap_starts:
        df.loc[(df['수집일시'] >= start_time) & (df['수집일시'] < start_time + timedelta(hours=1)), '왜곡영역'] = True
    
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
        try:
            temp = pd.read_excel(file)
            df_list.append(temp)
        except Exception as e:
            st.error(f"파일 읽기 오류 ({file}): {e}")
    if not df_list: return None
    merged_df = pd.concat(df_list, ignore_index=True)
    merged_df = merged_df.drop_duplicates()
    return merged_df

raw_df = load_server_data()
if raw_df is None:
    st.error("🚨 서버에 데이터 파일이 없습니다.")
    st.stop()

# --- 5. 사이드바 (날짜/시간 정밀 설정) ---
st.sidebar.title("📅 리포트 설정")
try:
    df = process_data(raw_df)
    min_time, max_time = df['수집일시'].min(), df['수집일시'].max()

    st.sidebar.subheader("⏰ 분석 기간 (정밀 설정)")
    col_sd, col_st = st.sidebar.columns(2)
    start_date = col_sd.date_input("시작일", min_time.date())
    start_time = col_st.time_input("시작시간", min_time.time())

    col_ed, col_et = st.sidebar.columns(2)
    end_date = col_ed.date_input("종료일", max_time.date())
    end_time = col_et.time_input("종료시간", max_time.time())

    start_dt = datetime.combine(start_date, start_time)
    end_dt = datetime.combine(end_date, end_time)

    mask = (df['수집일시'] >= start_dt) & (df['수집일시'] <= end_dt)
    t_df = df[mask].copy()

    if t_df.empty:
        st.error("설정한 기간에 데이터가 없습니다.")
        st.stop()

    global_times = t_df['수집일시'].drop_duplicates().sort_values().reset_index(drop=True)
    bundle_keys = ['단지명', '동/호수', '층/타입', '거래방식', '가격']
    group_keys = bundle_keys + ['부동산명']
    complex_list = sorted(t_df['단지명'].dropna().unique().tolist())
    complex_list_with_all = ["전체 단지"] + complex_list

    latest_t = t_df.groupby(bundle_keys)['수집일시'].max().reset_index()
    first_place_df = pd.merge(t_df, latest_t, on=bundle_keys+['수집일시'])
    first_place_df = first_place_df[first_place_df['묶음내순위_숫자']==1][bundle_keys+['부동산명']].rename(columns={'부동산명':'현재1위부동산'}).drop_duplicates(subset=bundle_keys)

    # M/S 점수 정수화 로직 포함
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
        my_r = cdf[cdf['부동산명'].str.contains(my_realtor)]
        my_ranks_dict[comp] = int(my_r['순위'].iloc[0]) if not my_r.empty else "권외"

    # --- 🚨 [보안 수정] 관리자 전용 실시간 알림판 (소장님 전용) ---
    MASTER_ADMIN_ID = "a123" # 소장님 실제 ID로 변경 가능
    if user_id == MASTER_ADMIN_ID:
        # 한국 시간 보정 로직
        KST = timezone(timedelta(hours=9))
        now_kst = datetime.now(KST).replace(tzinfo=None)
        last_update_dt = df['수집일시'].max()
        alive_diff = now_kst - last_update_dt

        if alive_diff > timedelta(hours=2.5):
            st.error(f"🚨 **[관리자 알림] 크롤러 중단!** PC를 확인하세요. (한국기준 **{alive_diff.total_seconds()/3600:.1f}시간**째 멈춤. 최종수집: {last_update_dt.strftime('%m/%d %H:%M')})")
        
        if 'json_error' in st.session_state:
            st.warning(f"⚠️ **[관리자 알림] realtors.json 오류:** {st.session_state['json_error']}")

    # --- 메인 화면 시작 ---
    st.title(f"📊 {display_realtor} 대표님을 위한 시장 동향")
    if IS_DEMO_MODE:
        st.info("💡 체험판 모드입니다. 타 부동산 실명과 상세 주소는 보호 처리되었습니다.")

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
    else: empty_houses['현재1위부동산'] = pd.Series(dtype='str')
    col3.metric("🎯 방치된 꿀매물 (최적타겟)", f"{len(empty_houses)}건")

    trk = t_df.sort_values(group_keys + ['수집일시', '전체순위_숫자']).copy()
    trk['쌍둥이_식별자'] = trk.groupby(group_keys + ['수집일시']).cumcount()
    fgk = group_keys + ['쌍둥이_식별자']
    trk = trk.sort_values(fgk + ['수집일시'])
    trk['이전_확인일자'] = trk.groupby(fgk)['확인일자'].shift(1)
    trk['수집일시_Date'] = trk['수집일시'].dt.normalize()
    c1 = trk['이전_확인일자'].notna() & (trk['이전_확인일자'] != trk['확인일자']) & trk['확인일자'].notna()
    c2 = trk['이전_확인일자'].isna() & ((trk['수집일시_Date'] - trk['확인일자_Date']).dt.days.between(0,1))
    
    boosted_raw = trk[c1 | c2]
    boosted_df = boosted_raw[boosted_raw['왜곡영역'] == False].copy()
    
    top_spender, top_spender_raw_name, peak_hour_str = "없음", "", ""
    if not boosted_df.empty:
        stat_df = boosted_df.groupby('부동산명').agg(총횟수=('부동산명', 'count')).reset_index().sort_values('총횟수', ascending=False)
        top_spender_raw_name = stat_df.iloc[0]['부동산명']
        masked_ts_name = mask_text(clean_realtor_name(top_spender_raw_name), True)
        top_spender = f"{masked_ts_name} ({stat_df.iloc[0]['총횟수']}회)"
        top_realtor_data = boosted_df[boosted_df['부동산명'] == top_spender_raw_name]
        if not top_realtor_data.empty:
            avg_h = int(round(top_realtor_data['수집일시'].dt.hour.mean()))
            peak_hour_str = f", 평균적으로 {avg_h}시 부근에 갱신이 집중됩니다."
            
    col4.metric("🔥 최대 지출 경쟁사", top_spender)
    st.markdown("---")

    # --- [탭 구성] 생략 없는 전체 UI 로직 ---
    tab_report, tab_ms, tab_danger, tab_empty, tab_rolling, tab_timing, tab_stat = st.tabs([
        "📋 요약 리포트", "🏆 점유율(M/S)", "🚨 내 매물 순위 현황", "🎯 방치된 매물", 
        "📉 단지 별 노출 현황", "⏱️ 광고 갱신 팩트", "📊 경쟁사 요약"
    ])
    
    with tab_report:
        # [신규 UI] 시안 반영 브리핑 박스
        st.markdown(f"""
        <div style="background-color:#f0f7ff; padding:30px; border-radius:20px; border-left: 8px solid #3182f6; margin-bottom:40px;">
            <h2 style="color:#1e3a8a; margin-top:0; font-size:32px;">📊 오늘의 시장 브리핑</h2>
            <p style="font-size:22px; line-height:1.8; color:#334155; white-space: pre-wrap; font-weight:500;">
[📅 이실장 시장 동향 브리핑]
(기간: {start_dt.strftime('%m/%d %H:%M')} ~ {end_dt.strftime('%m/%d %H:%M')})

📈 시장 지표 현황:
- 대표님의 현재 단지별 랭킹: [{" / ".join([f"{mask_text(k)} {v}위" for k, v in my_ranks_dict.items() if v != '권외']) if any(v != '권외' for v in my_ranks_dict.values()) else '분석된 순위 없음'}]
- 상위 노출에서 밀려난 방어전 타겟: {len(danger_ls)}건 (즉시 재광고 추천)
- 6시간 이상 방치된 빈집 공격 타겟: {len(empty_houses)}건 (1위 탈환 가능)

🔥 경쟁사 동향:
- 가장 활발한 경쟁사: [{mask_text(clean_realtor_name(top_spender_raw_name), True) if top_spender_raw_name else '없음'}]
- {peak_hour_str} 해당 시간을 피해 광고를 올리거나, 자동화 솔루션으로 선점하세요.
            </p>
        </div>
        """, unsafe_allow_html=True)
        
        # [신규 UI] 시안 반영 가격 카드
        st.markdown("<h2 style='text-align:center; margin-bottom:30px;'>💳 프리미엄 서비스 안내</h2>", unsafe_allow_html=True)
        col_p1, col_p2, col_p3 = st.columns(3)
        card_html = """
        <div style="position: relative; padding: 30px 20px; border-radius: 20px; background-color: white; border: 1px solid #e5e8eb; box-shadow: 0 10px 25px rgba(0,0,0,0.05); text-align: center; height: 100%;">
            <div style="position: absolute; top: -15px; right: 15px; background-color: #ef4444; color: white; padding: 6px 12px; border-radius: 10px; font-weight: 800; font-size: 14px;">20% OFF</div>
            <div style="font-size: 20px; font-weight: 700; margin-bottom: 15px; color: #4b5563;">{title}</div>
            <div style="color: #9ca3af; text-decoration: line-through; font-size: 16px;">{old_price}</div>
            <div style="font-size: 32px; font-weight: 900; color: #3182f6; margin-bottom: 20px;">{new_price}</div>
            <div style="font-size: 14px; color: #6b7280;">{desc}</div>
        </div>
        """
        with col_p1: st.markdown(card_html.format(title="시장 분석 리포트", old_price="100,000 KRW", new_price="80,000 KRW", desc="매일 아침 자동 생성되는<br>단지별 점유율 및 경쟁사 분석"), unsafe_allow_html=True)
        with col_p2: st.markdown(card_html.format(title="⭐ 프리미엄 통합팩", old_price="160,000 KRW", new_price="130,000 KRW", desc="분석 리포트 + 광고 자동화<br>최고의 가성비 패키지"), unsafe_allow_html=True)
        with col_p3: st.markdown(card_html.format(title="광고 자동화 솔루션", old_price="100,000 KRW", new_price="80,000 KRW", desc="소장님이 잠든 새벽에도 24시간<br>원하는 시간에 재광고 무한 실행"), unsafe_allow_html=True)

        st.markdown("<br>", unsafe_allow_html=True)
        st.info("🏦 **결제 계좌:** 신한은행 110-388-348507 (예금주: 장성우)  \n📞 **문의:** 010-6502-2105")

    with tab_ms:
        st.info("💡 **점유율 가이드:** 매물 순위와 규모를 기반으로 파워점수를 산정하여 단지별 랭킹을 보여줍니다. (공식: 10점 + 순위 가중치 + 단지 규모 가산점)")
        filter_comp = st.selectbox("단지 필터", complex_list_with_all, key="ms_comp")
        ms_df = ms_counts.copy()
        if filter_comp != "전체 단지": ms_df = ms_df[ms_df['단지명'] == filter_comp]
        agg_ms = ms_df.groupby('부동산명').agg({'매물건수':'sum', '총점수':'sum'}).reset_index().sort_values('총점수', ascending=False)
        col_a, col_b = st.columns([1, 1])
        with col_a:
            ms_show = agg_ms.copy()
            ms_show['부동산명'] = ms_show['부동산명'].apply(lambda x: mask_text(x, True))
            st.dataframe(ms_show, use_container_width=True)
        with col_b:
            agg_ms['부동산명_축약'] = agg_ms['부동산명'].apply(lambda x: mask_text(clean_realtor_name(x), True))
            top10 = agg_ms.head(10).sort_values('총점수', ascending=True)
            fig = px.bar(top10, x='총점수', y='부동산명_축약', orientation='h', title=f"{mask_text(filter_comp)} 점유율 Top 10", text='총점수', color_discrete_sequence=['#3182f6'])
            st.plotly_chart(fig, use_container_width=True)

    with tab_danger:
        st.info("💡 **방어전 가이드:** 경쟁 부동산에 밀려 1위 자리에서 이탈한 매물들입니다. 즉시 재광고를 실행하여 최상단 자리를 탈환하세요.")
        if not danger_ls.empty:
            danger_show = danger_ls[['수집일시', '단지명', '동/호수', '층/타입', '거래방식', '묶음내순위_숫자', '현재1위부동산']].copy()
            danger_show['동/호수'] = danger_show['동/호수'].apply(mask_text)
            danger_show['현재1위부동산'] = danger_show['현재1위부동산'].apply(lambda x: mask_text(x, True))
            st.dataframe(danger_show, use_container_width=True)
        else: st.info("현재 1위에서 밀려난 매물이 없습니다!")

    with tab_empty:
        st.info("💡 **공격 타겟 가이드:** 타 부동산들이 6시간 이상 관리하지 않아 '방치'된 매물들입니다. 이 틈을 타 광고를 올리면 아주 쉽게 1위를 점령할 수 있습니다.")
        if not empty_houses.empty:
            empty_show = empty_houses[['단지명', '동/호수', '층/타입', '거래방식', '묶음내순위_숫자', '현재1위부동산', '방치시간(시간)']].copy()
            empty_show['동/호수'] = empty_show['동/호수'].apply(mask_text)
            empty_show['현재1위부동산'] = empty_houses['현재1위부동산'].apply(lambda x: mask_text(x, True))
            st.dataframe(empty_show, use_container_width=True)
        else: st.info("현재 6시간 이상 방치된 빈집 매물이 없습니다.")

    with tab_rolling:
        st.info("💡 **순위 롤링 가이드:** 네이버 부동산은 이용자마다 순위를 다르게 보여줍니다. 본 차트는 실시간 추적을 통해 내 매물의 실제 평균 노출 위치를 분석합니다.")
        c1, c2 = st.columns(2)
        tr_comp = c1.selectbox("단지명 선택", sorted(t_df['단지명'].dropna().unique()), key="tr_comp")
        bundle_list = sorted(t_df[t_df['단지명'] == tr_comp]['매물묶음키'].dropna().unique().tolist())
        tr_bundle = c2.selectbox("매물 묶음 선택", bundle_list, key="tr_bundle")
        if tr_comp and tr_bundle:
            bdf = t_df[(t_df['단지명'] == tr_comp) & (t_df['매물묶음키'] == tr_bundle)]
            def get_bundle_state(grp):
                first_place = grp[grp['묶음내순위_숫자'] == 1]
                realtor = first_place['부동산명'].iloc[0] if not first_place.empty else grp.sort_values('묶음내순위_숫자')['부동산명'].iloc[0]
                return pd.Series({'전체순위': grp['전체순위_숫자'].min(), '1위부동산': realtor})
            b_hist = bdf.groupby('수집일시').apply(get_bundle_state).reset_index()
            t_hist = pd.merge(pd.DataFrame({'수집일시': global_times}), b_hist, on='수집일시', how='left')
            t_hist['전체순위차트용'] = t_hist['전체순위'].fillna(21)
            t_hist['노출수준'] = t_hist['전체순위'].apply(lambda x: "✅ 상위 노출" if pd.notna(x) and x <= 20 else ("하위권" if pd.notna(x) else "이탈"))
            fig2 = px.line(t_hist, x='수집일시', y='전체순위차트용', markers=True, title=f"🌀 {mask_text(tr_comp)} 순위 히스토리", color_discrete_sequence=['#3182f6'])
            fig2.update_yaxes(autorange="reversed", range=[21.5, 0.5])
            st.plotly_chart(fig2, use_container_width=True)
            t_show = t_hist[['수집일시', '전체순위', '노출수준', '1위부동산']].copy()
            t_show['1위부동산'] = t_show['1위부동산'].apply(lambda x: mask_text(x, True))
            st.dataframe(t_show, use_container_width=True)

    with tab_timing:
        st.info("💡 **데이터 로그 가이드:** 수집된 데이터 중 가격이나 상태가 변경된 모든 '액션' 기록입니다. 경쟁사가 언제 움직였는지 증거를 확인하세요.")
        if not boosted_raw.empty:
            show_boost = boosted_raw[['수집일시', '부동산명', '단지명', '매물묶음키', '확인일자', '왜곡영역']].copy()
            show_boost['부동산명'] = show_boost['부동산명'].apply(lambda x: mask_text(x, True))
            show_boost['단지명'] = show_boost['단지명'].apply(mask_text)
            show_boost['비고'] = show_boost['왜곡영역'].apply(lambda x: "⚠️ 분석제외" if x else "정상")
            show_boost = show_boost.drop(columns=['왜곡영역'])
            st.dataframe(show_boost.sort_values('수집일시', ascending=False), use_container_width=True)
        else: st.info("갱신 내역이 없습니다.")
            
    with tab_stat:
        st.info("💡 **경쟁사 분석 가이드:** 라이벌 업체들이 주로 광고비를 지출하는 루틴을 분석합니다. (야간 저빈도 업체는 신뢰도를 위해 통계에서 제외됩니다.)")
        if not boosted_df.empty:
            boosted_df['활동시간대'] = boosted_df['수집일시'].dt.hour
            # 야간 저빈도 필터링
            realtor_stats = boosted_df.groupby('부동산명').agg(
                총횟수=('부동산명', 'count'), 
                평균시간=('활동시간대', lambda x: int(round(x.mean()))),
                늦은시간갱신=('활동시간대', lambda x: (x >= 19).any())
            ).reset_index()
            stat_df_final = realtor_stats[~((realtor_stats['늦은시간갱신'] == True) & (realtor_stats['총횟수'] <= 5))].sort_values('총횟수', ascending=False)
            
            c_a, c_b = st.columns(2)
            stat_show = stat_df_final.copy()
            stat_show['부동산명'] = stat_show['부동산명'].apply(lambda x: mask_text(x, True))
            stat_show['평균시간'] = stat_show['평균시간'].apply(lambda x: f"{x}시")
            c_a.dataframe(stat_show[['부동산명', '총횟수', '평균시간']], use_container_width=True)
            
            # 평균 시간대별 부동산 수 분포 그래프
            hc = stat_df_final.groupby('평균시간').size().reset_index(name='부동산수')
            fig3 = px.line(hc, x='평균시간', y='부동산수', title="시장 전체 광고 갱신 주력 시간대 (평균 기준)", markers=True, color_discrete_sequence=['#3182f6'])
            c_b.plotly_chart(fig3, use_container_width=True)

except Exception as e:
    st.error(f"🚨 데이터 처리 중 치명적 오류 발생: {e}")
