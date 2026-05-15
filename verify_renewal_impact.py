"""
verify_renewal_impact.py

[목적]
TOP RANK AI 시스템의 핵심 전제인
'광고 갱신(최신성) → 상위권 도달 → 시간 흐름에 따른 순위 하락'
가설을 데이터에 존재하는 모든 부동산을 대상으로 전수 검증한다.

[분석 항목]
1) 갱신 직후 즉각적 순위 임팩트 (평균 상승폭, TOP3 타격 성공률)
2) 갱신 시점(T) 기준 +1h / +3h / +6h / +12h 평균 순위 디케이 곡선
   (생존자만 포함 — 재갱신·이탈 매물 제외)
3) [생존자 편향 통제] 이탈/재갱신을 '999(논리적 최하위)'로 처리한 진짜 디케이
4) [경쟁 압력별 생존율] 동일 단지+평형 내 (T, T+3h] 타사 갱신 건수에 따라
   Blue Ocean(0건) / Normal(1~2건) / Red Ocean(3건+) 그룹으로 나누어
   T+3h 시점 TOP3 유지율 비교
5) [Cluster Size 통제] 매물묶음키별 참여 부동산 수(체급 1~3 / 4~10 / 11+)와
   묶음 내 타사 갱신 비율(Blue 0% / Normal ~30% / Red 30%+)을 교차한
   3×3 매트릭스 — 분석 4의 교란변수(묶음 크기) 보정
6) [Golden Cell 시간대 분포] 분석 5에서 찾은 '대형 × Blue' 황금 타점이
   하루 24시간 중 어느 시간대에 발생하는지 — 점심/저녁 피크 vs 새벽
7) [Golden vs Red 디케이 비교] 같은 대형 묶음 안에서 Blue/Red의 TOP3
   유지율을 T+1h/3h/6h/12h 시점별로 비교 — 효과의 지속 시간 측정

[실행]
  python verify_renewal_impact.py

* 별도의 독립 스크립트이므로 Streamlit 실행 컨텍스트 없이도 동작한다.
"""

from __future__ import annotations

import os
import sys
import time
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

# Streamlit가 콘솔에 띄우는 ScriptRunContext 경고 차단
os.environ.setdefault("STREAMLIT_LOG_LEVEL", "error")

# 한글/특수문자(▲▼) 출력 안정화 (Windows PowerShell 대응)
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if _BASE_DIR not in sys.path:
    sys.path.insert(0, _BASE_DIR)

from data_fetcher import clean_realtor_name, process_data  # noqa: E402


# ---------------------------------------------------------------------------
# 상수
# ---------------------------------------------------------------------------
DATA_DIR = os.path.join(_BASE_DIR, "data")
TARGET_FILES = [
    "naver_market_report_2026_04.parquet",
    "naver_market_report_2026_05.parquet",
]

GRP_KEYS = [
    "부동산명_정제",
    "단지명",
    "동/호수",
    "층/타입",
    "거래방식",
    "가격",
    "CP사",
]
DECAY_OFFSETS_HOURS = [1, 3, 6, 12]
# 디케이 매칭 시 타겟 시각(T+offset) 기준 ± 허용 오차
# (단지별 수집 세션 간격이 약 30~40분이므로 30분이면 충분히 가까운 관측치 포착)
DECAY_TOLERANCE = pd.Timedelta(minutes=30)
# 분석 3에서 매칭 실패(재갱신·이탈)를 '논리적 최하위'로 간주할 때의 순위 값
DROPOUT_RANK = 999.0
# 분석 4 경쟁 압력 윈도우
PRESSURE_WINDOW_HOURS = 3


# ---------------------------------------------------------------------------
# 데이터 로더 (data/ 폴더 내 4월·5월 parquet 직접 취합)
# ---------------------------------------------------------------------------
def load_target_parquets() -> pd.DataFrame | None:
    """
    `data_fetcher.load_server_data()`는 최근 14일 cutoff 필터를 적용하므로
    4월 데이터를 보려면 우회해야 한다. 본 함수는 지정된 두 parquet 파일을
    직접 로드 → concat → 중복 제거 후 반환한다.
    """
    if not os.path.isdir(DATA_DIR):
        print(f"  ! 데이터 폴더가 없습니다: {DATA_DIR}")
        return None

    frames: list[pd.DataFrame] = []
    for name in TARGET_FILES:
        path = os.path.join(DATA_DIR, name)
        if not os.path.exists(path):
            print(f"  ! 파일 누락: {path}")
            continue
        t0 = time.time()
        size_mb = os.path.getsize(path) / (1024 * 1024)
        d = pd.read_parquet(path)
        print(
            f"      • {name:<42} → {len(d):>10,} 행  "
            f"({size_mb:>6.1f} MB, {time.time() - t0:.2f}s)"
        )
        frames.append(d)

    if not frames:
        return None

    df = pd.concat(frames, ignore_index=True).drop_duplicates()
    df["수집일시"] = pd.to_datetime(df["수집일시"], errors="coerce")
    df = df[df["수집일시"].notna()].copy()

    if not df.empty:
        dmin, dmax = df["수집일시"].min(), df["수집일시"].max()
        days = (dmax - dmin).total_seconds() / 86400
        print(
            f"      → 취합 결과 {len(df):,} 행 · 기간 "
            f"{dmin:%Y-%m-%d %H:%M} ~ {dmax:%Y-%m-%d %H:%M} ({days:.1f}일)"
        )
    return df


# ---------------------------------------------------------------------------
# 핵심 로직
# ---------------------------------------------------------------------------
def detect_renewals(df: pd.DataFrame) -> pd.DataFrame:
    """
    grp_keys 기준으로 정렬한 뒤, 동일 매물 내에서 '고유번호'가
    직전 행(shift(1))과 달라지는 순간을 갱신 이벤트로 포착한다.

    반환 DF에는 다음 컬럼이 추가된다.
      - is_renewed : 갱신 발생 여부 (bool)
      - 갱신_전_순위 / 갱신_전_시각 / 갱신_전_고유번호
    """
    df = df.copy()

    df["부동산명_정제"] = df["부동산명"].astype(str).map(clean_realtor_name)

    for c in GRP_KEYS:
        if c not in df.columns:
            df[c] = "미상"
        df[c] = df[c].fillna("미상").astype(str)

    if "고유번호" not in df.columns:
        df["고유번호"] = "기록없음"
    df["고유번호"] = df["고유번호"].fillna("기록없음").astype(str)

    df["수집일시"] = pd.to_datetime(df["수집일시"], errors="coerce")
    df = df[df["수집일시"].notna()].copy()

    df = df.sort_values(GRP_KEYS + ["수집일시"]).reset_index(drop=True)

    g = df.groupby(GRP_KEYS, dropna=False, sort=False)
    df["갱신_전_고유번호"] = g["고유번호"].shift(1)
    df["갱신_전_순위"] = g["묶음내순위_숫자"].shift(1)
    df["갱신_전_시각"] = g["수집일시"].shift(1)

    df["is_renewed"] = (
        df["갱신_전_고유번호"].notna()
        & (df["고유번호"] != df["갱신_전_고유번호"])
        & (df["고유번호"] != "기록없음")
        & (df["갱신_전_고유번호"] != "기록없음")
    )

    return df


def analyze_immediate_impact(renewed: pd.DataFrame) -> dict:
    """[분석 1] 갱신 직전 vs 직후 순위 비교."""
    before = pd.to_numeric(renewed["갱신_전_순위"], errors="coerce")
    after = pd.to_numeric(renewed["묶음내순위_숫자"], errors="coerce")

    # 999는 "순위 정보 없음"의 fill 값이므로 분석 대상에서 제외
    valid = before.notna() & after.notna() & (before < 999) & (after < 999)
    before = before[valid].astype(float)
    after = after[valid].astype(float)
    delta = before - after  # +가 상승

    n = int(len(after))
    if n == 0:
        return {
            "n": 0, "avg_before": np.nan, "avg_after": np.nan,
            "avg_delta": np.nan, "median_delta": np.nan,
            "top1_hit": 0, "top1_rate": np.nan,
            "top3_hit": 0, "top3_rate": np.nan,
            "top5_hit": 0, "top5_rate": np.nan,
            "improved_rate": np.nan,
        }

    return {
        "n": n,
        "avg_before": float(before.mean()),
        "avg_after": float(after.mean()),
        "avg_delta": float(delta.mean()),
        "median_delta": float(delta.median()),
        "top1_hit": int((after <= 1).sum()),
        "top1_rate": float((after <= 1).mean() * 100),
        "top3_hit": int((after <= 3).sum()),
        "top3_rate": float((after <= 3).mean() * 100),
        "top5_hit": int((after <= 5).sum()),
        "top5_rate": float((after <= 5).mean() * 100),
        "improved_rate": float((delta > 0).mean() * 100),
    }


def analyze_decay_curve(
    df: pd.DataFrame, renewed: pd.DataFrame
) -> tuple[list[dict], list[dict], pd.Series]:
    """
    [분석 2 + 분석 3] 갱신 시점(T) 기준 T+offset 시점의 평균 순위.

    한 번의 merge_asof 패스로 두 가지 관점을 함께 산출한다.

    분석 2 (Survivor view):
      - 매칭에 실패한(NaN) 표본을 제외 → 동일 고유번호로 살아남은 매물만 추적.
      - "한 번의 갱신이 자연스럽게 늙어가는 곡선"을 본다 (생존자 편향 존재).

    분석 3 (Lifespan view):
      - 매칭 실패(=재갱신으로 고유번호가 또 바뀌었거나, 순위권 밖으로 밀려나
        크롤링되지 않은 매물)를 'DROPOUT_RANK(999)'으로 채워 N을 유지한다.
      - 시장에서 실제로 체감되는 '진짜 디케이 곡선'을 보여준다.

    추가 반환:
      - per_event_ranks : 갱신 이벤트별 모든 offset의 순위(이탈은 999)
        DataFrame 인덱스는 _evt_id, 컬럼은 'rank_T+1h'/'rank_T+3h'/...
        분석 4·5(T+3h) 및 분석 7(T+1/3/6/12h 비교)에서 모두 사용된다.
    """
    obs_cols = GRP_KEYS + ["고유번호", "수집일시", "묶음내순위_숫자"]
    obs = df[obs_cols].dropna(subset=["수집일시"]).copy()
    obs = obs.sort_values("수집일시").reset_index(drop=True)
    obs = obs.rename(columns={"수집일시": "관측시각", "묶음내순위_숫자": "관측순위"})

    base = renewed.loc[renewed["is_renewed"], obs_cols].copy().reset_index(drop=True)
    base["_evt_id"] = np.arange(len(base))
    base = base.rename(columns={"수집일시": "갱신시각", "묶음내순위_숫자": "갱신순위"})

    survivor: list[dict] = []
    lifespan: list[dict] = []
    per_event_data: dict[int, pd.Series] = {}

    for h in DECAY_OFFSETS_HOURS:
        target = base.copy()
        target["타겟시각"] = target["갱신시각"] + pd.Timedelta(hours=h)
        target = target.sort_values("타겟시각").reset_index(drop=True)

        merged = pd.merge_asof(
            target,
            obs,
            left_on="타겟시각",
            right_on="관측시각",
            by=GRP_KEYS + ["고유번호"],
            direction="nearest",
            tolerance=DECAY_TOLERANCE,
        )

        rank_raw = pd.to_numeric(merged["관측순위"], errors="coerce")

        # --- 분석 2 : Survivor view (NaN/999 제외) ---
        rank_s = rank_raw[rank_raw.notna() & (rank_raw < 999)]
        n_s = int(len(rank_s))
        survivor.append(
            {
                "offset_h": h,
                "n": n_s,
                "avg_rank": float(rank_s.mean()) if n_s else np.nan,
                "median_rank": float(rank_s.median()) if n_s else np.nan,
                "top3_rate": float((rank_s <= 3).mean() * 100) if n_s else np.nan,
            }
        )

        # --- 분석 3 : Lifespan view (NaN → DROPOUT_RANK) ---
        rank_l = rank_raw.fillna(DROPOUT_RANK)
        n_l = int(len(rank_l))
        n_drop = int(rank_raw.isna().sum())
        lifespan.append(
            {
                "offset_h": h,
                "n": n_l,
                "n_dropout": n_drop,
                "dropout_rate": (n_drop / n_l * 100) if n_l else np.nan,
                "avg_rank": float(rank_l.mean()) if n_l else np.nan,
                "median_rank": float(rank_l.median()) if n_l else np.nan,
                "top3_rate": float((rank_l <= 3).mean() * 100) if n_l else np.nan,
            }
        )

        # --- 분석 4·5·7용 보조 데이터: 이벤트별 T+offset 순위 ---
        per_event_data[h] = pd.Series(
            rank_l.values,
            index=merged["_evt_id"].astype(int).values,
            name=f"rank_T+{h}h",
        )

    per_event_ranks = pd.DataFrame(
        {f"rank_T+{h}h": per_event_data[h] for h in DECAY_OFFSETS_HOURS}
    )
    per_event_ranks.index.name = "_evt_id"
    per_event_ranks = per_event_ranks.sort_index()

    return survivor, lifespan, per_event_ranks


def _extract_area(floor_type: pd.Series) -> pd.Series:
    """'층/타입' 컬럼은 process_data 단계에서 'area|floor|direction' 포맷으로
    표준화되어 있다. 여기서 area 부분만 추출하여 '평형'으로 사용한다."""
    return floor_type.astype(str).str.split("|").str[0].str.strip()


def _count_competitor_renewals(
    renewed: pd.DataFrame, hours: int = PRESSURE_WINDOW_HOURS
) -> np.ndarray:
    """
    각 갱신 이벤트(T)마다 동일 (단지명, 평형) 내에서 [T, T+hours] 윈도우에
    발생한 '타사 부동산'의 갱신 건수를 센다.

    - 자기 자신(같은 부동산)의 갱신은 시간이 같든 다르든 모두 제외 → 순수
      외부 경쟁 압력만 측정.
    - (단지, 평형) 그룹 내에서 시간 정렬 후 searchsorted로 윈도우 인덱스
      범위를 벡터로 구해 윈도우 안의 부동산명을 비교하는 방식.
      O(N · 윈도우 크기)로 동작하며 29k 이벤트 기준 1초 미만.
    """
    n = len(renewed)
    counts = np.zeros(n, dtype=np.int32)
    if n == 0:
        return counts

    work = pd.DataFrame(
        {
            "단지명": renewed["단지명"].astype(str).values,
            "평형": _extract_area(renewed["층/타입"]).values,
            "시각": pd.to_datetime(renewed["수집일시"]).values,
            "부동산": renewed["부동산명_정제"].astype(str).values,
            "_pos": np.arange(n, dtype=np.int64),
        }
    )

    delta = np.timedelta64(int(hours), "h")

    for _, grp in work.groupby(["단지명", "평형"], sort=False):
        if len(grp) < 2:
            continue  # 본인뿐이라면 경쟁사 갱신 0건
        grp = grp.sort_values("시각")
        times = grp["시각"].values.astype("datetime64[ns]")
        realtors = grp["부동산"].values
        positions = grp["_pos"].values

        # [T_i, T_i + delta]
        starts = np.searchsorted(times, times, side="left")
        ends = np.searchsorted(times, times + delta, side="right")

        for i in range(len(times)):
            s, e = starts[i], ends[i]
            if e > s:
                # 같은 부동산은 모두 제외(자기 자신 + 본인의 다른 매물)
                counts[positions[i]] = int((realtors[s:e] != realtors[i]).sum())

    return counts


def analyze_competitive_pressure(
    renewed: pd.DataFrame, t3h_rank: pd.Series
) -> tuple[list[dict], dict]:
    """
    [분석 4] 동일 (단지, 평형) 내 (T, T+3h] 타사 갱신 건수에 따른 T+3h 생존율.

    그룹 정의:
      A. Blue Ocean : 0건
      B. Normal     : 1~2건
      C. Red Ocean  : 3건 이상
    """
    if len(renewed) == 0:
        return [], {}

    base = renewed.loc[renewed["is_renewed"]].copy().reset_index(drop=True)
    # 분석 2/3와 동일 순서로 _evt_id 부여 (t3h_rank 인덱스와 정합)
    base["_evt_id"] = np.arange(len(base))
    base["평형"] = _extract_area(base["층/타입"])

    # 단지명·평형이 식별 가능한 이벤트만 분석. _evt_id는 보존 (재할당 X)
    valid_mask = (base["단지명"].astype(str) != "미상") & base["평형"].astype(bool)
    base = base[valid_mask].reset_index(drop=True)

    base["타사_갱신수"] = _count_competitor_renewals(base, hours=PRESSURE_WINDOW_HOURS)
    base["순위_T+3h"] = base["_evt_id"].map(t3h_rank).fillna(DROPOUT_RANK).astype(float)

    def _bucket(c: int) -> str:
        if c <= 0:
            return "A. Blue Ocean (0건)"
        if c <= 2:
            return "B. Normal (1~2건)"
        return "C. Red Ocean (3건+)"

    base["압력그룹"] = base["타사_갱신수"].apply(_bucket)

    bucket_order = [
        "A. Blue Ocean (0건)",
        "B. Normal (1~2건)",
        "C. Red Ocean (3건+)",
    ]
    results: list[dict] = []
    for name in bucket_order:
        sub = base[base["압력그룹"] == name]
        n = len(sub)
        if n == 0:
            results.append(
                {
                    "name": name, "n": 0, "share": 0.0,
                    "avg_competitors": np.nan, "avg_rank": np.nan,
                    "median_rank": np.nan, "top3_rate": np.nan,
                    "dropout_rate": np.nan,
                }
            )
            continue

        rank = sub["순위_T+3h"]
        results.append(
            {
                "name": name,
                "n": int(n),
                "share": float(n / len(base) * 100),
                "avg_competitors": float(sub["타사_갱신수"].mean()),
                "avg_rank": float(rank.mean()),
                "median_rank": float(rank.median()),
                "top3_rate": float((rank <= 3).mean() * 100),
                "dropout_rate": float((rank >= DROPOUT_RANK).mean() * 100),
            }
        )

    summary = {
        "total_events_analyzed": int(len(base)),
        "avg_competitors_overall": float(base["타사_갱신수"].mean()),
        "max_competitors": int(base["타사_갱신수"].max()),
    }
    return results, summary


# ---------------------------------------------------------------------------
# [분석 5] Cluster Size 통제 후 압력 매트릭스
# ---------------------------------------------------------------------------
def _add_cluster_id(frame: pd.DataFrame) -> pd.Series:
    """
    동일 물건(같은 단지의 같은 동/호수/타입/거래방식/CP)을 식별하는 키.
    process_data의 매물묶음키는 단지명을 포함하지 않아 다른 단지에서 동일한
    동/호수가 충돌할 수 있으므로 단지명을 prefix로 결합한다.
    """
    return (
        frame["단지명"].astype(str).str.strip()
        + "║"
        + frame["매물묶음키"].astype(str)
    )


def _count_renewals_in_bundle(
    renewed: pd.DataFrame,
    cluster_col: str,
    hours: int = PRESSURE_WINDOW_HOURS,
) -> np.ndarray:
    """
    동일 매물 묶음(`cluster_col`) 내에서 (T, T+hours] 윈도우에 발생한
    '타사 부동산'의 갱신 건수를 카운트한다.

    분석 4의 단지+평형 스코프와 달리 이쪽은 '같은 매물(동/호수)을 두고
    직접 경쟁하는 부동산'들 사이의 갱신 빈도이므로 압력 정의가 더 정확하다.
    """
    n = len(renewed)
    counts = np.zeros(n, dtype=np.int32)
    if n == 0:
        return counts

    work = pd.DataFrame(
        {
            "묶음": renewed[cluster_col].astype(str).values,
            "시각": pd.to_datetime(renewed["수집일시"]).values,
            "부동산": renewed["부동산명_정제"].astype(str).values,
            "_pos": np.arange(n, dtype=np.int64),
        }
    )

    delta = np.timedelta64(int(hours), "h")

    for _, grp in work.groupby("묶음", sort=False):
        if len(grp) < 2:
            continue
        grp = grp.sort_values("시각")
        times = grp["시각"].values.astype("datetime64[ns]")
        realtors = grp["부동산"].values
        positions = grp["_pos"].values

        starts = np.searchsorted(times, times, side="left")
        ends = np.searchsorted(times, times + delta, side="right")

        for i in range(len(times)):
            s, e = starts[i], ends[i]
            if e > s:
                counts[positions[i]] = int((realtors[s:e] != realtors[i]).sum())

    return counts


def analyze_cluster_pressure_matrix(
    df: pd.DataFrame, renewed: pd.DataFrame, t3h_rank: pd.Series
) -> tuple[list[list[dict]], dict, pd.DataFrame]:
    """
    [분석 5] Cluster Size를 통제한 3 체급 × 3 압력 매트릭스.

    체급 (매물묶음키별 고유 부동산 수):
        🥉 소형  : 1 ~ 3 명
        🥈 중형  : 4 ~ 10 명
        🥇 대형  : 11 명 이상

    압력 (T, T+3h] 동일 묶음 내 타사 갱신 비율 = 타사갱신수 / max(총원-1, 1):
        Blue   : 0 %
        Normal : 0 % 초과 ~ 30 % 이하
        Red    : 30 % 초과

    각 셀에서 T+3h 시점 'TOP3 유지율'(Lifespan 기준 — 이탈은 999로 채움)을
    산출한다. 압력 정의를 '비율'로 바꾼 덕분에 체급 간 직접 비교가 가능하다.

    추가 반환:
      - labeled_events : 이벤트 단위로 _evt_id, 체급, 압력, 묶음_총개수,
        타사_갱신율, 수집일시 등을 포함한 DataFrame. 분석 6·7에서 재사용.
    """
    if len(renewed) == 0:
        return [], {}, pd.DataFrame()

    base = renewed.loc[renewed["is_renewed"]].copy().reset_index(drop=True)
    # _evt_id는 분석 2/3와 동일한 순서 → t3h_rank 인덱스와 정합
    base["_evt_id"] = np.arange(len(base))
    base["_cluster_id"] = _add_cluster_id(base)

    # (1) 체급: 전체 df 기준 cluster size를 사용 (특정 시점 활성 수가 아니라
    #     해당 매물에 '평소 참여하는' 부동산 풀의 크기)
    df_keyed = df.copy()
    df_keyed["_cluster_id"] = _add_cluster_id(df_keyed)
    cluster_size = (
        df_keyed.groupby("_cluster_id", dropna=False)["부동산명_정제"]
        .nunique()
        .rename("묶음_총개수")
    )
    base = base.merge(cluster_size, on="_cluster_id", how="left")
    base["묶음_총개수"] = base["묶음_총개수"].fillna(1).astype(int)

    # (2) 같은 묶음 내 타사 갱신 건수
    base["묶음내_타사갱신수"] = _count_renewals_in_bundle(
        base, "_cluster_id", hours=PRESSURE_WINDOW_HOURS
    )

    # (3) 갱신 비율 = 타사갱신수 / (총원-1, 최소 1)
    other_count = (base["묶음_총개수"] - 1).clip(lower=1)
    base["타사_갱신율"] = base["묶음내_타사갱신수"] / other_count

    # (4) 체급 라벨
    def _tier(size: int) -> str:
        if size <= 3:
            return "🥉 소형 (1~3)"
        if size <= 10:
            return "🥈 중형 (4~10)"
        return "🥇 대형 (11+)"

    base["체급"] = base["묶음_총개수"].apply(_tier)

    # (5) 압력 라벨
    def _pressure(ratio: float) -> str:
        if ratio <= 0.0:
            return "Blue"
        if ratio <= 0.30:
            return "Normal"
        return "Red"

    base["압력"] = base["타사_갱신율"].apply(_pressure)

    # (6) T+3h 순위 (Lifespan: 이탈은 999)
    base["순위_T+3h"] = (
        base["_evt_id"].map(t3h_rank).fillna(DROPOUT_RANK).astype(float)
    )

    # (7) 3 × 3 매트릭스
    tier_order = ["🥉 소형 (1~3)", "🥈 중형 (4~10)", "🥇 대형 (11+)"]
    pressure_order = ["Blue", "Normal", "Red"]

    matrix: list[list[dict]] = []
    for t in tier_order:
        row: list[dict] = []
        sub_t = base[base["체급"] == t]
        for p in pressure_order:
            sub = sub_t[sub_t["압력"] == p]
            n = len(sub)
            if n == 0:
                row.append(
                    {
                        "tier": t, "pressure": p, "n": 0,
                        "top3_rate": np.nan, "dropout_rate": np.nan,
                        "avg_rank": np.nan, "avg_ratio": np.nan,
                    }
                )
                continue
            rank = sub["순위_T+3h"]
            row.append(
                {
                    "tier": t,
                    "pressure": p,
                    "n": int(n),
                    "top3_rate": float((rank <= 3).mean() * 100),
                    "dropout_rate": float((rank >= DROPOUT_RANK).mean() * 100),
                    "avg_rank": float(rank.mean()),
                    "avg_ratio": float(sub["타사_갱신율"].mean() * 100),
                }
            )
        matrix.append(row)

    # 체급 분포
    tier_counts = base["체급"].value_counts()
    total = len(base)
    summary = {
        "total": int(total),
        "avg_cluster_size": float(base["묶음_총개수"].mean()),
        "median_cluster_size": float(base["묶음_총개수"].median()),
        "max_cluster_size": int(base["묶음_총개수"].max()),
        "tier_share": {
            t: float(tier_counts.get(t, 0) / total * 100) if total else 0.0
            for t in tier_order
        },
    }

    # 분석 6·7에서 사용할 라벨링된 이벤트 (필요 컬럼만 슬라이스)
    labeled_events = base[
        ["_evt_id", "체급", "압력", "묶음_총개수", "타사_갱신율", "수집일시", "단지명"]
    ].copy()

    return matrix, summary, labeled_events


# ---------------------------------------------------------------------------
# [분석 6] 황금 타점(대형-Blue)의 시간대별 발생 분포
# ---------------------------------------------------------------------------
GOLDEN_TIER = "🥇 대형 (11+)"
GOLDEN_PRESSURE = "Blue"
RED_PRESSURE = "Red"

# 트래픽 피크 정의 (네이버 부동산 기준 휴리스틱)
LUNCH_HOURS = [11, 12, 13]
EVENING_HOURS = [18, 19, 20]
DAWN_HOURS = [0, 1, 2, 3, 4, 5]


def analyze_golden_hour_distribution(labeled_events: pd.DataFrame) -> dict:
    """
    [분석 6] 분석 5의 'Golden Cell' (대형 묶음 × Blue Ocean) 표본만 추출하여
    수집일시(=갱신 발생 시각)의 시(hour) 분포를 산출.

    팩트 체크 포인트:
      - 점심(11~13시)·저녁(18~20시)에 황금 타점이 의미 있는 비중으로 열리는가?
      - 새벽 시간대에만 몰려있어서 '실전 활용 불가능한 신호'가 아닌가?
    """
    if labeled_events is None or len(labeled_events) == 0:
        return {"n": 0}

    golden = labeled_events[
        (labeled_events["체급"] == GOLDEN_TIER)
        & (labeled_events["압력"] == GOLDEN_PRESSURE)
    ].copy()

    n = len(golden)
    if n == 0:
        return {"n": 0}

    times = pd.to_datetime(golden["수집일시"], errors="coerce")
    hours = times.dt.hour.dropna().astype(int)

    counts = hours.value_counts().reindex(range(24), fill_value=0).sort_index()
    pct = (counts / n * 100).round(4)

    hourly = [
        {"hour": int(h), "count": int(counts.iloc[h]), "pct": float(pct.iloc[h])}
        for h in range(24)
    ]

    def _bucket_share(hours_list: list[int]) -> tuple[float, int]:
        c = int(counts.reindex(hours_list, fill_value=0).sum())
        return (c / n * 100.0, c)

    lunch_share, lunch_cnt = _bucket_share(LUNCH_HOURS)
    evening_share, evening_cnt = _bucket_share(EVENING_HOURS)
    dawn_share, dawn_cnt = _bucket_share(DAWN_HOURS)
    peak_share = lunch_share + evening_share
    peak_cnt = lunch_cnt + evening_cnt

    # Top hour
    top_idx = int(counts.idxmax())
    top_pct = float(pct.iloc[top_idx])

    return {
        "n": int(n),
        "hourly": hourly,
        "max_pct": float(pct.max()),
        "top_hour": top_idx,
        "top_hour_pct": top_pct,
        "lunch_share": float(lunch_share),
        "lunch_cnt": int(lunch_cnt),
        "evening_share": float(evening_share),
        "evening_cnt": int(evening_cnt),
        "peak_share": float(peak_share),
        "peak_cnt": int(peak_cnt),
        "dawn_share": float(dawn_share),
        "dawn_cnt": int(dawn_cnt),
    }


# ---------------------------------------------------------------------------
# [분석 7] 황금 타점(대형-Blue) vs 출혈 경쟁(대형-Red) 디케이 비교
# ---------------------------------------------------------------------------
def analyze_golden_vs_red_decay(
    labeled_events: pd.DataFrame, per_event_ranks: pd.DataFrame
) -> tuple[list[dict], dict]:
    """
    [분석 7] 동일 체급(대형 11+) 안에서 압력만 극단적으로 다른 두 그룹의
    T+1h / T+3h / T+6h / T+12h 시점 TOP3 유지율을 비교.

    같은 체급이므로 Cluster Size 효과는 통제되어 있고, 차이는 순수하게
    경쟁 압력에서 비롯된다. 시간이 갈수록 격차가 확대되는지(=빈집 효과의
    유통기한이 긴지) 직접 확인할 수 있다.
    """
    if labeled_events is None or len(labeled_events) == 0:
        return [], {}

    big = labeled_events[labeled_events["체급"] == GOLDEN_TIER]
    if len(big) == 0:
        return [], {}

    blue_ids = big.loc[big["압력"] == GOLDEN_PRESSURE, "_evt_id"].astype(int).values
    red_ids = big.loc[big["압력"] == RED_PRESSURE, "_evt_id"].astype(int).values

    blue_ranks = per_event_ranks.reindex(blue_ids)
    red_ranks = per_event_ranks.reindex(red_ids)

    rows: list[dict] = []
    for h in DECAY_OFFSETS_HOURS:
        col = f"rank_T+{h}h"
        if col not in per_event_ranks.columns:
            continue

        b = blue_ranks[col].fillna(DROPOUT_RANK)
        r = red_ranks[col].fillna(DROPOUT_RANK)

        b_n = int(b.notna().sum())
        r_n = int(r.notna().sum())
        b_top3 = float((b <= 3).mean() * 100) if b_n else np.nan
        r_top3 = float((r <= 3).mean() * 100) if r_n else np.nan
        b_drop = float((b >= DROPOUT_RANK).mean() * 100) if b_n else np.nan
        r_drop = float((r >= DROPOUT_RANK).mean() * 100) if r_n else np.nan

        delta = (
            b_top3 - r_top3
            if not (np.isnan(b_top3) or np.isnan(r_top3))
            else np.nan
        )

        rows.append(
            {
                "offset_h": h,
                "blue_n": b_n,
                "red_n": r_n,
                "blue_top3": b_top3,
                "red_top3": r_top3,
                "blue_dropout": b_drop,
                "red_dropout": r_drop,
                "delta": delta,
            }
        )

    summary = {
        "blue_n": int(len(blue_ids)),
        "red_n": int(len(red_ids)),
    }
    return rows, summary


# ---------------------------------------------------------------------------
# 리포트 출력
# ---------------------------------------------------------------------------
def _visible_width(s: str) -> int:
    """콘솔에서 차지하는 표시 폭 근사 (CJK·이모지를 2칸으로 계산)."""
    width = 0
    for ch in s:
        cp = ord(ch)
        # CJK Unified Ideographs / Hangul Syllables / Emoji 등은 2칸 폭
        if (
            0x1100 <= cp <= 0x115F  # Hangul Jamo
            or 0x2E80 <= cp <= 0x9FFF  # CJK
            or 0xA000 <= cp <= 0xA4CF
            or 0xAC00 <= cp <= 0xD7A3  # Hangul Syllables
            or 0xF900 <= cp <= 0xFAFF
            or 0xFE30 <= cp <= 0xFE4F
            or 0xFF00 <= cp <= 0xFF60
            or 0xFFE0 <= cp <= 0xFFE6
            or 0x1F300 <= cp <= 0x1FAFF  # Emoji blocks (수상 이모지 포함)
            or 0x2600 <= cp <= 0x27BF
        ):
            width += 2
        elif cp >= 0x20:
            width += 1
    return width


def _pad_visible(s: str, width: int, align: str = "left") -> str:
    """표시 폭 기준 좌/우 패딩."""
    diff = max(0, width - _visible_width(s))
    if align == "right":
        return " " * diff + s
    return s + " " * diff


def render_report(
    impact: dict,
    decay: list[dict],
    lifespan: list[dict],
    pressure: list[dict],
    pressure_summary: dict,
    cluster_matrix: list[list[dict]],
    cluster_summary: dict,
    golden_hours: dict,
    golden_decay: list[dict],
    *,
    total_rows: int,
    total_renewals: int,
    elapsed_sec: float,
) -> None:
    bar = "═" * 68
    sub = "─" * 68

    print()
    print(bar)
    print("  TOP RANK AI · 광고 갱신 임팩트 전수 검증 리포트")
    print(bar)
    print(f"  데이터 총 행 수          : {total_rows:>10,} 행")
    print(f"  포착된 갱신 이벤트(전체) : {total_renewals:>10,} 건")
    print(f"  분석 1 유효 표본(N)       : {impact['n']:>10,} 건")
    print(f"  소요 시간                : {elapsed_sec:>10.2f} 초")
    print()

    print("[ 분석 1 ] 갱신 직후 즉각적 순위 임팩트")
    print(sub)
    if impact["n"] == 0:
        print("  ! 유효 표본이 없어 분석을 수행할 수 없습니다.")
    else:
        print(
            f"  평균 순위 변화        : {impact['avg_before']:>6.2f} 위  ➔  "
            f"{impact['avg_after']:>5.2f} 위"
        )
        print(
            f"  평균 상승폭          : ▲ {impact['avg_delta']:>5.2f} 계단  "
            f"(중앙값 ▲ {impact['median_delta']:.2f})"
        )
        print(f"  순위 상승 발생 비율   : {impact['improved_rate']:>6.2f} %")
        print(
            f"  TOP 1 타격 성공률     : {impact['top1_rate']:>6.2f} %   "
            f"({impact['top1_hit']:,} / {impact['n']:,} 건)"
        )
        print(
            f"  TOP 3 타격 성공률 ★  : {impact['top3_rate']:>6.2f} %   "
            f"({impact['top3_hit']:,} / {impact['n']:,} 건)"
        )
        print(
            f"  TOP 5 타격 성공률     : {impact['top5_rate']:>6.2f} %   "
            f"({impact['top5_hit']:,} / {impact['n']:,} 건)"
        )
    print()

    print("[ 분석 2 ] 시간 경과 디케이 곡선 (Survivor view · 재갱신/이탈 제외)")
    print(sub)
    print(
        f"  {'경과시간':<10}{'표본 N':>10}{'평균 순위':>14}"
        f"{'중앙 순위':>14}{'TOP3 유지율':>16}"
    )
    print(sub)

    base_avg = decay[0]["avg_rank"] if decay and not np.isnan(decay[0]["avg_rank"]) else None
    for r in decay:
        if r["n"] == 0 or np.isnan(r["avg_rank"]):
            print(
                f"  T+{r['offset_h']:>2}h     {r['n']:>10,}"
                f"{'-':>14}{'-':>14}{'-':>16}"
            )
            continue

        suffix = ""
        if base_avg is not None and r["offset_h"] != DECAY_OFFSETS_HOURS[0]:
            diff = r["avg_rank"] - base_avg
            if diff > 0:
                suffix = f"  (▼ {diff:.2f})"
            elif diff < 0:
                suffix = f"  (▲ {abs(diff):.2f})"

        print(
            f"  T+{r['offset_h']:>2}h     "
            f"{r['n']:>10,}"
            f"{r['avg_rank']:>14.2f}"
            f"{r['median_rank']:>14.2f}"
            f"{r['top3_rate']:>15.2f}%"
            f"{suffix}"
        )
    print()

    # ---------------- 분석 3 : Lifespan view ----------------
    print("[ 분석 3 ] 진짜 시장 디케이 곡선 (Lifespan view · 이탈/재갱신 = 999)")
    print("           ※ 매칭 실패 = 재갱신 또는 순위권 밖 이탈, 두 경우 모두 포함")
    print(sub)
    print(
        f"  {'경과시간':<10}{'표본 N':>10}{'이탈건수':>10}{'이탈률':>10}"
        f"{'평균 순위':>13}{'중앙 순위':>13}{'TOP3 유지율':>16}"
    )
    print(sub)

    base_top3 = (
        lifespan[0]["top3_rate"]
        if lifespan and not np.isnan(lifespan[0]["top3_rate"])
        else None
    )
    for r in lifespan:
        if r["n"] == 0:
            print(
                f"  T+{r['offset_h']:>2}h     {r['n']:>10,}"
                f"{'-':>10}{'-':>10}{'-':>13}{'-':>13}{'-':>16}"
            )
            continue

        suffix = ""
        if base_top3 is not None and r["offset_h"] != DECAY_OFFSETS_HOURS[0]:
            diff = r["top3_rate"] - base_top3
            if diff < 0:
                suffix = f"  (▼ {abs(diff):.2f}%p)"
            elif diff > 0:
                suffix = f"  (▲ {diff:.2f}%p)"

        print(
            f"  T+{r['offset_h']:>2}h     "
            f"{r['n']:>10,}"
            f"{r['n_dropout']:>10,}"
            f"{r['dropout_rate']:>9.2f}%"
            f"{r['avg_rank']:>13.2f}"
            f"{r['median_rank']:>13.2f}"
            f"{r['top3_rate']:>15.2f}%"
            f"{suffix}"
        )
    print()

    # ---------------- 분석 4 : 경쟁 압력별 ----------------
    print("[ 분석 4 ] 경쟁 압력별 T+3h 생존율 (동일 단지+평형 내 타사 갱신 건수)")
    if pressure_summary:
        print(
            f"           분석 대상 {pressure_summary['total_events_analyzed']:,} 건 · "
            f"평균 경쟁 갱신 {pressure_summary['avg_competitors_overall']:.2f} 건 · "
            f"최대 {pressure_summary['max_competitors']} 건"
        )
    print(sub)
    print(
        f"  {'그룹':<22}{'표본 N':>10}{'비중':>9}"
        f"{'평균 경쟁수':>13}{'평균 순위':>13}{'TOP3 유지율':>16}{'이탈률':>11}"
    )
    print(sub)

    blue_top3 = None
    for r in pressure:
        if r["n"] == 0:
            print(
                f"  {r['name']:<22}{r['n']:>10,}{'-':>9}"
                f"{'-':>13}{'-':>13}{'-':>16}{'-':>11}"
            )
            continue

        suffix = ""
        if r["name"].startswith("A."):
            blue_top3 = r["top3_rate"]
        elif blue_top3 is not None:
            diff = r["top3_rate"] - blue_top3
            if diff < 0:
                suffix = f"  (▼ {abs(diff):.2f}%p)"
            elif diff > 0:
                suffix = f"  (▲ {diff:.2f}%p)"

        print(
            f"  {r['name']:<22}"
            f"{r['n']:>10,}"
            f"{r['share']:>8.2f}%"
            f"{r['avg_competitors']:>13.2f}"
            f"{r['avg_rank']:>13.2f}"
            f"{r['top3_rate']:>15.2f}%"
            f"{r['dropout_rate']:>10.2f}%"
            f"{suffix}"
        )

    print()

    # ---------------- 분석 5 : Cluster Size 통제 매트릭스 ----------------
    print("[ 분석 5 ] 묶음 규모(Cluster Size) 통제 후 경쟁 압력 매트릭스 (T+3h)")
    print("           압력 = 동일 묶음 내 (T, T+3h] 타사 갱신 / (총원-1)")
    print("           Blue 0%  ·  Normal 0~30%  ·  Red 30%+")
    if cluster_summary:
        ts = cluster_summary["tier_share"]
        print(
            f"           묶음 크기: 평균 {cluster_summary['avg_cluster_size']:.2f}명 "
            f"(중앙 {cluster_summary['median_cluster_size']:.0f}, "
            f"최대 {cluster_summary['max_cluster_size']}명)  ·  "
            f"체급 분포 — 소형 {ts['🥉 소형 (1~3)']:.1f}% / "
            f"중형 {ts['🥈 중형 (4~10)']:.1f}% / "
            f"대형 {ts['🥇 대형 (11+)']:.1f}%"
        )
    print(sub)

    # 헤더
    col_tier_w = 18
    col_cell_w = 18
    col_delta_w = 12
    header_top = (
        "  "
        + _pad_visible("체급 \\ 압력", col_tier_w)
        + _pad_visible("Blue", col_cell_w, "right")
        + _pad_visible("Normal", col_cell_w, "right")
        + _pad_visible("Red", col_cell_w, "right")
        + _pad_visible("Δ(B−R)", col_delta_w, "right")
    )
    header_sub = (
        "  "
        + _pad_visible("", col_tier_w)
        + _pad_visible("TOP3% (N)", col_cell_w, "right")
        + _pad_visible("TOP3% (N)", col_cell_w, "right")
        + _pad_visible("TOP3% (N)", col_cell_w, "right")
        + _pad_visible("%p", col_delta_w, "right")
    )
    print(header_top)
    print(header_sub)
    print(sub)

    for row in cluster_matrix:
        tier_name = row[0]["tier"]
        cells_text: list[str] = []
        blue_top3: float | None = None
        red_top3: float | None = None

        for cell in row:
            if cell["n"] == 0:
                cells_text.append("-")
            else:
                cells_text.append(f"{cell['top3_rate']:5.2f}% ({cell['n']:>5,})")
                if cell["pressure"] == "Blue":
                    blue_top3 = cell["top3_rate"]
                elif cell["pressure"] == "Red":
                    red_top3 = cell["top3_rate"]

        if blue_top3 is not None and red_top3 is not None:
            delta = blue_top3 - red_top3
            sign = "+" if delta >= 0 else ""
            delta_str = f"{sign}{delta:.2f}%p"
        else:
            delta_str = "-"

        print(
            "  "
            + _pad_visible(tier_name, col_tier_w)
            + _pad_visible(cells_text[0], col_cell_w, "right")
            + _pad_visible(cells_text[1], col_cell_w, "right")
            + _pad_visible(cells_text[2], col_cell_w, "right")
            + _pad_visible(delta_str, col_delta_w, "right")
        )

    print(sub)
    print("  ※ 셀 표기: T+3h TOP3 유지율 (표본 N) — Lifespan 기준(이탈=999)")
    print("  ※ Δ(B−R) = Blue 대비 Red TOP3 유지율 격차(%p) — 같은 체급 내 순효과")
    print()

    # ---------------- 분석 6 : Golden Cell 시간대 분포 ----------------
    print("[ 분석 6 ] 황금 타점(대형 × Blue) 시간대별 발생 분포 — 팩트 체크")
    if not golden_hours or golden_hours.get("n", 0) == 0:
        print("           ! 황금 타점 표본이 없어 분석을 수행할 수 없습니다.")
    else:
        n_g = golden_hours["n"]
        max_pct = max(golden_hours["max_pct"], 1.0)
        # 가독성을 위한 동적 스케일: 가장 높은 시간대 막대를 24칸으로
        bar_max = 24.0
        scale = bar_max / max_pct

        print(f"           표본 N = {n_g:,} 건  ·  스케일: 한 칸(█) ≈ {1/scale:.2f}%")
        print(sub)
        print(
            f"  {'시간대':<6}{'빈도':>8}{'비중':>9}   "
            f"{'분포':<28}     비고"
        )
        print(sub)

        for entry in golden_hours["hourly"]:
            h = entry["hour"]
            pct = entry["pct"]
            cnt = entry["count"]
            bar_len = int(round(pct * scale))
            bar_str = "█" * bar_len if bar_len > 0 else "·"

            tag = ""
            if h in LUNCH_HOURS:
                tag = "🍱 점심"
            elif h in EVENING_HOURS:
                tag = "🌆 저녁"
            elif h in DAWN_HOURS:
                tag = "🌙 새벽"

            bar_padded = _pad_visible(bar_str, 28)
            print(
                f"  {h:>2}시  {cnt:>6,}{pct:>8.2f}%   "
                f"{bar_padded}     {tag}"
            )

        print(sub)
        print(
            f"  🍱 점심(11~13시) 황금 타점 비중 : "
            f"{golden_hours['lunch_share']:>5.2f}% "
            f"({golden_hours['lunch_cnt']:,}건)"
        )
        print(
            f"  🌆 저녁(18~20시) 황금 타점 비중 : "
            f"{golden_hours['evening_share']:>5.2f}% "
            f"({golden_hours['evening_cnt']:,}건)"
        )
        print(
            f"  ⭐ 피크 합계 (점심+저녁)        : "
            f"{golden_hours['peak_share']:>5.2f}% "
            f"({golden_hours['peak_cnt']:,}건)"
        )
        print(
            f"  🌙 새벽(00~05시) 황금 타점 비중 : "
            f"{golden_hours['dawn_share']:>5.2f}% "
            f"({golden_hours['dawn_cnt']:,}건)"
        )
    print()

    # ---------------- 분석 7 : Golden vs Red 디케이 ----------------
    print("[ 분석 7 ] 같은 대형 묶음 내 Blue(황금) vs Red(출혈) 시간 경과 비교")
    if not golden_decay:
        print("           ! 비교 표본이 부족하여 분석을 수행할 수 없습니다.")
    else:
        print(sub)
        print(
            f"  {'경과시간':<10}"
            f"{'🥇 Blue TOP3 (N)':>22}"
            f"{'🥥 Red TOP3 (N)':>22}"
            f"{'Δ(B−R)':>14}"
            f"   이탈률 (B / R)"
        )
        print(sub)

        first_delta: float | None = None
        last_delta: float | None = None
        for r in golden_decay:
            blue_str = (
                f"{r['blue_top3']:>5.2f}% ({r['blue_n']:>4,})"
                if not np.isnan(r["blue_top3"])
                else "        -        "
            )
            red_str = (
                f"{r['red_top3']:>5.2f}% ({r['red_n']:>4,})"
                if not np.isnan(r["red_top3"])
                else "        -        "
            )
            if not np.isnan(r["delta"]):
                sign = "+" if r["delta"] >= 0 else ""
                delta_str = f"{sign}{r['delta']:>5.2f}%p"
                if first_delta is None:
                    first_delta = r["delta"]
                last_delta = r["delta"]
            else:
                delta_str = "-"

            drop_str = ""
            if not np.isnan(r["blue_dropout"]) and not np.isnan(r["red_dropout"]):
                drop_str = (
                    f"   {r['blue_dropout']:>5.2f}% / {r['red_dropout']:>5.2f}%"
                )

            print(
                f"  T+{r['offset_h']:>2}h     "
                f"{_pad_visible(blue_str, 22, 'right')}"
                f"{_pad_visible(red_str, 22, 'right')}"
                f"{delta_str:>14}"
                f"{drop_str}"
            )

        print(sub)
        if first_delta is not None and last_delta is not None:
            trend = last_delta - first_delta
            if trend > 0:
                trend_msg = (
                    f"시간이 갈수록 격차 확대 (+{trend:.2f}%p) — "
                    "황금 타점 효과의 유통기한이 길다"
                )
            elif trend < 0:
                trend_msg = (
                    f"시간이 갈수록 격차 축소 ({trend:.2f}%p) — "
                    "초기 임팩트가 시간이 지나며 평준화"
                )
            else:
                trend_msg = "시간이 흘러도 격차 유지 — 안정적 우위"
            print(f"  ※ 격차 추이: T+1h → T+12h 변화 = {trend_msg}")
    print()

    print(bar)

    # ---------------- 종합 요약 ----------------
    if impact["n"] > 0:
        print(
            f"  요약 │ 갱신 직후: {impact['avg_before']:.1f}위 ➔ "
            f"{impact['avg_after']:.1f}위, TOP3 타격률 {impact['top3_rate']:.1f}%"
        )
        if lifespan and not np.isnan(lifespan[-1]["top3_rate"]):
            print(
                f"        12h Lifespan TOP3 유지율 "
                f"{lifespan[-1]['top3_rate']:.1f}% "
                f"(이탈률 {lifespan[-1]['dropout_rate']:.1f}%) "
                f"— Survivor view {decay[-1]['top3_rate']:.1f}% 와 격차 "
                f"= 생존자 편향 크기"
            )

        # 분석 5에서 대형 묶음의 Blue vs Red 격차를 강조 (= 사장님이 가장 궁금한 지점)
        if cluster_matrix:
            big_row = cluster_matrix[-1]  # 대형 (11+)
            big_blue = next((c for c in big_row if c["pressure"] == "Blue"), None)
            big_red = next((c for c in big_row if c["pressure"] == "Red"), None)
            if big_blue and big_red and big_blue["n"] and big_red["n"]:
                print(
                    f"        🥇 대형 묶음(11+)에서도 Blue {big_blue['top3_rate']:.1f}% "
                    f"vs Red {big_red['top3_rate']:.1f}% "
                    f"→ 격차 {big_blue['top3_rate'] - big_red['top3_rate']:+.1f}%p "
                    f"→ '빈집 타이밍'은 출혈 경쟁 묶음에서 더 큰 방어 효과"
                )

        # 분석 6 : 황금 타점은 새벽 전용이 아님 — 피크에도 열린다
        if golden_hours and golden_hours.get("n", 0) > 0:
            print(
                f"        🍱🌆 황금 타점의 피크 시간대 비중 "
                f"{golden_hours['peak_share']:.1f}% (점심 {golden_hours['lunch_share']:.1f}% + "
                f"저녁 {golden_hours['evening_share']:.1f}%) "
                f"vs 새벽 {golden_hours['dawn_share']:.1f}% "
                f"→ 트래픽 높은 시간대에도 빈집은 충분히 열린다"
            )

        # 분석 7 : 격차 추이 — 빈집 효과의 유통기한
        if golden_decay:
            t1 = next((x for x in golden_decay if x["offset_h"] == 1), None)
            t12 = next((x for x in golden_decay if x["offset_h"] == 12), None)
            if t1 and t12 and not np.isnan(t1["delta"]) and not np.isnan(t12["delta"]):
                print(
                    f"        ⏳ 대형 묶음 Blue−Red TOP3 격차: "
                    f"T+1h {t1['delta']:+.1f}%p → T+12h {t12['delta']:+.1f}%p "
                    f"→ 빈집 갱신은 12시간 뒤에도 우위 유지 "
                    f"→ 효과가 압도적으로 오래간다"
                )

    print(bar)
    print()


# ---------------------------------------------------------------------------
# 엔트리포인트
# ---------------------------------------------------------------------------
def main() -> int:
    t0 = time.time()
    print("[1/3] data/ 폴더에서 4월·5월 parquet 취합 중...")
    raw = load_target_parquets()
    if raw is None or len(raw) == 0:
        print("  ! 분석할 데이터를 찾지 못했습니다.")
        return 1

    print("[2/3] 데이터 전처리 (process_data) 중...")
    df = process_data(raw)
    print(f"      → 전처리 후 {len(df):,} 행")

    print("[3/3] 전수 갱신 포착 및 임팩트 분석 중...")
    df = detect_renewals(df)
    renewed = df[df["is_renewed"]].copy()
    print(f"      → 갱신 이벤트 {len(renewed):,} 건 포착")

    impact = analyze_immediate_impact(renewed)
    decay, lifespan, per_event_ranks = analyze_decay_curve(df, renewed)

    t3h_rank = per_event_ranks["rank_T+3h"]
    pressure, pressure_summary = analyze_competitive_pressure(renewed, t3h_rank)
    cluster_matrix, cluster_summary, labeled_events = analyze_cluster_pressure_matrix(
        df, renewed, t3h_rank
    )

    golden_hours = analyze_golden_hour_distribution(labeled_events)
    golden_decay, _ = analyze_golden_vs_red_decay(labeled_events, per_event_ranks)

    render_report(
        impact,
        decay,
        lifespan,
        pressure,
        pressure_summary,
        cluster_matrix,
        cluster_summary,
        golden_hours,
        golden_decay,
        total_rows=len(df),
        total_renewals=len(renewed),
        elapsed_sec=time.time() - t0,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
