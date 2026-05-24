# -*- coding: utf-8 -*-
"""
학맞통 AI 교사용 의사결정 보조 프로토타입 v2

실행:
    streamlit run hakmatch_streamlit_app.py

이번 버전 반영 사항:
- 접속 첫 화면: 담임교사 대시보드
- 상단 역할 전환: 담임교사 / 학생맞춤통합지원담당교원
- 담임교사: 본인 반 학생만 조회
- 학생맞춤통합지원담당교원: 전교 학생 상태 조회
- 학교 정보 DB CSV 연결
- 1차 체크리스트 입력 → 점수 계산 → 맥락 보정 → Red Flag 확인
  → 심층 유도 분석 활성화 → 상담지 생성 고려 영역 산출
  → 다음 단계 LLM 입력 payload 미리보기

주의:
- 이 코드는 발표·시연용 MVP입니다.
- 실제 학생 개인정보, 실제 학교명, 민감 정보는 넣지 마세요.
- 실제 LLM API 호출, RAG, 벡터DB, 기관 검색, 협의록 생성은 구현하지 않았습니다.
"""

from __future__ import annotations

import io
import json
import math
from datetime import date
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import pandas as pd
import streamlit as st

try:
    import plotly.express as px
except Exception:
    px = None

# -----------------------------------------------------------------------------
# 기본 설정
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="학맞통 AI | 교사용 지원 신호 대시보드",
    page_icon="🧭",
    layout="wide",
    initial_sidebar_state="expanded",
)

APP_DIR = Path(__file__).resolve().parent
DATA_DIR = APP_DIR / "data"

# 파일 경로는 여기만 바꾸면 됩니다.
CSV_PATHS = {
    "school_info": [
        DATA_DIR / "02_school_info_db_location.csv",
        DATA_DIR / "05_school_info_db_location.csv",
        APP_DIR / "02_school_info_db_location.csv",
        APP_DIR / "05_school_info_db_location.csv",
    ],
    "school_context": [
        DATA_DIR / "02_school_context_scores_db.csv",
        APP_DIR / "02_school_context_scores_db.csv",
    ],
    "region_context": [
        DATA_DIR / "서울_학생지원맥락_영역별점수.csv",
        APP_DIR / "서울_학생지원맥락_영역별점수.csv",
    ],
    "checklist": [
        DATA_DIR / "first_checklist_items_v1.csv",
        APP_DIR / "first_checklist_items_v1.csv",
    ],
    "deep_rules": [
        DATA_DIR / "deep_inference_rules_v1.csv",
        APP_DIR / "deep_inference_rules_v1.csv",
    ],
    "rule_map": [
        DATA_DIR / "checklist_item_deep_rule_map_v1.csv",
        APP_DIR / "checklist_item_deep_rule_map_v1.csv",
    ],
}

# 기존 코드 변수명이 다를 때 이곳만 맞추면 됩니다.
SCHOOL_CONTEXT_VAR_NAME = "selected_school_context"
REGION_CONTEXT_VAR_NAME = "selected_region_context"

SUPPORT_AREAS = ["학업", "심리정서", "복지경제", "진로"]
AREA_TO_SCHOOL_CONTEXT_COL = {
    "학업": "학교_학습점수",
    "심리정서": "학교_정서심리점수",
    "복지경제": "학교_경제복지점수",
    "진로": "학교_진로점수",
}
AREA_TO_REGION_CONTEXT_COL = {
    "학업": "지역_학습점수",
    "심리정서": "지역_정서심리점수",
    "복지경제": "지역_경제복지점수",
    "진로": "지역_진로점수",
}

STATUS_ORDER = ["심층 파악 필요", "주의 및 탐색", "일상적 관찰"]
ROLE_HOMEROOM = "담임교사"
ROLE_COORDINATOR = "학생맞춤통합지원담당교원"
DEFAULT_GRADE = "2학년"
DEFAULT_CLASS = "3반"

# -----------------------------------------------------------------------------
# CSS
# -----------------------------------------------------------------------------
def inject_css() -> None:
    st.markdown(
        """
        <style>
        :root {
            --blue: #2f6bff;
            --deep-blue: #0b2a55;
            --navy: #111927;
            --line: #d8dee9;
            --muted: #64748b;
            --bg: #f4f7fb;
            --soft-blue: #eef4ff;
            --green: #14a36f;
            --orange: #f59e0b;
            --red: #ef4444;
            --purple: #7c3aed;
        }
        .stApp { background: var(--bg); }
        section[data-testid="stSidebar"] {
            background: #ffffff;
            border-right: 1px solid #d6dbe6;
        }
        section[data-testid="stSidebar"] .block-container { padding-top: 1rem; }
        .edutop {
            display: flex;
            align-items: stretch;
            justify-content: space-between;
            border: 1px solid #cbd5e1;
            background: #ffffff;
            margin: -0.5rem 0 0.8rem 0;
            min-height: 74px;
        }
        .edu-logo {
            width: 210px;
            display: flex;
            align-items: center;
            gap: 10px;
            padding: 12px 16px;
            border-right: 1px solid #cbd5e1;
            font-weight: 900;
            color: #0f172a;
        }
        .edu-symbol {
            width: 34px;
            height: 34px;
            border-radius: 50%;
            background: linear-gradient(135deg, #2f6bff, #00a884);
            display: inline-flex;
            align-items: center;
            justify-content: center;
            color: white;
            font-size: 18px;
        }
        .edu-main { flex: 1; }
        .edu-bluebar {
            height: 34px;
            background: var(--blue);
            color: white;
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 0 12px;
            font-size: 0.88rem;
        }
        .edu-school-badge {
            background: rgba(255,255,255,0.18);
            border: 1px solid rgba(255,255,255,0.35);
            border-radius: 4px;
            padding: 3px 8px;
            font-weight: 800;
            margin-right: 8px;
        }
        .edu-actions span {
            border: 1px solid rgba(255,255,255,0.7);
            border-radius: 3px;
            padding: 3px 8px;
            margin-left: 5px;
            background: #ffffff;
            color: #0f172a;
            font-weight: 800;
        }
        .rolebar {
            min-height: 40px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 12px;
            padding: 0 18px;
            font-weight: 800;
            color: #0f2a50;
            border-top: 1px solid #cbd5e1;
            background: #ffffff;
        }
        .role-pill {
            display: inline-block;
            border-radius: 999px;
            padding: 5px 10px;
            background: #eef4ff;
            border: 1px solid #bfdbfe;
            color: #1d4ed8;
            font-size: .82rem;
        }
        .page-title {
            font-size: 1.35rem;
            font-weight: 900;
            color: #0f172a;
            margin: 0.3rem 0 0.2rem 0;
        }
        .page-subtitle {
            font-size: 0.92rem;
            color: #64748b;
            margin-bottom: 0.8rem;
        }
        .panel {
            background: #ffffff;
            border: 1px solid #dbe2ef;
            border-radius: 10px;
            padding: 16px;
            box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
            margin-bottom: 12px;
        }
        .panel-title {
            font-weight: 900;
            color: #0f2a50;
            margin-bottom: 10px;
            display: flex;
            align-items: center;
            gap: 6px;
        }
        .panel-title::before {
            content: '';
            display: inline-block;
            width: 5px;
            height: 18px;
            border-radius: 4px;
            background: var(--blue);
        }
        .metric-card {
            background: #ffffff;
            border: 1px solid #dbe2ef;
            border-radius: 12px;
            padding: 16px 16px 14px 16px;
            box-shadow: 0 1px 3px rgba(15,23,42,0.05);
            min-height: 112px;
        }
        .metric-label {
            font-size: 0.82rem;
            color: #64748b;
            font-weight: 800;
            margin-bottom: 8px;
        }
        .metric-value {
            font-size: 1.85rem;
            line-height: 1.1;
            color: #0f172a;
            font-weight: 900;
        }
        .metric-help {
            font-size: 0.75rem;
            color: #94a3b8;
            margin-top: 8px;
        }
        .student-card {
            border: 1px solid #dbe2ef;
            background: #ffffff;
            border-radius: 12px;
            padding: 14px 16px;
            margin-bottom: 10px;
            box-shadow: 0 1px 2px rgba(15,23,42,0.04);
        }
        .risk-deep { border-left: 8px solid var(--red); background: #fff7f7; }
        .risk-watch { border-left: 8px solid var(--orange); background: #fffaf0; }
        .risk-normal { border-left: 8px solid #94a3b8; }
        .badge {
            display: inline-block;
            border-radius: 999px;
            padding: 3px 9px;
            font-weight: 900;
            font-size: 0.78rem;
            margin-right: 5px;
            border: 1px solid transparent;
        }
        .badge-deep { background: #fee2e2; color: #b91c1c; border-color: #fecaca; }
        .badge-watch { background: #ffedd5; color: #c2410c; border-color: #fed7aa; }
        .badge-normal { background: #f1f5f9; color: #475569; border-color: #e2e8f0; }
        .mini-grid {
            display: grid;
            grid-template-columns: repeat(4, minmax(80px, 1fr));
            gap: 7px;
            margin-top: 10px;
        }
        .mini-domain {
            background: #f8fafc;
            border: 1px solid #e2e8f0;
            border-radius: 8px;
            padding: 7px;
        }
        .domain-name { font-size: 0.72rem; color: #64748b; font-weight: 800; margin-bottom: 4px; }
        .dots { letter-spacing: 1px; color: #2563eb; font-weight: 900; }
        .dots-zero { color: #cbd5e1; }
        .info-table {
            width: 100%;
            border-collapse: collapse;
            font-size: 0.86rem;
        }
        .info-table th {
            background: #f1f5f9;
            color: #0f2a50;
            text-align: left;
            padding: 9px;
            border: 1px solid #dbe2ef;
        }
        .info-table td {
            padding: 9px;
            border: 1px solid #dbe2ef;
            vertical-align: top;
        }
        .small-muted { color: #64748b; font-size: 0.84rem; }
        .recommend-card {
            background: #ffffff;
            border: 1px solid #dbe2ef;
            border-radius: 12px;
            padding: 14px 16px;
            margin-bottom: 10px;
        }
        .recommend-rank {
            display: inline-flex;
            width: 25px;
            height: 25px;
            border-radius: 50%;
            align-items: center;
            justify-content: center;
            background: var(--deep-blue);
            color: white;
            font-weight: 900;
            margin-right: 8px;
        }
        .callout {
            padding: 12px 14px;
            border-radius: 10px;
            border: 1px solid #bfdbfe;
            background: #eff6ff;
            color: #0f2a50;
            margin-bottom: 10px;
        }
        .warning-callout {
            padding: 12px 14px;
            border-radius: 10px;
            border: 1px solid #fecaca;
            background: #fff7f7;
            color: #7f1d1d;
            margin-bottom: 10px;
        }
        .footer-note {
            color: #64748b;
            font-size: 0.82rem;
            border-top: 1px solid #e2e8f0;
            padding-top: 10px;
            margin-top: 18px;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

# -----------------------------------------------------------------------------
# 공통 로더
# -----------------------------------------------------------------------------
def first_existing_path(paths: Iterable[Path]) -> Optional[Path]:
    for path in paths:
        if path.exists():
            return path
    return None


def load_csv_with_fallback(path: Path | str) -> pd.DataFrame:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(str(path))
    try:
        return pd.read_csv(path, encoding="utf-8-sig")
    except UnicodeDecodeError:
        return pd.read_csv(path, encoding="cp949")


def load_optional_csv(paths: Iterable[Path], name: str) -> Tuple[Optional[pd.DataFrame], Optional[Path], Optional[str]]:
    path = first_existing_path(paths)
    if path is None:
        return None, None, f"{name} 파일을 찾을 수 없습니다. 확인한 경로: " + ", ".join(str(p) for p in paths)
    try:
        return load_csv_with_fallback(path), path, None
    except Exception as e:
        return None, path, f"{path.name} 읽기 실패: {e}"


def get_cell(row: Optional[pd.Series | Dict[str, Any]], col: str, default: float = 0.0) -> float:
    if row is None:
        return default
    try:
        value = row[col]
    except Exception:
        return default
    try:
        if pd.isna(value):
            return default
    except Exception:
        pass
    try:
        return float(value)
    except Exception:
        return default


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    return str(value).strip()


def normalize_area_name(value: str) -> str:
    value = normalize_text(value)
    mapping = {
        "학습": "학업",
        "학습지원": "학업",
        "학습·진로": "학업",
        "학업진로": "학업",
        "정서": "심리정서",
        "심리": "심리정서",
        "심리·정서": "심리정서",
        "심리정서지원": "심리정서",
        "복지": "복지경제",
        "경제": "복지경제",
        "복지·경제": "복지경제",
        "환경": "복지경제",
        "건강·안전": "심리정서",
        "교사관계": "심리정서",
    }
    return mapping.get(value, value)


def normalize_area_list(value: Any) -> List[str]:
    if value is None:
        return []
    text = normalize_text(value)
    if not text:
        return []
    for sep in [",", ";", "/", "·"]:
        text = text.replace(sep, "|")
    parts = [normalize_area_name(x.strip()) for x in text.split("|") if x.strip()]
    result: List[str] = []
    for p in parts:
        if p not in result:
            result.append(p)
    return result

# -----------------------------------------------------------------------------
# 학교 DB 연결
# -----------------------------------------------------------------------------
def load_school_databases() -> Dict[str, Any]:
    school_info_df, school_info_path, school_info_err = load_optional_csv(CSV_PATHS["school_info"], "학교 정보 DB")
    school_context_df, school_context_path, school_context_err = load_optional_csv(CSV_PATHS["school_context"], "학교 맥락 점수 DB")
    region_context_df, region_context_path, region_context_err = load_optional_csv(CSV_PATHS["region_context"], "지역 맥락 점수 DB")

    errors = [x for x in [school_info_err, school_context_err, region_context_err] if x]

    if school_info_df is None:
        school_info_df = pd.DataFrame(
            [
                {
                    "자치구": "강서구",
                    "교육지원청": "강서양천교육지원청",
                    "학교급": "고등학교",
                    "학교명": "데모고등학교",
                    "학교_주소": "서울특별시 강서구",
                    "학교_학생수": 600,
                    "학교_교원1인당학생수": 12.0,
                    "교육복지우선지원여부_UI": "해당 없음",
                    "위클래스_있음": "있음",
                    "전문상담교사_수": 1,
                    "보건교사_수": 1,
                    "진로상담실_있음": "있음",
                }
            ]
        )
    return {
        "school_info_df": school_info_df,
        "school_context_df": school_context_df,
        "region_context_df": region_context_df,
        "paths": {
            "school_info": school_info_path,
            "school_context": school_context_path,
            "region_context": region_context_path,
        },
        "errors": errors,
    }


def find_matching_row(df: Optional[pd.DataFrame], school_name: str, district: Optional[str] = None) -> Optional[pd.Series]:
    if df is None or df.empty or "학교명" not in df.columns:
        return None
    matched = df[df["학교명"].astype(str) == str(school_name)]
    if district and "자치구" in df.columns:
        matched2 = matched[matched["자치구"].astype(str) == str(district)]
        if not matched2.empty:
            matched = matched2
    if matched.empty:
        return None
    return matched.iloc[0]


def find_region_row(df: Optional[pd.DataFrame], district: str) -> Optional[pd.Series]:
    if df is None or df.empty or "자치구" not in df.columns:
        return None
    matched = df[df["자치구"].astype(str) == str(district)]
    if matched.empty:
        return None
    return matched.iloc[0]


def school_row_to_dict(row: pd.Series) -> Dict[str, Any]:
    def yes(v: Any) -> bool:
        return normalize_text(v) in ["있음", "Y", "예", "1", "True", "true", "해당"]

    return {
        "자치구": normalize_text(row.get("자치구", "")),
        "교육지원청": normalize_text(row.get("교육지원청", "")),
        "학교급": normalize_text(row.get("학교급", "")),
        "학교명": normalize_text(row.get("학교명", "")),
        "학교_주소": normalize_text(row.get("학교_주소", "")),
        "대표_전화번호": normalize_text(row.get("대표_전화번호", "")),
        "홈페이지_URL": normalize_text(row.get("홈페이지_URL", "")),
        "학교_학생수": get_cell(row, "학교_학생수", 0),
        "학교_교원1인당학생수": get_cell(row, "학교_교원1인당학생수", 0),
        "교육복지우선지원여부_UI": normalize_text(row.get("교육복지우선지원여부_UI", "")),
        "위클래스_있음": yes(row.get("위클래스_있음", "")),
        "전문상담교사_수": int(get_cell(row, "전문상담교사_수", 0)),
        "보건교사_수": int(get_cell(row, "보건교사_수", 0)),
        "진로상담실_있음": yes(row.get("진로상담실_있음", "")),
        "방과후교과프로그램수": get_cell(row, "방과후교과프로그램수", 0),
        "방과후특기적성프로그램수": get_cell(row, "방과후특기적성프로그램수", 0),
    }

# -----------------------------------------------------------------------------
# 학생 데모 데이터
# -----------------------------------------------------------------------------
def classify_action_stage(raw_score: int, red_flag_result: Dict[str, Any]) -> Dict[str, str]:
    if raw_score <= 3:
        score_based_stage = "일상적 관찰"
        score_based_action = "현재 유지"
    elif raw_score <= 7:
        score_based_stage = "주의 및 탐색"
        score_based_action = "교사 면담 및 가벼운 개입"
    else:
        score_based_stage = "심층 파악 필요"
        score_based_action = "2차 상담 질문 활성화 및 전문 상담 검토"

    if red_flag_result.get("urgent_flag"):
        final_action_stage = "심층 파악 필요"
        final_action = "2차 상담 질문 활성화 및 긴급 확인 질문 포함"
    else:
        final_action_stage = score_based_stage
        final_action = score_based_action

    return {
        "score_based_stage": score_based_stage,
        "score_based_action": score_based_action,
        "final_action_stage": final_action_stage,
        "final_action": final_action,
    }


def generate_demo_students(school_name: str) -> pd.DataFrame:
    rows: List[Dict[str, Any]] = []
    patterns = [
        ("일상적 관찰", [0, 0, 0, 0], "특이 신호 없음", False),
        ("주의 및 탐색", [2, 1, 0, 0], "수업 중 무기력, 과제 수행 부족", False),
        ("심층 파악 필요", [1, 4, 1, 0], "또래관계 단절, 우울 표현, 결석 증가", True),
        ("주의 및 탐색", [0, 1, 2, 0], "복장·위생 상태 우려, 돌봄 공백 가능성", False),
        ("심층 파악 필요", [3, 1, 2, 1], "학업 의지 저하, 경제적 어려움, 진로 무기력", False),
        ("주의 및 탐색", [0, 2, 0, 1], "불안 표현, 진로 결정 회피", False),
        ("일상적 관찰", [1, 0, 0, 0], "일시적 과제 미제출", False),
        ("주의 및 탐색", [1, 0, 0, 2], "진로 목표 부재, 활동 참여 저하", False),
    ]
    idx = 1
    for grade in ["1학년", "2학년", "3학년"]:
        for klass in ["1반", "2반", "3반", "4반"]:
            for n in range(1, 9):
                stage, scores, signal, urgent = patterns[(idx + n) % len(patterns)]
                raw_like = sum(scores)
                if urgent:
                    final_stage = "심층 파악 필요"
                elif raw_like >= 5:
                    final_stage = "심층 파악 필요"
                elif raw_like >= 2:
                    final_stage = "주의 및 탐색"
                else:
                    final_stage = "일상적 관찰"
                rows.append(
                    {
                        "학생코드": f"S-{idx:03d}",
                        "이름": f"학생 {idx:03d}",
                        "학교명": school_name,
                        "학년": grade,
                        "반": klass,
                        "학업": scores[0],
                        "심리정서": scores[1],
                        "복지경제": scores[2],
                        "진로": scores[3],
                        "RedFlag": urgent,
                        "주요신호": signal,
                        "최종단계": final_stage,
                        "권장Action": "2차 상담 질문 활성화 및 전문 상담 검토" if final_stage == "심층 파악 필요" else ("교사 면담 및 가벼운 개입" if final_stage == "주의 및 탐색" else "현재 유지"),
                        "담당자": "담임교사" if klass == DEFAULT_CLASS else "학맞통 담당",
                        "기한": str(date.today()) if final_stage != "일상적 관찰" else "-",
                    }
                )
                idx += 1
    return pd.DataFrame(rows)


def get_view_students() -> pd.DataFrame:
    df = st.session_state.students.copy()
    role = st.session_state.role
    if role == ROLE_HOMEROOM:
        df = df[(df["학년"] == st.session_state.homeroom_grade) & (df["반"] == st.session_state.homeroom_class)]
    return df.reset_index(drop=True)

# -----------------------------------------------------------------------------
# 체크리스트 계산 함수
# -----------------------------------------------------------------------------
def get_active_items_df() -> pd.DataFrame:
    items_df = st.session_state.get("checklist_items_df")
    if items_df is None or items_df.empty:
        return pd.DataFrame()
    df = items_df.copy()
    if "active" in df.columns:
        df = df[df["active"].astype(str).str.upper().str.strip() == "Y"]
    for col in ["domain_order", "item_order"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(999)
    sort_cols = [c for c in ["domain_order", "item_order"] if c in df.columns]
    if sort_cols:
        df = df.sort_values(sort_cols)
    return df.reset_index(drop=True)


def calculate_checklist_scores(items_df: pd.DataFrame, responses: Dict[str, int]) -> Dict[str, Any]:
    active_df = items_df.copy()
    if "active" in active_df.columns:
        active_df = active_df[active_df["active"].astype(str).str.upper().str.strip() == "Y"]

    domain_rows: List[Dict[str, Any]] = []
    for domain in SUPPORT_AREAS:
        sub = active_df[active_df["domain"].map(normalize_area_name) == domain]
        raw = int(sum(int(responses.get(str(row["item_id"]), 0)) for _, row in sub.iterrows()))
        max_score = int(len(sub) * 2)
        scaled = round(raw / max_score * 100, 1) if max_score > 0 else 0.0
        domain_rows.append(
            {
                "지원 영역": domain,
                "domain_raw_score": raw,
                "domain_max_score": max_score,
                "domain_scaled_score": scaled,
            }
        )

    student_raw_score = int(sum(int(v) for k, v in responses.items() if not str(k).startswith("_")))
    student_scaled_score = int(student_raw_score * 5)
    domain_scores = pd.DataFrame(domain_rows)
    primary_areas = get_primary_areas(domain_scores)
    return {
        "student_raw_score": student_raw_score,
        "student_scaled_score": student_scaled_score,
        "domain_scores": domain_scores,
        "primary_areas": primary_areas,
    }


def get_primary_areas(domain_scores: pd.DataFrame) -> List[str]:
    if domain_scores is None or domain_scores.empty:
        return ["현재 뚜렷한 우선 영역 없음"]
    max_score = float(domain_scores["domain_scaled_score"].max())
    if max_score <= 0:
        return ["현재 뚜렷한 우선 영역 없음"]
    return domain_scores.loc[domain_scores["domain_scaled_score"] == max_score, "지원 영역"].tolist()


def detect_red_flags(items_df: pd.DataFrame, responses: Dict[str, int]) -> Dict[str, Any]:
    urgent_items: List[Dict[str, Any]] = []
    for _, row in items_df.iterrows():
        item_id = normalize_text(row.get("item_id"))
        item_code = normalize_text(row.get("item_code"))
        score = int(responses.get(item_id, 0))
        is_red = item_code in ["정서-C", "환경-A"] or item_id in ["EMO_C", "ENV_A"]
        if is_red and score >= 1:
            if item_code == "정서-C" or item_id == "EMO_C":
                mapped_area = "심리정서"
            elif item_code == "환경-A" or item_id == "ENV_A":
                mapped_area = "복지경제"
            else:
                mapped_area = normalize_area_name(row.get("domain", ""))
            urgent_items.append(
                {
                    "item_id": item_id,
                    "item_code": item_code,
                    "item_text": normalize_text(row.get("item_text")),
                    "score": score,
                    "area": mapped_area,
                    "reason": "우선 확인 필요 신호",
                }
            )
    return {
        "urgent_flag": bool(urgent_items),
        "urgent_flag_items": urgent_items,
    }


def parse_rule_ids(value: Any) -> List[str]:
    text = normalize_text(value)
    if not text:
        return []
    for sep in [",", ";", "/"]:
        text = text.replace(sep, "|")
    return [x.strip() for x in text.split("|") if x.strip()]


def row_get_flexible(row: pd.Series, candidates: List[str], default: str = "") -> str:
    for c in candidates:
        if c in row.index:
            value = normalize_text(row.get(c))
            if value:
                return value
    return default


def activate_deep_rules(
    responses: Dict[str, int],
    rule_map_df: Optional[pd.DataFrame],
    deep_rules_df: Optional[pd.DataFrame],
) -> List[Dict[str, Any]]:
    if rule_map_df is None or deep_rules_df is None or rule_map_df.empty or deep_rules_df.empty:
        return []

    if "rule_id" not in deep_rules_df.columns:
        return []

    active_items = {item_id for item_id, score in responses.items() if not str(item_id).startswith("_") and int(score) >= 1}
    active_rule_ids: Dict[str, str] = {}

    # 매핑 파일 기반 활성화
    for _, row in rule_map_df.iterrows():
        item_id = normalize_text(row.get("item_id"))
        item_code = normalize_text(row.get("item_code"))
        related = []
        if "rule_id" in row.index:
            related.extend(parse_rule_ids(row.get("rule_id")))
        if "related_rule_ids" in row.index:
            related.extend(parse_rule_ids(row.get("related_rule_ids")))
        threshold = 1
        if "activation_threshold" in row.index:
            try:
                threshold = int(float(row.get("activation_threshold")))
            except Exception:
                threshold = 1
        item_score = int(responses.get(item_id, 0))
        if item_score >= threshold:
            for rid in related:
                active_rule_ids[rid] = "single"
        if item_code:
            for resp_item_id, resp_score in responses.items():
                if int(resp_score) >= threshold and resp_item_id == item_id:
                    for rid in related:
                        active_rule_ids[rid] = "single"

    # 규칙 파일의 trigger_items 기반 활성화, 복합 규칙 포함
    for _, rule in deep_rules_df.iterrows():
        rid = normalize_text(rule.get("rule_id"))
        trigger_items = parse_rule_ids(rule.get("trigger_items"))
        if not trigger_items:
            continue
        checked_count = sum(1 for item in trigger_items if int(responses.get(item, 0)) >= 1)
        if checked_count == 0:
            continue
        if len(trigger_items) >= 2:
            activation_type = "full_combo" if checked_count == len(trigger_items) else "partial_combo"
        else:
            activation_type = "single"
        previous = active_rule_ids.get(rid)
        if previous == "full_combo":
            continue
        active_rule_ids[rid] = activation_type

    result: List[Dict[str, Any]] = []
    for rid, activation_type in active_rule_ids.items():
        matched = deep_rules_df[deep_rules_df["rule_id"].astype(str) == rid]
        if matched.empty:
            continue
        row = matched.iloc[0]
        rule_title = row_get_flexible(row, ["rule_title", "rule_name"], rid)
        possible_hidden = row_get_flexible(row, ["possible_hidden_factors", "possible_underlying_factors"], "")
        linked_areas = normalize_area_list(row.get("linked_areas"))
        counseling_question_areas = normalize_area_list(row.get("counseling_question_areas"))
        result.append(
            {
                "rule_id": rid,
                "rule_title": rule_title,
                "activation_type": activation_type,
                "surface_signal": row_get_flexible(row, ["surface_signal"], ""),
                "possible_hidden_factors": possible_hidden,
                "deep_guidance_text": row_get_flexible(row, ["deep_guidance_text"], ""),
                "linked_areas": linked_areas,
                "counseling_question_areas": counseling_question_areas,
                "priority": row_get_flexible(row, ["priority"], ""),
                "is_urgent_related": row_get_flexible(row, ["is_urgent_related", "urgent_flag_related"], ""),
            }
        )
    type_order = {"full_combo": 0, "partial_combo": 1, "single": 2}
    result.sort(key=lambda x: (type_order.get(x.get("activation_type", "single"), 9), x.get("rule_id", "")))
    return result


def derive_counseling_consideration_areas(
    domain_scores: pd.DataFrame,
    responses: Dict[str, int],
    red_flag_result: Dict[str, Any],
    active_deep_rules: List[Dict[str, Any]],
    items_df: Optional[pd.DataFrame] = None,
) -> List[Dict[str, Any]]:
    focus: Dict[str, float] = {area: 0.0 for area in SUPPORT_AREAS}
    reasons: Dict[str, List[str]] = {area: [] for area in SUPPORT_AREAS}

    for _, row in domain_scores.iterrows():
        area = normalize_area_name(row["지원 영역"])
        scaled = float(row["domain_scaled_score"])
        if area in focus and scaled > 0:
            focus[area] += scaled * 0.5
            reasons[area].append(f"{area} 영역 1차 체크리스트 환산점수 {scaled:g}점")

    if items_df is not None and not items_df.empty:
        for _, row in items_df.iterrows():
            item_id = normalize_text(row.get("item_id"))
            score = int(responses.get(item_id, 0))
            area = normalize_area_name(row.get("domain"))
            if area in focus and score == 2:
                focus[area] += 10
                reasons[area].append(f"{normalize_text(row.get('item_code'))} 문항이 뚜렷하게 관찰됨")
            if area in focus and score >= 1:
                text = normalize_text(row.get("item_text"))
                code = normalize_text(row.get("item_code"))
                short = text[:28] + ("..." if len(text) > 28 else "")
                reasons[area].append(f"{code} 체크: {short}")

    for item in red_flag_result.get("urgent_flag_items", []):
        area = normalize_area_name(item.get("area"))
        if area in focus:
            focus[area] += 20
            reasons[area].append(f"{item.get('item_code')} 우선 확인 필요 신호")

    for rule in active_deep_rules:
        title = rule.get("rule_title", rule.get("rule_id", "심층 유도 분석"))
        for area in rule.get("linked_areas", []):
            area = normalize_area_name(area)
            if area in focus:
                focus[area] += 15
                reasons[area].append(f"심층 유도 분석 연결 영역: {title}")
        for area in rule.get("counseling_question_areas", []):
            area = normalize_area_name(area)
            if area in focus:
                focus[area] += 15
                reasons[area].append(f"상담 질문 생성 시 함께 확인 필요: {title}")

    result: List[Dict[str, Any]] = []
    for area, score in focus.items():
        if score <= 0:
            continue
        if score >= 60:
            level = "필수 확인"
        elif score >= 35:
            level = "함께 확인"
        else:
            level = "보조 확인"
        unique_reasons = []
        for r in reasons[area]:
            if r and r not in unique_reasons:
                unique_reasons.append(r)
        result.append(
            {
                "area": area,
                "focus_score": round(score, 1),
                "priority_level": level,
                "reasons": unique_reasons[:6],
            }
        )

    if red_flag_result.get("urgent_flag"):
        result.append(
            {
                "area": "긴급확인",
                "focus_score": 100,
                "priority_level": "필수 확인",
                "reasons": ["우선 확인 필요 신호가 포함되어 안전·정서·환경 확인 질문을 우선 포함"],
            }
        )

    level_order = {"필수 확인": 0, "함께 확인": 1, "보조 확인": 2}
    result.sort(key=lambda x: (level_order.get(x["priority_level"], 9), -float(x["focus_score"])))
    return result


def calculate_school_bonus(score: float, apply_context: bool) -> float:
    if not apply_context:
        return 0.0
    if score >= 90:
        return 10.0
    if score >= 75:
        return 7.0
    if score >= 50:
        return 3.0
    return 0.0


def calculate_region_bonus(score: float, apply_context: bool) -> float:
    if not apply_context:
        return 0.0
    if score >= 90:
        return 5.0
    if score >= 75:
        return 3.5
    if score >= 50:
        return 1.5
    return 0.0


def calculate_context_result(
    primary_areas: List[str],
    student_scaled_score: float,
    selected_school_context: Optional[pd.Series],
    selected_region_context: Optional[pd.Series],
) -> Dict[str, Any]:
    apply_context = student_scaled_score >= 40
    context_rows: List[Dict[str, Any]] = []
    usable_primary = [a for a in primary_areas if a in SUPPORT_AREAS]
    if not usable_primary:
        usable_primary = []

    best_school_bonus = 0.0
    best_region_bonus = 0.0
    best_school_score = 0.0
    best_region_score = 0.0
    applied_area = usable_primary[0] if usable_primary else "-"

    for area in SUPPORT_AREAS:
        school_score = get_cell(selected_school_context, AREA_TO_SCHOOL_CONTEXT_COL[area], 0)
        region_score = get_cell(selected_region_context, AREA_TO_REGION_CONTEXT_COL[area], 0)
        school_bonus = calculate_school_bonus(school_score, apply_context and (not usable_primary or area in usable_primary))
        region_bonus = calculate_region_bonus(region_score, apply_context and (not usable_primary or area in usable_primary))
        applied = "적용" if (school_bonus > 0 or region_bonus > 0) else ("대상 영역이나 보정 없음" if area in usable_primary else "미적용")
        context_rows.append(
            {
                "적용 영역": area,
                "학교 맥락 점수": round(school_score, 1),
                "학교 보정 점수": school_bonus,
                "지역 맥락 점수": round(region_score, 1),
                "지역 보정 점수": region_bonus,
                "적용 여부": applied,
            }
        )
        if area in usable_primary and (school_bonus + region_bonus) >= (best_school_bonus + best_region_bonus):
            best_school_bonus = school_bonus
            best_region_bonus = region_bonus
            best_school_score = school_score
            best_region_score = region_score
            applied_area = area

    if not apply_context:
        best_school_bonus = 0.0
        best_region_bonus = 0.0

    return {
        "apply_context": apply_context,
        "applied_area": applied_area,
        "school_context_score": round(best_school_score, 1),
        "region_context_score": round(best_region_score, 1),
        "school_context_bonus": best_school_bonus,
        "region_context_bonus": best_region_bonus,
        "final_priority_score": round(float(student_scaled_score) + best_school_bonus + best_region_bonus, 1),
        "context_table": pd.DataFrame(context_rows),
        "context_missing": selected_school_context is None or selected_region_context is None,
    }


def build_counseling_payload(
    first_check_result: Dict[str, Any],
    red_flag_result: Dict[str, Any],
    context_result: Dict[str, Any],
    active_deep_rules: List[Dict[str, Any]],
    counseling_consideration_areas: List[Dict[str, Any]],
    stage_result: Dict[str, str],
) -> Dict[str, Any]:
    domain_scores_payload = {}
    for _, row in first_check_result["domain_scores"].iterrows():
        area = row["지원 영역"]
        domain_scores_payload[area] = {
            "domain_raw_score": int(row["domain_raw_score"]),
            "domain_max_score": int(row["domain_max_score"]),
            "domain_scaled_score": float(row["domain_scaled_score"]),
        }

    payload = {
        "first_check_result": {
            "raw_score": int(first_check_result["student_raw_score"]),
            "scaled_score": int(first_check_result["student_scaled_score"]),
            "score_based_stage": stage_result["score_based_stage"],
            "final_action_stage": stage_result["final_action_stage"],
            "domain_scores": domain_scores_payload,
            "primary_areas": first_check_result["primary_areas"],
        },
        "red_flag_result": {
            "urgent_flag": bool(red_flag_result.get("urgent_flag", False)),
            "urgent_flag_items": red_flag_result.get("urgent_flag_items", []),
        },
        "context_result": {
            "applied_area": context_result.get("applied_area"),
            "school_context_score": context_result.get("school_context_score"),
            "region_context_score": context_result.get("region_context_score"),
            "school_context_bonus": context_result.get("school_context_bonus"),
            "region_context_bonus": context_result.get("region_context_bonus"),
            "final_priority_score": context_result.get("final_priority_score"),
        },
        "active_deep_rules": [
            {
                "rule_id": r.get("rule_id"),
                "rule_title": r.get("rule_title"),
                "activation_type": r.get("activation_type"),
                "surface_signal": r.get("surface_signal"),
                "possible_hidden_factors": r.get("possible_hidden_factors"),
                "deep_guidance_text": r.get("deep_guidance_text"),
                "linked_areas": r.get("linked_areas"),
            }
            for r in active_deep_rules
        ],
        "counseling_consideration_areas": counseling_consideration_areas,
        "instruction_for_next_step": "이 payload를 기반으로 교육청 체크리스트를 참고하여 2차 상담 질문을 생성한다.",
    }
    return payload

# -----------------------------------------------------------------------------
# 렌더링 함수
# -----------------------------------------------------------------------------
def render_header() -> None:
    school = st.session_state.selected_school_info
    role = st.session_state.role
    scope_text = f"{st.session_state.homeroom_grade} {st.session_state.homeroom_class}만 조회" if role == ROLE_HOMEROOM else "전교 학생 조회"
    st.markdown(
        f"""
        <div class="edutop">
            <div class="edu-logo">
                <span class="edu-symbol">학</span>
                <div>
                    <div>학맞통 AI</div>
                    <div style="font-size:.74rem;color:#64748b;font-weight:700;">교사용 지원 신호 포털</div>
                </div>
            </div>
            <div class="edu-main">
                <div class="edu-bluebar">
                    <div>
                        <span class="edu-school-badge">{school.get('학교명', '학교 미선택')}</span>
                        {school.get('교육지원청', '')} · {school.get('자치구', '')}
                    </div>
                    <div class="edu-actions">
                        <span>로그아웃</span><span>튜토리얼</span><span>사용자지원</span>
                    </div>
                </div>
                <div class="rolebar">
                    <div>현재 역할: <span class="role-pill">{role}</span></div>
                    <div class="small-muted">조회 범위: {scope_text}</div>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_role_switch() -> None:
    role = st.radio(
        "역할 전환",
        [ROLE_HOMEROOM, ROLE_COORDINATOR],
        index=[ROLE_HOMEROOM, ROLE_COORDINATOR].index(st.session_state.role),
        horizontal=True,
        help="담임교사는 본인 반 학생만, 학생맞춤통합지원담당교원은 전교 학생을 볼 수 있습니다.",
    )
    st.session_state.role = role


def render_page_title(title: str, subtitle: str) -> None:
    st.markdown(f"<div class='page-title'>{title}</div>", unsafe_allow_html=True)
    st.markdown(f"<div class='page-subtitle'>{subtitle}</div>", unsafe_allow_html=True)


def metric_card(label: str, value: str, help_text: str = "") -> str:
    return f"""
    <div class="metric-card">
        <div class="metric-label">{label}</div>
        <div class="metric-value">{value}</div>
        <div class="metric-help">{help_text}</div>
    </div>
    """


def stage_badge(stage: str) -> str:
    if stage == "심층 파악 필요":
        cls = "badge-deep"
    elif stage == "주의 및 탐색":
        cls = "badge-watch"
    else:
        cls = "badge-normal"
    return f"<span class='badge {cls}'>{stage}</span>"


def dots(score: int, max_score: int = 4) -> str:
    if score <= 0:
        return "<span class='dots dots-zero'>○○○○</span>"
    filled = "●" * min(score, max_score)
    empty = "○" * max(0, max_score - score)
    return f"<span class='dots'>{filled}<span class='dots-zero'>{empty}</span></span>"


def domain_grid(row: pd.Series) -> str:
    cells = "".join(
        f"""
        <div class="mini-domain">
            <div class="domain-name">{area}</div>
            {dots(int(row.get(area, 0)))}
        </div>
        """
        for area in SUPPORT_AREAS
    )
    return f"<div class='mini-grid'>{cells}</div>"


def render_student_card(row: pd.Series) -> None:
    stage = normalize_text(row.get("최종단계", "일상적 관찰"))
    cls = "risk-deep" if stage == "심층 파악 필요" else ("risk-watch" if stage == "주의 및 탐색" else "risk-normal")
    top_area = max(SUPPORT_AREAS, key=lambda a: int(row.get(a, 0)))
    if sum(int(row.get(a, 0)) for a in SUPPORT_AREAS) == 0:
        top_area = "-"
    st.markdown(
        f"""
        <div class="student-card {cls}">
            <div style="display:flex;justify-content:space-between;align-items:center;gap:10px;">
                <div style="font-weight:900;font-size:1.02rem;color:#0f172a;">
                    {stage_badge(stage)} {row.get('이름')} <span class="small-muted">({row.get('학생코드')})</span>
                </div>
                <div class="small-muted">{row.get('학년')} {row.get('반')} · 우선 영역: <span style="font-weight:900;">{top_area}</span></div>
            </div>
            {domain_grid(row)}
            <div style="margin-top:10px;color:#334155;font-size:.9rem;">
                <span style="font-weight:900;">주요 신호</span>: {row.get('주요신호')}<br>
                <span style="font-weight:900;">권장 Action</span>: {row.get('권장Action')}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_school_info_cards() -> None:
    school = st.session_state.selected_school_info
    cols = st.columns(5)
    values = [
        ("학교 DB", school.get("학교명", "-"), school.get("학교급", "")),
        ("학생 수", f"{int(school.get('학교_학생수', 0)):,}명" if school.get("학교_학생수", 0) else "-", "DB 기준"),
        ("교원 1인당 학생수", f"{school.get('학교_교원1인당학생수', 0):.1f}명" if school.get("학교_교원1인당학생수", 0) else "-", "학교 여건"),
        ("위클래스", "있음" if school.get("위클래스_있음") else "없음", f"상담교사 {school.get('전문상담교사_수', 0)}명"),
        ("진로상담실", "있음" if school.get("진로상담실_있음") else "없음", f"보건교사 {school.get('보건교사_수', 0)}명"),
    ]
    for col, (label, value, help_text) in zip(cols, values):
        with col:
            st.markdown(metric_card(label, str(value), help_text), unsafe_allow_html=True)


def render_summary_cards(result: Dict[str, Any]) -> None:
    cards = [
        ("체크리스트 원점수", f"{result['raw_score']} / 20점", "1차 체크리스트 합산"),
        ("체크리스트 환산점수", f"{result['scaled_score']} / 100점", "원점수 × 5"),
        ("학교 맥락 보정", f"+{result['school_context_bonus']:g}점", result.get("applied_area", "")),
        ("지역 맥락 보정", f"+{result['region_context_bonus']:g}점", result.get("applied_area", "")),
        ("최종 우선순위 점수", f"{result['final_priority_score']:g} / 115점", "지원 검토 참고 점수"),
        ("원점수 기준 단계", result["score_based_stage"], "기본 단계"),
        ("최종 단계", result["final_action_stage"], "우선 확인 신호 반영"),
        ("권장 Action", result["final_action"], "다음 조치"),
    ]
    rows = [st.columns(4), st.columns(4)]
    idx = 0
    for row_cols in rows:
        for col in row_cols:
            label, value, help_text = cards[idx]
            with col:
                st.markdown(metric_card(label, value, help_text), unsafe_allow_html=True)
            idx += 1


def render_domain_score_table(domain_scores: pd.DataFrame, primary_areas: Optional[List[str]] = None) -> None:
    if domain_scores is None or domain_scores.empty:
        st.info("영역별 점수를 표시할 수 없습니다.")
        return
    primary_areas = primary_areas or []
    table = domain_scores.copy()
    table["우선 영역 여부"] = table["지원 영역"].apply(lambda x: "우선" if x in primary_areas else "-")
    table = table.rename(
        columns={
            "domain_raw_score": "원점수",
            "domain_max_score": "최대점수",
            "domain_scaled_score": "환산점수",
        }
    )[["지원 영역", "원점수", "최대점수", "환산점수", "우선 영역 여부"]]
    st.dataframe(table, use_container_width=True, hide_index=True)


def render_red_flag_section(red_flag_result: Dict[str, Any]) -> None:
    st.markdown("<div class='panel'><div class='panel-title'>우선 확인 필요 신호 결과</div>", unsafe_allow_html=True)
    if not red_flag_result.get("urgent_flag"):
        st.info("우선 확인 필요 신호가 확인되지 않았습니다.")
    else:
        st.markdown(
            "<div class='warning-callout'>긴급 확인 관련 신호가 포함되어 2차 상담 질문 생성 시 안전·정서·환경 확인 질문을 우선 포함합니다.</div>",
            unsafe_allow_html=True,
        )
        table = pd.DataFrame(red_flag_result.get("urgent_flag_items", []))
        if not table.empty:
            show_cols = [c for c in ["item_code", "item_text", "score", "area", "reason"] if c in table.columns]
            st.dataframe(table[show_cols], use_container_width=True, hide_index=True)
    st.markdown("</div>", unsafe_allow_html=True)


def render_deep_rule_cards(active_deep_rules: List[Dict[str, Any]]) -> None:
    st.markdown("<div class='panel'><div class='panel-title'>심층 유도 분석 결과</div>", unsafe_allow_html=True)
    if not active_deep_rules:
        st.info("활성화된 심층 유도 분석이 없습니다.")
    for i, rule in enumerate(active_deep_rules, start=1):
        linked = ", ".join(rule.get("linked_areas", [])) or "-"
        st.markdown(
            f"""
            <div class="recommend-card">
                <div style="font-weight:900;"><span class="recommend-rank">{i}</span>{rule.get('rule_title', rule.get('rule_id'))}</div>
                <div class="small-muted">활성화 유형: {rule.get('activation_type')}</div>
                <table class="info-table" style="margin-top:8px;">
                    <tr><th>표면 신호</th><td>{rule.get('surface_signal', '-')}</td></tr>
                    <tr><th>가능한 이면 변인</th><td>{rule.get('possible_hidden_factors', '-')}</td></tr>
                    <tr><th>심층 유도 서술</th><td>{rule.get('deep_guidance_text', '-')}</td></tr>
                    <tr><th>연결 지원 영역</th><td>{linked}</td></tr>
                </table>
            </div>
            """,
            unsafe_allow_html=True,
        )
    st.markdown("</div>", unsafe_allow_html=True)


def render_counseling_area_table(counseling_areas: List[Dict[str, Any]]) -> None:
    st.markdown("<div class='panel'><div class='panel-title'>상담지 생성 시 고려 영역</div>", unsafe_allow_html=True)
    if not counseling_areas:
        st.info("상담지 생성 시 추가로 고려할 영역이 없습니다.")
    else:
        table = pd.DataFrame(
            [
                {
                    "고려 영역": x["area"],
                    "확인 우선도": x["priority_level"],
                    "focus_score": x["focus_score"],
                    "포함 근거": " / ".join(x.get("reasons", [])),
                }
                for x in counseling_areas
            ]
        )
        st.dataframe(table, use_container_width=True, hide_index=True)
    st.markdown("</div>", unsafe_allow_html=True)


def render_context_table(context_result: Dict[str, Any]) -> None:
    st.markdown("<div class='panel'><div class='panel-title'>맥락 보정 표</div>", unsafe_allow_html=True)
    if context_result.get("context_missing"):
        st.warning("학교·지역 맥락 점수 중 일부를 불러오지 못해 보정점수는 0점 또는 일부만 적용됩니다.")
    table = context_result.get("context_table", pd.DataFrame())
    if not table.empty:
        long_rows = []
        for _, row in table.iterrows():
            long_rows.append(
                {
                    "구분": "학교 맥락",
                    "적용 영역": row["적용 영역"],
                    "원 맥락 점수": row["학교 맥락 점수"],
                    "보정 점수": row["학교 보정 점수"],
                    "적용 여부": row["적용 여부"],
                }
            )
            long_rows.append(
                {
                    "구분": "지역 맥락",
                    "적용 영역": row["적용 영역"],
                    "원 맥락 점수": row["지역 맥락 점수"],
                    "보정 점수": row["지역 보정 점수"],
                    "적용 여부": row["적용 여부"],
                }
            )
        st.dataframe(pd.DataFrame(long_rows), use_container_width=True, hide_index=True)
    st.caption("체크리스트 환산점수가 40점 미만이면 맥락 보정은 적용하지 않습니다. 단, 우선 확인 필요 신호는 별도로 판단합니다.")
    st.markdown("</div>", unsafe_allow_html=True)

# -----------------------------------------------------------------------------
# 페이지: 대시보드
# -----------------------------------------------------------------------------
def chart_bar(data: pd.DataFrame, x: str, y: str, title: str = "") -> None:
    if px is None:
        st.bar_chart(data.set_index(x)[y])
    else:
        fig = px.bar(data, x=x, y=y, text=y, title=title)
        fig.update_layout(height=300, margin=dict(l=10, r=10, t=35, b=10))
        fig.update_traces(textposition="outside")
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


def page_dashboard() -> None:
    role = st.session_state.role
    scope = f"{st.session_state.homeroom_grade} {st.session_state.homeroom_class}" if role == ROLE_HOMEROOM else "전교"
    render_page_title(
        f"{scope} 학생맞춤통합지원 대시보드",
        "담임교사는 본인 반만, 학생맞춤통합지원담당교원은 전교 학생 상태를 조회합니다.",
    )
    render_school_info_cards()

    df = get_view_students()
    total = len(df)
    deep = int((df["최종단계"] == "심층 파악 필요").sum())
    watch = int((df["최종단계"] == "주의 및 탐색").sum())
    red = int(df["RedFlag"].astype(bool).sum())
    meeting = deep

    metric_cols = st.columns(5)
    metrics = [
        ("조회 학생", f"{total}명", role),
        ("심층 파악 필요", f"{deep}명", "2차 상담 질문 후보"),
        ("주의 및 탐색", f"{watch}명", "담임 면담 후보"),
        ("우선 확인 신호", f"{red}명", "긴급 확인 관련"),
        ("회의자료 후보", f"{meeting}건", "학맞통 회의 검토"),
    ]
    for col, (label, value, help_text) in zip(metric_cols, metrics):
        with col:
            st.markdown(metric_card(label, value, help_text), unsafe_allow_html=True)

    left, right = st.columns([1.35, 1])
    with left:
        st.markdown("<div class='panel'><div class='panel-title'>지원 영역별 분포</div>", unsafe_allow_html=True)
        domain_counts = pd.DataFrame({"지원영역": SUPPORT_AREAS, "학생수": [(df[a] > 0).sum() for a in SUPPORT_AREAS]})
        chart_bar(domain_counts, "지원영역", "학생수")
        st.markdown("</div>", unsafe_allow_html=True)

        st.markdown("<div class='panel'><div class='panel-title'>우선 검토 학생 목록</div>", unsafe_allow_html=True)
        order = {"심층 파악 필요": 0, "주의 및 탐색": 1, "일상적 관찰": 2}
        show = df[df["최종단계"].isin(["심층 파악 필요", "주의 및 탐색"])].copy()
        show["정렬"] = show["최종단계"].map(order)
        show["합계"] = show[SUPPORT_AREAS].sum(axis=1)
        show = show.sort_values(["정렬", "RedFlag", "합계"], ascending=[True, False, False])
        if show.empty:
            st.info("현재 조회 범위에서 우선 검토 학생이 없습니다.")
        for _, row in show.head(20).iterrows():
            render_student_card(row)
        st.markdown("</div>", unsafe_allow_html=True)

    with right:
        st.markdown("<div class='panel'><div class='panel-title'>행동 단계 분포</div>", unsafe_allow_html=True)
        stage_counts = df["최종단계"].value_counts().reindex(STATUS_ORDER, fill_value=0).reset_index()
        stage_counts.columns = ["단계", "학생수"]
        chart_bar(stage_counts, "단계", "학생수")
        st.markdown("</div>", unsafe_allow_html=True)

        st.markdown("<div class='panel'><div class='panel-title'>학교 DB 연결 상태</div>", unsafe_allow_html=True)
        paths = st.session_state.school_db.get("paths", {})
        rows = []
        for label, path in paths.items():
            rows.append({"DB": label, "연결 파일": path.name if path else "없음"})
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        st.markdown("</div>", unsafe_allow_html=True)

# -----------------------------------------------------------------------------
# 페이지: 1차 체크리스트
# -----------------------------------------------------------------------------
def render_checklist_input(items_df: pd.DataFrame, selected_student: str) -> Dict[str, int]:
    responses: Dict[str, int] = {}
    if items_df.empty:
        st.error("1차 체크리스트 CSV를 불러올 수 없습니다.")
        return responses

    score_labels = {
        0: "0점 · 관찰되지 않음",
        1: "1점 · 약하게/가끔 관찰됨",
        2: "2점 · 뚜렷하게/자주 관찰됨",
    }
    grouped = items_df.groupby(["domain_order", "domain_label"], dropna=False, sort=True)
    for (_, domain_label), sub in grouped:
        with st.expander(str(domain_label), expanded=True):
            for _, row in sub.iterrows():
                item_id = normalize_text(row.get("item_id"))
                item_code = normalize_text(row.get("item_code"))
                item_text = normalize_text(row.get("item_text"))
                default_value = st.session_state.checklist_responses.get(selected_student, {}).get(item_id, 0)
                value = st.radio(
                    f"{item_code}. {item_text}",
                    [0, 1, 2],
                    index=[0, 1, 2].index(int(default_value)),
                    format_func=lambda x: score_labels[x],
                    horizontal=True,
                    key=f"score_{selected_student}_{item_id}",
                )
                responses[item_id] = int(value)
    return responses


def page_first_checklist() -> None:
    render_page_title(
        "1차 체크리스트 입력 및 심층 유도 분석",
        "1차 체크리스트 입력 후 점수 계산, 맥락 보정, 우선 확인 신호, 상담지 생성 고려 영역을 산출합니다.",
    )

    items_df = get_active_items_df()
    rule_map_df = st.session_state.get("rule_map_df")
    deep_rules_df = st.session_state.get("deep_rules_df")

    df = get_view_students()
    if df.empty:
        st.warning("현재 조회 범위에 학생이 없습니다.")
        return

    student_options = [f"{row['학생코드']} | {row['이름']} | {row['학년']} {row['반']}" for _, row in df.iterrows()]
    selected_label = st.selectbox("학생 선택", student_options, index=0)
    selected_student = selected_label.split(" | ")[0]

    left, right = st.columns([1.1, 1])
    with left:
        st.markdown("<div class='panel'><div class='panel-title'>1차 체크리스트</div>", unsafe_allow_html=True)
        responses = render_checklist_input(items_df, selected_student)
        save_clicked = st.button("체크리스트 결과 계산 및 학생 기록 반영", type="primary", use_container_width=True)
        st.markdown("</div>", unsafe_allow_html=True)

    if not responses:
        return

    first_result = calculate_checklist_scores(items_df, responses)
    red_flag_result = detect_red_flags(items_df, responses)
    stage_result = classify_action_stage(first_result["student_raw_score"], red_flag_result)
    active_deep_rules = activate_deep_rules(responses, rule_map_df, deep_rules_df)
    counseling_areas = derive_counseling_consideration_areas(
        first_result["domain_scores"], responses, red_flag_result, active_deep_rules, items_df
    )
    context_result = calculate_context_result(
        first_result["primary_areas"],
        first_result["student_scaled_score"],
        st.session_state.get("selected_school_context"),
        st.session_state.get("selected_region_context"),
    )
    payload = build_counseling_payload(
        first_result, red_flag_result, context_result, active_deep_rules, counseling_areas, stage_result
    )

    with right:
        st.markdown("<div class='panel'><div class='panel-title'>즉시 계산 결과</div>", unsafe_allow_html=True)
        summary_for_cards = {
            "raw_score": first_result["student_raw_score"],
            "scaled_score": first_result["student_scaled_score"],
            "school_context_bonus": context_result["school_context_bonus"],
            "region_context_bonus": context_result["region_context_bonus"],
            "final_priority_score": context_result["final_priority_score"],
            "score_based_stage": stage_result["score_based_stage"],
            "final_action_stage": stage_result["final_action_stage"],
            "final_action": stage_result["final_action"],
            "applied_area": context_result.get("applied_area", ""),
        }
        render_summary_cards(summary_for_cards)
        if stage_result["final_action_stage"] == "일상적 관찰":
            st.info("현재 1차 체크리스트 기준으로는 뚜렷한 지원 신호가 높지 않습니다. 평소 관찰과 라포 형성을 유지합니다.")
        elif stage_result["final_action_stage"] == "주의 및 탐색":
            st.warning("일부 지원 신호가 관찰됩니다. 담임교사의 가벼운 면담을 통해 학생의 최근 변화와 어려움을 탐색할 수 있습니다.")
        else:
            st.error("여러 지원 신호 또는 우선 확인 필요 신호가 확인되어 심층 파악이 필요합니다. 다음 단계에서 AI 2차 상담 질문 생성으로 연결할 수 있습니다.")
        st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("<div class='panel'><div class='panel-title'>영역별 점수 표</div>", unsafe_allow_html=True)
    render_domain_score_table(first_result["domain_scores"], first_result["primary_areas"])
    st.markdown("</div>", unsafe_allow_html=True)

    render_red_flag_section(red_flag_result)
    render_deep_rule_cards(active_deep_rules)
    render_counseling_area_table(counseling_areas)
    render_context_table(context_result)

    st.markdown("<div class='panel'><div class='panel-title'>다음 단계 LLM 입력 payload 미리보기</div>", unsafe_allow_html=True)
    st.json(payload)
    st.markdown(
        "<div class='callout'>다음 단계에서는 위 상담 고려 영역과 심층 유도 분석을 교육청 체크리스트와 함께 LLM에 전달하여 2차 상담 질문을 생성합니다.</div>",
        unsafe_allow_html=True,
    )
    st.markdown("</div>", unsafe_allow_html=True)

    if save_clicked:
        # 학생 기록 반영
        all_df = st.session_state.students.copy()
        idx = all_df.index[all_df["학생코드"] == selected_student]
        if len(idx) > 0:
            idx0 = idx[0]
            for _, row in first_result["domain_scores"].iterrows():
                area = row["지원 영역"]
                # 학생 카드용 0~4 점수로 축약 표시
                all_df.at[idx0, area] = min(4, int(round(float(row["domain_scaled_score"]) / 25)))
            all_df.at[idx0, "RedFlag"] = bool(red_flag_result.get("urgent_flag"))
            all_df.at[idx0, "최종단계"] = stage_result["final_action_stage"]
            all_df.at[idx0, "권장Action"] = stage_result["final_action"]
            checked_codes = []
            for _, row in items_df.iterrows():
                item_id = normalize_text(row.get("item_id"))
                if int(responses.get(item_id, 0)) >= 1:
                    checked_codes.append(normalize_text(row.get("item_code")))
            all_df.at[idx0, "주요신호"] = ", ".join(checked_codes) if checked_codes else "선택된 신호 없음"
            all_df.at[idx0, "기한"] = str(date.today()) if stage_result["final_action_stage"] != "일상적 관찰" else "-"
            st.session_state.students = all_df
        st.session_state.checklist_responses[selected_student] = responses
        st.session_state.last_payload = payload
        st.success("계산 결과가 학생 기록에 반영되었습니다.")

# -----------------------------------------------------------------------------
# 페이지: 학생 상세 / 지원 현황 / 데이터 연결 안내
# -----------------------------------------------------------------------------
def page_student_detail() -> None:
    render_page_title("학생 상세 리포트", "선택 학생의 현재 지원 신호와 다음 조치 후보를 확인합니다.")
    df = get_view_students()
    if df.empty:
        st.warning("현재 조회 범위에 학생이 없습니다.")
        return
    selected = st.selectbox("학생 선택", df["학생코드"].tolist())
    student = df[df["학생코드"] == selected].iloc[0]

    col1, col2 = st.columns([1, 1.4])
    with col1:
        render_student_card(student)
        st.markdown("<div class='panel'><div class='panel-title'>학생 요약</div>", unsafe_allow_html=True)
        table = pd.DataFrame(
            [
                ["학생코드", student["학생코드"]],
                ["학년·반", f"{student['학년']} {student['반']}"],
                ["최종 단계", student["최종단계"]],
                ["우선 확인 신호", "있음" if student["RedFlag"] else "없음"],
                ["담당자", student["담당자"]],
                ["기한", student["기한"]],
            ],
            columns=["항목", "내용"],
        )
        st.dataframe(table, use_container_width=True, hide_index=True)
        st.markdown("</div>", unsafe_allow_html=True)

    with col2:
        st.markdown("<div class='panel'><div class='panel-title'>지원 검토 메모</div>", unsafe_allow_html=True)
        areas = [a for a in SUPPORT_AREAS if int(student.get(a, 0)) > 0]
        st.write("우선 검토 영역: " + (", ".join(areas) if areas else "현재 뚜렷한 우선 영역 없음"))
        st.write("관찰 신호: " + normalize_text(student.get("주요신호")))
        if student["최종단계"] == "심층 파악 필요":
            st.error("심층 파악이 필요한 상태입니다. 1차 체크리스트 결과를 바탕으로 2차 상담 질문 생성을 검토합니다.")
        elif student["최종단계"] == "주의 및 탐색":
            st.warning("담임교사의 가벼운 면담과 관찰 기록 업데이트를 권장합니다.")
        else:
            st.info("현재는 일상적 관찰 단계입니다.")
        st.markdown("</div>", unsafe_allow_html=True)

        if st.session_state.get("last_payload"):
            with st.expander("최근 생성 payload 보기"):
                st.json(st.session_state.last_payload)


def make_status_table(df: pd.DataFrame) -> pd.DataFrame:
    table = df.copy()
    table["지원영역"] = table.apply(lambda r: ", ".join([a for a in SUPPORT_AREAS if int(r[a]) > 0]) or "-", axis=1)
    table["다음 할 일"] = table["권장Action"]
    return table[["학생코드", "학년", "반", "최종단계", "RedFlag", "지원영역", "주요신호", "다음 할 일", "담당자", "기한"]]


def to_excel_bytes(df: pd.DataFrame) -> bytes:
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="지원현황")
    return output.getvalue()


def page_status_table() -> None:
    render_page_title("지원 현황표", "조회 권한에 따른 지원 현황을 표로 보고 CSV/Excel로 다운로드합니다.")
    df = get_view_students()
    stage_filter = st.multiselect("단계", STATUS_ORDER, default=["심층 파악 필요", "주의 및 탐색"])
    if stage_filter:
        df = df[df["최종단계"].isin(stage_filter)]
    table = make_status_table(df)
    st.dataframe(table, use_container_width=True, hide_index=True)

    col1, col2, col3 = st.columns([1, 1, 2])
    with col1:
        st.download_button("CSV 다운로드", data=table.to_csv(index=False).encode("utf-8-sig"), file_name="학맞통_지원현황표.csv", mime="text/csv", use_container_width=True)
    with col2:
        st.download_button("Excel 다운로드", data=to_excel_bytes(table), file_name="학맞통_지원현황표.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)
    with col3:
        st.info("실제 제출·시연에서는 학생 실명 대신 학생코드만 사용하세요.")


def page_data_connection() -> None:
    render_page_title("DB 연결 안내", "현재 버전은 CSV 파일을 DB처럼 읽어 학교 정보와 맥락 점수를 연결합니다.")
    st.markdown("<div class='panel'><div class='panel-title'>현재 연결된 파일</div>", unsafe_allow_html=True)
    rows = []
    for key, path in st.session_state.school_db.get("paths", {}).items():
        rows.append({"구분": key, "파일명": path.name if path else "없음", "경로": str(path) if path else "-"})
    rows.extend(
        [
            {"구분": "checklist", "파일명": st.session_state.get("checklist_path_name", "없음"), "경로": "data/first_checklist_items_v1.csv"},
            {"구분": "deep_rules", "파일명": st.session_state.get("deep_rules_path_name", "없음"), "경로": "data/deep_inference_rules_v1.csv"},
            {"구분": "rule_map", "파일명": st.session_state.get("rule_map_path_name", "없음"), "경로": "data/checklist_item_deep_rule_map_v1.csv"},
        ]
    )
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("<div class='panel'><div class='panel-title'>GitHub 배포용 폴더 구조</div>", unsafe_allow_html=True)
    st.code(
        """hmt-streamlit/
├─ hakmatch_streamlit_app.py
├─ requirements.txt
└─ data/
   ├─ 05_school_info_db_location.csv
   ├─ 02_school_context_scores_db.csv
   ├─ 서울_학생지원맥락_영역별점수.csv
   ├─ first_checklist_items_v1.csv
   ├─ deep_inference_rules_v1.csv
   └─ checklist_item_deep_rule_map_v1.csv""",
        language="text",
    )
    st.write("Streamlit Cloud에서는 별도 SQL 서버 없이도 위 CSV 파일을 data 폴더에 올리면 앱이 자동으로 읽습니다.")
    st.write("나중에 Supabase, PostgreSQL 같은 실제 DB로 바꿀 때는 load_school_databases() 함수만 DB 조회 코드로 교체하면 됩니다.")
    st.markdown("</div>", unsafe_allow_html=True)

# -----------------------------------------------------------------------------
# 초기화 / 사이드바
# -----------------------------------------------------------------------------
def init_state() -> None:
    if "role" not in st.session_state:
        st.session_state.role = ROLE_HOMEROOM
    if "homeroom_grade" not in st.session_state:
        st.session_state.homeroom_grade = DEFAULT_GRADE
    if "homeroom_class" not in st.session_state:
        st.session_state.homeroom_class = DEFAULT_CLASS
    if "checklist_responses" not in st.session_state:
        st.session_state.checklist_responses = {}

    school_db = load_school_databases()
    st.session_state.school_db = school_db
    for err in school_db.get("errors", []):
        st.sidebar.error(err)

    school_info_df = school_db["school_info_df"]
    if "selected_school_name" not in st.session_state:
        if "공항고등학교" in school_info_df["학교명"].astype(str).tolist():
            st.session_state.selected_school_name = "공항고등학교"
        else:
            st.session_state.selected_school_name = str(school_info_df.iloc[0]["학교명"])

    selected_info_row = find_matching_row(school_info_df, st.session_state.selected_school_name)
    if selected_info_row is None:
        selected_info_row = school_info_df.iloc[0]
        st.session_state.selected_school_name = str(selected_info_row["학교명"])
    st.session_state.selected_school_info = school_row_to_dict(selected_info_row)

    district = st.session_state.selected_school_info.get("자치구", "")
    st.session_state.selected_school_context = find_matching_row(
        school_db.get("school_context_df"),
        st.session_state.selected_school_name,
        district,
    )
    st.session_state.selected_region_context = find_region_row(school_db.get("region_context_df"), district)

    # 체크리스트/규칙 CSV
    items_df, items_path, items_err = load_optional_csv(CSV_PATHS["checklist"], "1차 체크리스트")
    deep_rules_df, deep_rules_path, deep_rules_err = load_optional_csv(CSV_PATHS["deep_rules"], "심층 유도 규칙")
    rule_map_df, rule_map_path, rule_map_err = load_optional_csv(CSV_PATHS["rule_map"], "체크리스트-규칙 매핑")
    for err in [items_err, deep_rules_err, rule_map_err]:
        if err:
            st.sidebar.error(err)
    st.session_state.checklist_items_df = items_df if items_df is not None else pd.DataFrame()
    st.session_state.deep_rules_df = deep_rules_df if deep_rules_df is not None else pd.DataFrame()
    st.session_state.rule_map_df = rule_map_df if rule_map_df is not None else pd.DataFrame()
    st.session_state.checklist_path_name = items_path.name if items_path else "없음"
    st.session_state.deep_rules_path_name = deep_rules_path.name if deep_rules_path else "없음"
    st.session_state.rule_map_path_name = rule_map_path.name if rule_map_path else "없음"

    if "students_school_name" not in st.session_state or st.session_state.students_school_name != st.session_state.selected_school_name:
        st.session_state.students = generate_demo_students(st.session_state.selected_school_name)
        st.session_state.students_school_name = st.session_state.selected_school_name


def render_sidebar() -> str:
    st.sidebar.markdown("### 학교 DB 선택")
    school_info_df = st.session_state.school_db["school_info_df"]
    school_names = school_info_df["학교명"].astype(str).drop_duplicates().tolist()
    if st.session_state.selected_school_name not in school_names:
        st.session_state.selected_school_name = school_names[0]
    selected_school = st.sidebar.selectbox(
        "학교명",
        school_names,
        index=school_names.index(st.session_state.selected_school_name),
        help="CSV DB에서 학교 정보를 불러옵니다.",
    )
    if selected_school != st.session_state.selected_school_name:
        st.session_state.selected_school_name = selected_school
        st.rerun()

    st.sidebar.markdown("### 담임 반 설정")
    st.session_state.homeroom_grade = st.sidebar.selectbox("학년", ["1학년", "2학년", "3학년"], index=["1학년", "2학년", "3학년"].index(st.session_state.homeroom_grade))
    st.session_state.homeroom_class = st.sidebar.selectbox("반", ["1반", "2반", "3반", "4반"], index=["1반", "2반", "3반", "4반"].index(st.session_state.homeroom_class))

    st.sidebar.divider()
    st.sidebar.markdown("### 메뉴")
    page = st.sidebar.radio(
        "화면 선택",
        ["담임교사 대시보드", "1차 체크리스트", "학생 상세 리포트", "지원 현황표", "DB 연결 안내"],
        index=0,
        label_visibility="collapsed",
    )

    school = st.session_state.selected_school_info
    st.sidebar.divider()
    st.sidebar.markdown("### 현재 학교 정보")
    st.sidebar.write(f"학교: {school.get('학교명')}")
    st.sidebar.write(f"자치구: {school.get('자치구')}")
    st.sidebar.write(f"위클래스: {'있음' if school.get('위클래스_있음') else '없음'}")
    st.sidebar.write(f"전문상담교사: {school.get('전문상담교사_수')}명")
    st.sidebar.caption("DB 파일을 교체하면 학교 정보가 자동으로 바뀝니다.")
    return page

# -----------------------------------------------------------------------------
# 메인
# -----------------------------------------------------------------------------
def main() -> None:
    inject_css()
    init_state()
    render_header()
    render_role_switch()
    page = render_sidebar()

    if page == "담임교사 대시보드":
        page_dashboard()
    elif page == "1차 체크리스트":
        page_first_checklist()
    elif page == "학생 상세 리포트":
        page_student_detail()
    elif page == "지원 현황표":
        page_status_table()
    elif page == "DB 연결 안내":
        page_data_connection()

    st.markdown(
        """
        <div class="footer-note">
        본 화면은 학맞통 AI 서비스의 발표·시연용 프로토타입입니다. 학생 지원 여부를 자동 확정하지 않으며,
        담임교사와 학교 협의체의 검토를 돕는 참고자료로 설계되었습니다.
        </div>
        """,
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
