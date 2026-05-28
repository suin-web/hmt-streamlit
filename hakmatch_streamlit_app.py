# -*- coding: utf-8 -*-
"""
학맞통 AI 교사용 의사결정 보조 프로토타입 v3

실행:
    streamlit run hakmatch_streamlit_app.py

이번 버전 반영 사항:
- 접속 첫 화면: 담임교사 대시보드
- 상단 역할 전환: 담임교사 / 학생맞춤통합지원담당교원
- 담임교사: 본인 반 학생만 조회
- 학생맞춤통합지원담당교원: 전교 학생 상태 조회
- 학교 정보 DB CSV 연결
- 1차 체크리스트 입력 → 점수 계산 → 맥락 보정 → 우선 확인 신호 확인
  → 심층 유도 분석 활성화 → 상담지 생성 고려 영역 산출
- Gemini API 기반 2차 상담 질문 생성, 상담 메모 구조화, 기관 추천 이유 생성
- Chroma DB 기반 RAG 검색, docx 템플릿 기반 협의록 및 학생성장기록지 생성

주의:
- 이 코드는 발표·시연용 MVP입니다.
- 실제 학생 개인정보, 실제 학교명, 민감 정보는 넣지 마세요.
- 문서 생성 단계에서 개인정보는 LLM에 보내지 않고 Python이 템플릿에 직접 삽입합니다.
"""

from __future__ import annotations

import io
import json
import math
import os
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import pandas as pd
import streamlit as st

from gemini_client import call_llm_with_validation, get_gemini_api_key
from validation import (
    HARD_BANNED_COMMON,
    validate_counseling_question_output,
    validate_counseling_analysis_output,
    validate_resource_recommendation_output,
    validate_document_generation_output,
)

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
    "official_checklist": [
        DATA_DIR / "official_counseling_checklist_reference_v1.csv",
        APP_DIR / "official_counseling_checklist_reference_v1.csv",
    ],
}

JSON_PATHS = {
    "district_adjacency": [
        DATA_DIR / "district_adjacency_seoul_FILTER_READY_20260527_v3.json",
        DATA_DIR / "district_adjacency_seoul_v1.json",
        APP_DIR / "district_adjacency_seoul_FILTER_READY_20260527_v3.json",
        APP_DIR / "district_adjacency_seoul_v1.json",
    ],
    "rag_config": [
        DATA_DIR / "rag_filter_rank_config_20260527_v3.json",
        APP_DIR / "rag_filter_rank_config_20260527_v3.json",
    ],
}

TEMPLATE_DIR = APP_DIR / "templates"
OUTPUT_DIR = APP_DIR / "outputs"

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

STATUS_ORDER = ["심층 파악 필요", "심층 파악 권고", "주의 및 탐색", "일상적 관찰"]
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



def score_based_stage_from_raw(raw_score: int) -> Tuple[str, str]:
    if raw_score <= 3:
        return "일상적 관찰", "현재 유지"
    if raw_score <= 7:
        return "주의 및 탐색", "교사 면담 및 가벼운 개입"
    return "심층 파악 필요", "2차 상담 질문 활성화 및 전문 상담 검토"


def context_adjustment_not_applied_reason(raw_score: int, red_flag: bool) -> str:
    if red_flag:
        return "우선 확인 필요 신호 우선 적용"
    if raw_score <= 4:
        return "원점수 0~4점 구간"
    if raw_score >= 8:
        return "원점수 8점 이상으로 이미 심층 파악 기준 도달"
    return "-"


def determine_final_action_stage(raw_score: int, scaled_score: float, red_flag: bool, context_check_score: float, context_adjustment_applied: bool) -> Dict[str, Any]:
    score_stage, score_action = score_based_stage_from_raw(raw_score)
    if red_flag:
        return {
            "score_based_stage": score_stage,
            "score_based_action": score_action,
            "final_action_stage": "심층 파악 필요",
            "final_action": "2차 상담 질문 활성화 및 우선 확인 질문 포함",
            "final_action_reason": "우선 확인 필요 신호가 포함되어 있습니다.",
            "activate_counseling_form": True,
        }
    if raw_score >= 8:
        return {
            "score_based_stage": score_stage,
            "score_based_action": score_action,
            "final_action_stage": "심층 파악 필요",
            "final_action": "2차 상담 질문 활성화 및 전문 상담 검토",
            "final_action_reason": "1차 체크리스트 원점수가 심층 파악 기준에 도달했습니다.",
            "activate_counseling_form": True,
        }
    if 5 <= raw_score <= 7:
        if context_adjustment_applied and context_check_score >= 40:
            return {
                "score_based_stage": score_stage,
                "score_based_action": score_action,
                "final_action_stage": "심층 파악 권고",
                "final_action": "2차 상담 질문 생성 권고",
                "final_action_reason": "체크리스트 기준으로는 주의 및 탐색 단계이나, 학교·지역 지원여건을 고려할 때 2차 상담 질문으로 한 번 더 확인하는 것이 권장됩니다.",
                "activate_counseling_form": True,
            }
        return {
            "score_based_stage": score_stage,
            "score_based_action": score_action,
            "final_action_stage": "주의 및 탐색",
            "final_action": "담임교사 면담과 추가 관찰 우선",
            "final_action_reason": "일부 지원 신호가 관찰되지만, 현재는 담임교사의 면담과 추가 관찰을 우선 권장합니다.",
            "activate_counseling_form": False,
        }
    if raw_score == 4:
        return {
            "score_based_stage": score_stage,
            "score_based_action": score_action,
            "final_action_stage": "주의 및 탐색",
            "final_action": "교사 면담 및 가벼운 개입",
            "final_action_reason": "일부 지원 신호가 관찰됩니다. 단, 맥락 보정 적용 구간에는 해당하지 않아 담임교사의 면담과 추가 관찰을 우선 권장합니다.",
            "activate_counseling_form": False,
        }
    return {
        "score_based_stage": score_stage,
        "score_based_action": score_action,
        "final_action_stage": "일상적 관찰",
        "final_action": "현재 유지",
        "final_action_reason": "현재 1차 체크리스트 기준으로는 뚜렷한 지원 신호가 높지 않습니다.",
        "activate_counseling_form": False,
    }


def calculate_context_result(
    primary_areas: List[str],
    student_raw_score: int,
    student_scaled_score: float,
    red_flag_result: Dict[str, Any],
    selected_school_context: Optional[pd.Series],
    selected_region_context: Optional[pd.Series],
) -> Dict[str, Any]:
    usable_primary = [a for a in primary_areas if a in SUPPORT_AREAS]
    applied_area = usable_primary[0] if usable_primary else "-"
    school_col = AREA_TO_SCHOOL_CONTEXT_COL.get(applied_area, "")
    region_col = AREA_TO_REGION_CONTEXT_COL.get(applied_area, "")
    school_context_score = get_cell(selected_school_context, school_col, 0) if school_col else 0.0
    region_context_score = get_cell(selected_region_context, region_col, 0) if region_col else 0.0

    red_flag = bool(red_flag_result.get("urgent_flag"))
    context_adjustment_applied = (5 <= int(student_raw_score) <= 7) and not red_flag
    context_adjustment_reason = "원점수 5~7점 구간이며 우선 확인 필요 신호가 없어 맥락 보정을 적용합니다." if context_adjustment_applied else context_adjustment_not_applied_reason(int(student_raw_score), red_flag)

    school_candidate = calculate_school_bonus(school_context_score, True)
    region_candidate = calculate_region_bonus(region_context_score, True)
    school_applied = school_candidate if context_adjustment_applied else 0.0
    region_applied = region_candidate if context_adjustment_applied else 0.0
    context_check_score = round(float(student_scaled_score) + school_applied + region_applied, 1)
    stage = determine_final_action_stage(int(student_raw_score), float(student_scaled_score), red_flag, context_check_score, context_adjustment_applied)

    reason = "-" if context_adjustment_applied else context_adjustment_reason
    context_rows = [
        {
            "구분": "학교 맥락",
            "적용 영역": applied_area,
            "원 맥락 점수": round(school_context_score, 1),
            "산출 가능한 보정점수": school_candidate,
            "실제 적용 보정점수": school_applied,
            "적용 여부": "적용" if context_adjustment_applied else "미적용",
            "미적용 사유": reason,
        },
        {
            "구분": "지역 맥락",
            "적용 영역": applied_area,
            "원 맥락 점수": round(region_context_score, 1),
            "산출 가능한 보정점수": region_candidate,
            "실제 적용 보정점수": region_applied,
            "적용 여부": "적용" if context_adjustment_applied else "미적용",
            "미적용 사유": reason,
        },
    ]
    return {
        "applied_area": applied_area,
        "context_adjustment_applied": context_adjustment_applied,
        "context_adjustment_reason": context_adjustment_reason,
        "school_context_score": round(school_context_score, 1),
        "region_context_score": round(region_context_score, 1),
        "school_context_bonus_candidate": school_candidate,
        "region_context_bonus_candidate": region_candidate,
        "school_context_bonus_applied": school_applied,
        "region_context_bonus_applied": region_applied,
        "context_check_score": context_check_score,
        "context_table": pd.DataFrame(context_rows),
        "context_missing": selected_school_context is None or selected_region_context is None,
        **stage,
    }


def build_counseling_payload(
    first_check_result: Dict[str, Any],
    red_flag_result: Dict[str, Any],
    context_result: Dict[str, Any],
    active_deep_rules: List[Dict[str, Any]],
    counseling_consideration_areas: List[Dict[str, Any]],
    stage_result: Dict[str, Any],
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
            "final_action_reason": stage_result.get("final_action_reason", ""),
            "activate_counseling_form": bool(stage_result.get("activate_counseling_form", False)),
            "domain_scores": domain_scores_payload,
            "primary_areas": first_check_result["primary_areas"],
        },
        "red_flag_result": {
            "urgent_flag": bool(red_flag_result.get("urgent_flag", False)),
            "urgent_flag_items": red_flag_result.get("urgent_flag_items", []),
        },
        "context_result": {
            "context_adjustment_applied": bool(context_result.get("context_adjustment_applied", False)),
            "context_adjustment_reason": context_result.get("context_adjustment_reason"),
            "school_context_score": context_result.get("school_context_score"),
            "region_context_score": context_result.get("region_context_score"),
            "school_context_bonus_candidate": context_result.get("school_context_bonus_candidate"),
            "region_context_bonus_candidate": context_result.get("region_context_bonus_candidate"),
            "school_context_bonus_applied": context_result.get("school_context_bonus_applied"),
            "region_context_bonus_applied": context_result.get("region_context_bonus_applied"),
            "context_check_score": context_result.get("context_check_score"),
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
                "counseling_question_areas": r.get("counseling_question_areas"),
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
    if stage in ["심층 파악 필요", "심층 파악 권고"]:
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
    cls = "risk-deep" if stage in ["심층 파악 필요", "심층 파악 권고"] else ("risk-watch" if stage == "주의 및 탐색" else "risk-normal")
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
    context_label = "적용" if result.get("context_adjustment_applied") else "미적용"
    context_help = result.get("context_adjustment_reason", "")
    cards = [
        ("체크리스트 원점수", f"{result['raw_score']} / 20점", "1차 체크리스트 합산"),
        ("체크리스트 환산점수", f"{result['scaled_score']} / 100점", "원점수 × 5"),
        ("원점수 기준 단계", result["score_based_stage"], "기본 단계"),
        ("우선 확인 필요 신호", "있음" if result.get("urgent_flag") else "없음", "Red Flag 참고"),
        ("맥락 보정 적용 여부", context_label, context_help),
        ("맥락 반영 심층확인 점수", f"{result['context_check_score']:g}" if result.get("context_adjustment_applied") else "미적용", "5~7점 구간에서만 적용"),
        ("최종 안내 단계", result["final_action_stage"], result.get("final_action_reason", "")),
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
    st.markdown("<div class='panel'><div class='panel-title'>맥락 반영 심층확인 점수 표</div>", unsafe_allow_html=True)
    if context_result.get("context_missing"):
        st.warning("학교 또는 지역 맥락 점수를 찾을 수 없어 참고 보정은 0점으로 처리했습니다.")
    table = context_result.get("context_table")
    if isinstance(table, pd.DataFrame) and not table.empty:
        st.dataframe(table, use_container_width=True, hide_index=True)
    if context_result.get("context_adjustment_applied"):
        st.caption("체크리스트 원점수 5~7점 구간에서만 학교·지역 맥락을 심층확인 보조 지표로 반영합니다.")
    else:
        st.caption("학교·지역 맥락 점수는 학생 개인의 지원 필요도를 직접 높이는 점수가 아니며, 이번 결과에서는 행동 단계 판단에 적용하지 않았습니다.")
    st.markdown("</div>", unsafe_allow_html=True)


# -----------------------------------------------------------------------------
# v3: Gemini, 상담 질문, 상담 메모 구조화, RAG, 기관 추천, 문서 생성
# -----------------------------------------------------------------------------

def load_json_with_fallback(paths: Iterable[Path]) -> Dict[str, Any]:
    path = first_existing_path(paths)
    if path is None:
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        try:
            return json.loads(path.read_text(encoding="cp949"))
        except Exception:
            return {}


def load_official_checklist_reference() -> Tuple[Optional[pd.DataFrame], Optional[str]]:
    path = first_existing_path(CSV_PATHS.get("official_checklist", []))
    if path is None:
        return None, "official_counseling_checklist_reference_v1.csv 파일을 찾을 수 없습니다."
    try:
        return load_csv_with_fallback(path), None
    except Exception as exc:
        return None, f"공식 체크리스트 참고 CSV를 읽지 못했습니다: {exc}"


def get_official_checklist_context(
    official_df: pd.DataFrame,
    counseling_consideration_areas: List[Dict[str, Any]],
    red_flag_result: Dict[str, Any],
    max_items: int = 12,
) -> List[Dict[str, Any]]:
    if official_df is None or official_df.empty:
        return []
    df = official_df.copy()
    for c in ["mapped_area_primary", "mapped_area_secondary", "urgent_check_reference", "question_focus", "suggested_question_angle"]:
        if c not in df.columns:
            df[c] = ""
    areas = [normalize_area_name(x.get("area", "")) for x in counseling_consideration_areas if x.get("area")]
    areas = [a for a in areas if a]
    required_areas = [normalize_area_name(x.get("area", "")) for x in counseling_consideration_areas if x.get("priority_level") == "필수 확인"]

    def row_match(row: pd.Series) -> bool:
        primary = normalize_area_name(row.get("mapped_area_primary", ""))
        secondary = normalize_area_list(row.get("mapped_area_secondary", ""))
        if primary in areas or any(a in areas for a in secondary):
            return True
        if primary == "공통":
            return True
        if red_flag_result.get("urgent_flag") and str(row.get("urgent_check_reference", "")).upper().strip() == "Y":
            return True
        return False

    filtered = df[df.apply(row_match, axis=1)].copy()
    if filtered.empty:
        filtered = df[df.get("mapped_area_primary", "").astype(str).map(normalize_area_name).isin(["공통"] + SUPPORT_AREAS)].head(5).copy()

    def priority_score(row: pd.Series) -> int:
        score = 0
        primary = normalize_area_name(row.get("mapped_area_primary", ""))
        secondary = normalize_area_list(row.get("mapped_area_secondary", ""))
        if primary in required_areas or any(a in required_areas for a in secondary):
            score += 50
        if str(row.get("urgent_check_reference", "")).upper().strip() == "Y":
            score += 30
        if normalize_text(row.get("question_focus")):
            score += 5
        if normalize_text(row.get("suggested_question_angle")):
            score += 5
        return score

    filtered["_priority"] = filtered.apply(priority_score, axis=1)
    sort_cols = ["_priority"]
    ascending = [False]
    for col in ["section_order", "item_order"]:
        if col in filtered.columns:
            sort_cols.append(col)
            ascending.append(True)
    filtered = filtered.sort_values(sort_cols, ascending=ascending).head(max_items)

    out: List[Dict[str, Any]] = []
    for _, r in filtered.iterrows():
        out.append(
            {
                "ref_id": normalize_text(r.get("ref_id")),
                "criterion_type": normalize_text(r.get("criterion_type")),
                "mapped_area_primary": normalize_text(r.get("mapped_area_primary")),
                "mapped_area_secondary": normalize_text(r.get("mapped_area_secondary")),
                "urgent_check_reference": normalize_text(r.get("urgent_check_reference")),
                "official_item_text": normalize_text(r.get("official_item_text")),
                "question_focus": normalize_text(r.get("question_focus")),
                "suggested_question_angle": normalize_text(r.get("suggested_question_angle")),
                "teacher_caution": normalize_text(r.get("teacher_caution")),
            }
        )
    return out


def _safe_json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2, default=str)


# ------------------------------ 2차 상담 질문 생성 ------------------------------
def build_counseling_question_system_prompt() -> str:
    return """
너는 학생맞춤통합지원 업무를 돕는 교사용 AI 상담 질문 생성 보조도구이다.
너의 역할은 1차 체크리스트 결과, 심층 유도 분석, 공식 교육청 체크리스트 참고 항목을 바탕으로 교사가 학생과 2차 상담을 진행할 때 사용할 수 있는 상담 질문을 추천하는 것이다.
학생을 진단하거나 판정하지 말고, 교사의 최종 판단을 대체하지 않는다.
낙인 표현, 의학적·법적 진단, 취조형 질문, 비교·죄책감 유발, 위협 표현을 사용하지 않는다.
공식 체크리스트 문항을 그대로 복사하지 말고 학생에게 자연스럽게 물어볼 수 있는 개방형 상담 질문으로 바꾼다.
출력은 반드시 지정된 JSON 형식으로만 작성한다.
""".strip()


def build_counseling_question_user_prompt(payload: Dict[str, Any]) -> str:
    return f"""
아래 자료를 바탕으로 학생맞춤통합지원 2차 상담 질문을 생성하라.
이번 상담지는 점수형 체크리스트가 아니라 교사가 학생과 대화할 때 활용할 수 있는 상담 질문 추천지이다.

[1차 체크리스트 결과]
{_safe_json(payload.get('first_check_result'))}

[Red Flag 또는 우선확인 신호 결과]
{_safe_json(payload.get('red_flag_result'))}

[활성화된 심층 유도 분석]
{_safe_json(payload.get('active_deep_rules'))}

[상담 질문 생성 시 고려할 영역]
{_safe_json(payload.get('counseling_consideration_areas'))}

[공식 교육청 체크리스트 참고 항목]
{_safe_json(payload.get('official_checklist_context'))}

중요 지침:
1. 교사 관찰 메모는 이번 입력에 포함되지 않는다.
2. 입력에 없는 학생의 구체적 사정, 가정환경, 질병, 피해 경험, 심리 상태를 만들어내지 않는다.
3. 필수 확인 영역은 반드시 질문에 포함한다.
4. 우선 확인 필요 신호가 있으면 linked_area가 "긴급확인"인 질문을 최소 1개 포함한다.
5. 질문은 총 5~8개 생성한다.
6. 각 질문마다 질문 목적, 연결 영역, 근거, 교사 유의사항을 함께 작성한다.
7. 출력은 JSON만 작성한다.

출력 형식:
{{
  "counseling_focus_summary": "이번 상담에서 중점적으로 확인할 내용 요약",
  "question_generation_basis": {{
    "primary_areas": ["학업"],
    "secondary_areas": ["진로", "심리정서"],
    "urgent_check_needed": false,
    "basis_summary": "질문 생성 근거 요약"
  }},
  "recommended_questions": [
    {{
      "question_id": "Q1",
      "question": "상담 질문 문장",
      "purpose": "이 질문을 하는 목적",
      "linked_area": "진로 / 학업 / 심리정서 / 복지경제 / 긴급확인 중 하나",
      "based_on": ["1차 체크리스트 문항", "심층 유도 분석 rule_id", "공식 체크리스트 참고 항목"],
      "teacher_caution": "교사가 질문할 때 주의할 점",
      "follow_up_if_needed": "학생 답변에 따라 추가로 확인할 수 있는 내용"
    }}
  ],
  "areas_to_confirm": [
    {{"area": "심리정서", "priority": "필수 확인 / 함께 확인 / 보조 확인", "reason": "이유"}}
  ],
  "urgent_check_guidance": {{"urgent_check_needed": false, "guidance": ""}},
  "teacher_recording_guide": ["상담 후 교사가 기록하면 좋은 내용 1", "기록 내용 2", "기록 내용 3"],
  "next_step_hint": "상담 후 교사 메모를 입력하면 지원 영역 구조화, 지역기관 추천, 협의록 초안 생성으로 연결할 수 있다."
}}
""".strip()


def build_counseling_question_repair_prompt(validation_error: str, previous_output: str) -> str:
    return f"""
이전 출력은 상담 질문 생성 조건을 충족하지 못했습니다.
검증 실패 사유: {validation_error}

아래 조건을 반영하여 다시 JSON 형식으로만 작성하세요.
1. recommended_questions는 5~8개일 것
2. 모든 질문에는 question, purpose, linked_area, based_on, teacher_caution 필드가 있어야 함
3. linked_area는 진로, 학업, 심리정서, 복지경제, 긴급확인 중 하나만 사용할 것
4. 금지 표현, 진단 표현, 취조형 표현, 비교·죄책감 유발 표현, 위협 표현을 사용하지 말 것
5. 학생을 진단하거나 낙인찍지 말 것
6. 공식 체크리스트 문항을 그대로 복사하지 말고 부드러운 개방형 상담 질문으로 바꿀 것

[이전 출력]
{previous_output}
""".strip()


def render_counseling_question_section() -> None:
    st.markdown("<div class='panel'><div class='panel-title'>AI 2차 상담 질문 추천</div>", unsafe_allow_html=True)
    first_check_result = st.session_state.get("first_check_result")
    red_flag_result = st.session_state.get("red_flag_result", {"urgent_flag": False, "urgent_flag_items": []})
    active_deep_rules = st.session_state.get("active_deep_rules", [])
    counseling_areas = st.session_state.get("counseling_consideration_areas", [])
    if not first_check_result or not counseling_areas:
        st.info("1차 체크리스트 결과와 상담 고려 영역이 생성되면 상담 질문을 만들 수 있습니다.")
        st.markdown("</div>", unsafe_allow_html=True)
        return
    official_df, err = load_official_checklist_reference()
    if err:
        st.warning(err)
        st.markdown("</div>", unsafe_allow_html=True)
        return
    official_context = get_official_checklist_context(official_df, counseling_areas, red_flag_result)
    st.session_state["official_checklist_context"] = official_context
    activate = bool(first_check_result.get("activate_counseling_form"))
    if activate:
        st.info("현재 결과에서는 2차 상담 질문 생성이 권장됩니다.")
    else:
        st.caption("현재 최종 안내 단계에서는 필수는 아니지만, 교사가 필요하다고 판단하면 질문지를 생성해볼 수 있습니다.")
    with st.expander("공식 교육청 체크리스트 참고 항목 보기", expanded=False):
        show = pd.DataFrame(official_context)
        if not show.empty:
            cols = [c for c in ["ref_id", "criterion_type", "mapped_area_primary", "question_focus", "suggested_question_angle"] if c in show.columns]
            st.dataframe(show[cols], use_container_width=True, hide_index=True)
    if not get_gemini_api_key():
        st.warning("Gemini API 키가 설정되어 있지 않습니다. Streamlit secrets 또는 환경변수에 GEMINI_API_KEY를 설정해 주세요.")
    if st.button("2차 상담 질문 생성하기", type="primary", use_container_width=True, key="btn_generate_questions"):
        if not get_gemini_api_key():
            st.warning("API 키가 설정되지 않아 상담 질문 생성을 실행할 수 없습니다.")
        else:
            payload = {
                "first_check_result": first_check_result,
                "red_flag_result": red_flag_result,
                "active_deep_rules": active_deep_rules,
                "counseling_consideration_areas": counseling_areas,
                "context_result": st.session_state.get("context_result", {}),
                "official_checklist_context": official_context,
            }
            with st.spinner("2차 상담 질문을 생성하고 있습니다..."):
                result = call_llm_with_validation(
                    build_counseling_question_system_prompt(),
                    build_counseling_question_user_prompt(payload),
                    validate_counseling_question_output,
                    build_counseling_question_repair_prompt,
                    validation_kwargs={"red_flag_result": red_flag_result, "counseling_consideration_areas": counseling_areas},
                )
            if result["success"]:
                st.session_state["generated_counseling_questions"] = result["data"]
                st.success("2차 상담 질문 생성이 완료되었습니다.")
                if result.get("warnings"):
                    st.warning("검증 경고: " + " / ".join(map(str, result["warnings"][:3])))
            else:
                st.error("상담 질문 생성에 실패했습니다: " + str(result.get("error")))
    data = st.session_state.get("generated_counseling_questions")
    if data:
        st.markdown(f"<div class='callout'>{data.get('counseling_focus_summary', '')}</div>", unsafe_allow_html=True)
        for q in data.get("recommended_questions", []):
            st.markdown(
                f"""
                <div class="recommend-card">
                    <div style="font-weight:900;">{q.get('question_id', '')}. {q.get('question', '')}</div>
                    <table class="info-table" style="margin-top:8px;">
                        <tr><th>질문 목적</th><td>{q.get('purpose', '')}</td></tr>
                        <tr><th>연결 영역</th><td>{q.get('linked_area', '')}</td></tr>
                        <tr><th>근거</th><td>{' / '.join(map(str, q.get('based_on', [])))}</td></tr>
                        <tr><th>교사 유의사항</th><td>{q.get('teacher_caution', '')}</td></tr>
                        <tr><th>추가 확인</th><td>{q.get('follow_up_if_needed', '')}</td></tr>
                    </table>
                </div>
                """,
                unsafe_allow_html=True,
            )
        if data.get("teacher_recording_guide"):
            st.write("상담 후 기록 가이드")
            for item in data.get("teacher_recording_guide", []):
                st.write("- " + str(item))
        with st.expander("생성 결과 JSON 원본"):
            st.json(data)
        st.download_button(
            "상담 질문 JSON 다운로드",
            data=_safe_json(data).encode("utf-8-sig"),
            file_name="counseling_questions_result.json",
            mime="application/json",
            use_container_width=True,
        )
    st.markdown("</div>", unsafe_allow_html=True)


# ------------------------------ 상담 결과 분석 ------------------------------
def build_counseling_analysis_payload(
    first_check_result: Dict[str, Any],
    active_deep_rules: List[Dict[str, Any]],
    generated_counseling_questions: Dict[str, Any],
    teacher_counseling_note: str,
    teacher_support_judgment: str,
    existing_support_info: str,
) -> Dict[str, Any]:
    return {
        "first_check_result": first_check_result,
        "active_deep_rules": active_deep_rules,
        "generated_counseling_questions": generated_counseling_questions,
        "counseling_consideration_areas": st.session_state.get("counseling_consideration_areas", []),
        "context_result": st.session_state.get("context_result", {}),
        "official_checklist_context": st.session_state.get("official_checklist_context", []),
        "teacher_counseling_note": teacher_counseling_note,
        "teacher_support_judgment": teacher_support_judgment,
        "existing_support_info": existing_support_info,
    }


def build_counseling_analysis_system_prompt() -> str:
    return """
너는 학생맞춤통합지원 업무를 돕는 교사용 AI 상담 결과 분석 보조도구이다.
교사가 입력한 2차 상담 결과 메모를 읽고 RAG 검색과 협의록 초안 생성에 사용할 수 있도록 핵심 정보를 구조화한다.
학생을 진단하거나 판정하지 말고, 상담 메모와 제공된 자료에 근거한 정보만 정리한다.
이 단계에서는 urgent_flag, Red Flag, 긴급확인 분기를 사용하지 않는다.
출력은 반드시 지정된 JSON 형식으로만 작성한다.
""".strip()


def build_counseling_analysis_user_prompt(payload: Dict[str, Any]) -> str:
    return f"""
아래 자료를 바탕으로 2차 상담 결과를 구조화하라.
이 단계의 목적은 기관 추천이나 협의록 완성이 아니라, 다음 단계인 RAG 검색과 협의록 초안 생성을 위한 구조화된 입력값을 만드는 것이다.
이 단계에서는 urgent_flag, Red Flag, 긴급확인 분기를 사용하지 않는다.

[1차 체크리스트 결과]
{_safe_json(payload.get('first_check_result'))}

[활성화된 심층 유도 분석]
{_safe_json(payload.get('active_deep_rules'))}

[AI가 생성한 2차 상담 질문]
{_safe_json(payload.get('generated_counseling_questions'))}

[교사의 2차 상담 결과 메모]
{payload.get('teacher_counseling_note')}

[교사의 지원 필요 판단]
{payload.get('teacher_support_judgment')}

[기존 지원 여부]
{payload.get('existing_support_info')}

출력 형식:
{{
  "analysis_summary": {{
    "one_sentence_summary": "상담 결과를 한 문장으로 요약",
    "support_needed": "현재 유지 / 추가 관찰 / 지원 검토 필요 / 판단 보류",
    "support_needed_reason": "지원 필요 판단의 근거",
    "analysis_note": "분석 시 주의할 점 또는 상담 메모의 한계"
  }},
  "primary_area": "진로 / 학업 / 심리정서 / 복지경제 / 공통",
  "key_signals": [
    {{"signal": "주요 신호", "linked_areas": ["심리정서"], "evidence_text": "교사 상담 메모의 실제 표현", "interpretation": "검토 방향"}}
  ],
  "rag_search_queries": [
    {{"query": "RAG 검색 질의", "target_collection": "policy_chunks / service_catalog / resource_catalog", "purpose": "검색 목적"}}
  ],
  "meeting_record_inputs": {{
    "counseling_summary": "협의록용 상담 요약",
    "discussion_points": ["논의 안건"],
    "teacher_confirmation_items": ["교사 확인사항"],
    "guardian_contact_considerations": ["보호자 상담 또는 동의 관련 확인사항"],
    "follow_up_items": ["후속 관찰 또는 사후관리 항목"]
  }},
  "safety_and_ethics_note": "AI 결과는 자동 판정이 아니라 교사와 학교 협의체 검토를 위한 참고자료입니다."
}}
""".strip()


def build_counseling_analysis_repair_prompt(validation_error: str, previous_output: str) -> str:
    return f"""
이전 출력은 상담 결과 분석 조건을 충족하지 못했습니다.
검증 실패 사유: {validation_error}
반드시 JSON 형식으로만 다시 작성하세요. urgent_flag, urgent_reasons, urgent_notice, 긴급확인 관련 필드는 출력하지 마세요.
지원 검토 필요인 경우 rag_search_queries를 최소 2개 이상 포함하세요. 상담 메모에 없는 사실을 만들지 마세요.

[이전 출력]
{previous_output}
""".strip()


def render_counseling_analysis_section() -> None:
    st.markdown("<div class='panel'><div class='panel-title'>2차 상담 결과 분석</div>", unsafe_allow_html=True)
    st.write("학생과 2차 상담을 진행한 뒤, 교사가 상담 결과를 자유롭게 기록하면 AI가 RAG 검색과 협의록 작성을 위한 구조화 정보를 생성합니다.")
    note = st.text_area(
        "2차 상담 결과 메모",
        value=st.session_state.get("teacher_counseling_note", ""),
        placeholder="학생은 수업 시간에 엎드리는 이유가 잠을 잘 못 자서라고 말함. 친구들과 어울리는 것이 부담스럽고 쉬는 시간에는 혼자 있는 것이 편하다고 답함. 앞으로 하고 싶은 일은 잘 모르겠다고 말함.",
        height=130,
        key="teacher_counseling_note_input",
    )
    col1, col2 = st.columns(2)
    with col1:
        judgment = st.selectbox("교사의 지원 필요 판단", ["현재 유지", "추가 관찰", "지원 검토 필요", "판단 보류"], index=2, key="teacher_support_judgment_input")
    with col2:
        existing = st.text_input("기존 지원 여부", value=st.session_state.get("existing_support_info", "기존 지원 없음"), placeholder="예: 기존 지원 없음 / 현재 Wee클래스 상담 중 / 확인 필요")
    if not get_gemini_api_key():
        st.warning("Gemini API 키가 설정되어 있지 않습니다. Streamlit secrets 또는 환경변수에 GEMINI_API_KEY를 설정해 주세요.")
    if st.button("상담 결과 분석하기", type="primary", use_container_width=True, key="btn_analyze_note"):
        if not note.strip():
            st.warning("상담 결과 메모를 입력해 주세요.")
        elif not st.session_state.get("generated_counseling_questions"):
            st.warning("먼저 2차 상담 질문을 생성해 주세요.")
        elif not st.session_state.get("first_check_result"):
            st.warning("먼저 1차 체크리스트를 완료해 주세요.")
        elif not get_gemini_api_key():
            st.warning("API 키가 설정되지 않아 상담 결과 분석을 실행할 수 없습니다.")
        else:
            payload = build_counseling_analysis_payload(
                st.session_state["first_check_result"],
                st.session_state.get("active_deep_rules", []),
                st.session_state["generated_counseling_questions"],
                note,
                judgment,
                existing,
            )
            with st.spinner("상담 결과 메모를 구조화하고 있습니다..."):
                result = call_llm_with_validation(
                    build_counseling_analysis_system_prompt(),
                    build_counseling_analysis_user_prompt(payload),
                    validate_counseling_analysis_output,
                    build_counseling_analysis_repair_prompt,
                    validation_kwargs={"teacher_counseling_note": note},
                )
            if result["success"]:
                st.session_state["structured_counseling_analysis"] = result["data"]
                st.session_state["teacher_counseling_note"] = note
                st.session_state["teacher_support_judgment"] = judgment
                st.session_state["existing_support_info"] = existing
                st.success("상담 결과 분석이 완료되었습니다.")
                if result.get("warnings"):
                    st.warning("검증 경고: " + " / ".join(map(str, result["warnings"][:3])))
            else:
                st.error("상담 결과 분석에 실패했습니다: " + str(result.get("error")))
    data = st.session_state.get("structured_counseling_analysis")
    if data:
        summ = data.get("analysis_summary", {})
        st.markdown(f"<div class='callout'>{summ.get('one_sentence_summary', '')}</div>", unsafe_allow_html=True)
        c1, c2 = st.columns(2)
        with c1:
            st.markdown(metric_card("지원 필요 판단", summ.get("support_needed", "-"), summ.get("support_needed_reason", "")), unsafe_allow_html=True)
        with c2:
            st.markdown(metric_card("우선 지원 영역", data.get("primary_area", "-"), "RAG 서비스 카탈로그 검색 기준"), unsafe_allow_html=True)
        if data.get("key_signals"):
            st.dataframe(pd.DataFrame(data["key_signals"]), use_container_width=True, hide_index=True)
        if data.get("rag_search_queries"):
            st.dataframe(pd.DataFrame(data["rag_search_queries"]), use_container_width=True, hide_index=True)
        with st.expander("협의록 입력 자료"):
            st.json(data.get("meeting_record_inputs", {}))
        with st.expander("분석 결과 JSON 원본"):
            st.json(data)
        st.download_button("상담 분석 JSON 다운로드", _safe_json(data).encode("utf-8-sig"), "structured_counseling_analysis.json", "application/json", use_container_width=True)
        st.info("다음 단계에서는 이 구조화 결과의 primary_area, key_signals, rag_search_queries를 활용하여 공식 자료, 서비스 카탈로그, 지역기관 DB를 검색합니다.")
    st.markdown("</div>", unsafe_allow_html=True)


# ------------------------------ RAG 검색 ------------------------------
EMBEDDING_MODEL_NAME = "sentence-transformers/distiluse-base-multilingual-cased-v1"


def parse_pipe_list(value: Any) -> List[str]:
    if value is None:
        return []
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return []
    for sep in [",", ";", "/"]:
        text = text.replace(sep, "|")
    return [x.strip() for x in text.split("|") if x.strip()]


def normalize_school_level(value: Any) -> str:
    text = normalize_text(value)
    if "초" in text:
        return "초"
    if "중" in text:
        return "중"
    if "고" in text:
        return "고"
    return text


def safe_float(value: Any) -> Optional[float]:
    try:
        if value is None or str(value).strip() == "":
            return None
        v = float(value)
        if math.isnan(v):
            return None
        return v
    except Exception:
        return None


def get_allowed_districts(selected_school_district: str, adjacency_map: Dict[str, Any]) -> List[str]:
    if not selected_school_district:
        return []
    if "district_adjacency" in adjacency_map and isinstance(adjacency_map["district_adjacency"], dict):
        adjacency_map = adjacency_map["district_adjacency"]
    return [selected_school_district] + list(adjacency_map.get(selected_school_district, []))


def is_common_or_wide_area_candidate(metadata: Dict[str, Any]) -> bool:
    text = " ".join(str(metadata.get(k, "")) for k in ["district", "filter_region_scope", "region_scope", "resource_scope", "filter_district_list"])
    return any(x in text for x in ["서울공통", "광역", "전체", "서울시 전체", "공통"])


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def distance_to_similarity(distance: Any) -> float:
    d = float(distance or 0)
    if 0 <= d <= 1:
        return max(0.0, min(1.0, 1.0 - d))
    return max(0.0, min(1.0, 1.0 / (1.0 + d)))


def ensure_chroma_db() -> Optional[Path]:
    chroma_dir = APP_DIR / "chroma_db"
    if chroma_dir.exists():
        return chroma_dir
    zip_url = None
    try:
        zip_url = st.secrets.get("CHROMA_DB_ZIP_URL", None)
    except Exception:
        zip_url = None
    zip_url = zip_url or os.getenv("CHROMA_DB_ZIP_URL")
    if not zip_url:
        return None
    try:
        import requests
        import zipfile
        tmp_zip = APP_DIR / "chroma_db.zip"
        with st.spinner("GitHub Release에서 Chroma DB를 내려받고 있습니다..."):
            r = requests.get(zip_url, timeout=120)
            r.raise_for_status()
            tmp_zip.write_bytes(r.content)
            with zipfile.ZipFile(tmp_zip, "r") as zf:
                zf.extractall(APP_DIR)
        if chroma_dir.exists():
            return chroma_dir
    except Exception as exc:
        st.error(f"Chroma DB zip 다운로드 또는 압축 해제에 실패했습니다: {exc}")
        return None
    return chroma_dir if chroma_dir.exists() else None


@st.cache_resource(show_spinner=False)
def get_embedding_model():
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer(EMBEDDING_MODEL_NAME)


@st.cache_resource(show_spinner=False)
def init_chroma_client_cached(chroma_path_str: str):
    import chromadb
    return chromadb.PersistentClient(path=chroma_path_str)


def query_chroma_collection(client: Any, collection_name: str, query: str, n_results: int = 10) -> List[Dict[str, Any]]:
    collection = client.get_collection(collection_name)
    model = get_embedding_model()
    emb = model.encode([query], normalize_embeddings=True).tolist()
    result = collection.query(query_embeddings=emb, n_results=n_results, include=["documents", "metadatas", "distances"])
    out: List[Dict[str, Any]] = []
    ids = result.get("ids", [[]])[0]
    docs = result.get("documents", [[]])[0]
    metas = result.get("metadatas", [[]])[0]
    dists = result.get("distances", [[]])[0]
    for i, doc_id in enumerate(ids):
        meta = metas[i] if i < len(metas) and metas[i] is not None else {}
        out.append({"id": doc_id, "document_text": docs[i] if i < len(docs) else "", "metadata": meta, "distance": dists[i] if i < len(dists) else None, "matched_query": query, "collection": collection_name})
    return out


def result_to_simple(item: Dict[str, Any]) -> Dict[str, Any]:
    meta = item.get("metadata", {}) or {}
    text = item.get("document_text", "") or ""
    out = {"id": item.get("id"), "text": text, "text_summary": text[:220], "distance": item.get("distance"), "matched_query": item.get("matched_query")}
    out.update({k: meta.get(k, "") for k in meta.keys()})
    # 자주 쓰는 키 보정
    out["title"] = out.get("title") or out.get("source_title") or out.get("service_type") or out.get("resource_name") or "-"
    out["source_doc"] = out.get("source_doc") or out.get("document_name") or out.get("source") or "-"
    out["support_area"] = normalize_area_name(out.get("support_area") or out.get("linked_area") or out.get("filter_support_area_list") or "")
    return out


def make_fallback_queries(analysis: Dict[str, Any]) -> List[Dict[str, str]]:
    area = analysis.get("primary_area") or "공통"
    signals = " ".join([str(s.get("signal", "")) for s in analysis.get("key_signals", [])[:2]])
    return [
        {"query": f"{area} 학생맞춤통합지원 통합지원 절차 {signals}", "target_collection": "policy_chunks", "purpose": "공식 지원 절차 근거 검색"},
        {"query": f"{area} 지원서비스 상담 학습 진로 복지 {signals}", "target_collection": "service_catalog", "purpose": "서비스 유형 검색"},
        {"query": f"{area} 상담 지원 지역기관 학생 {signals}", "target_collection": "resource_catalog", "purpose": "지역기관 후보 검색"},
    ]


def filter_resource_candidates(candidates: List[Dict[str, Any]], primary_area: str, selected_school_level: str, selected_school_district: str, allowed_districts: List[str], existing_support_info: str) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    filtered: List[Dict[str, Any]] = []
    excluded: List[Dict[str, str]] = []
    for item in candidates:
        meta = item.get("metadata", {}) or {}
        support_list = [normalize_area_name(x) for x in parse_pipe_list(meta.get("filter_support_area_list") or meta.get("support_area") or meta.get("linked_area"))]
        support_pass = bool(primary_area in support_list or "공통" in support_list or not support_list)
        level_list = [normalize_school_level(x) for x in parse_pipe_list(meta.get("filter_school_level_list") or meta.get("target_school_levels") or meta.get("target_school_level"))]
        selected_level = normalize_school_level(selected_school_level)
        level_pass = bool(not level_list or "전체" in level_list or "공통" in level_list or selected_level in level_list)
        dist_list = parse_pipe_list(meta.get("filter_district_list") or meta.get("district") or meta.get("자치구"))
        district = meta.get("district") or meta.get("자치구") or (dist_list[0] if dist_list else "")
        district_pass = bool(is_common_or_wide_area_candidate(meta) or not allowed_districts or any(d in allowed_districts for d in dist_list) or district in allowed_districts)
        reasons = []
        if not support_pass:
            reasons.append("지원 영역 불일치")
        if not level_pass:
            reasons.append("학교급 불일치")
        if not district_pass:
            reasons.append("지역 범위 밖")
        item["support_area_filter_pass"] = support_pass
        item["school_level_filter_pass"] = level_pass
        item["district_filter_pass"] = district_pass
        item["filter_pass"] = support_pass and level_pass and district_pass
        item["filter_exclusion_reason"] = ", ".join(reasons)
        name = meta.get("resource_name") or meta.get("기관명") or meta.get("name") or item.get("id")
        category = meta.get("resource_category") or meta.get("service_type") or ""
        if existing_support_info and any(k in existing_support_info for k in ["Wee", "위클래스", "위센터"]) and any(k in str(category) + str(name) for k in ["Wee", "위", "위센터"]):
            item["existing_support_status"] = "기존 지원 점검"
        else:
            item["existing_support_status"] = "신규 연계 후보" if not existing_support_info or "없음" in existing_support_info else "확인 필요"
        if item["filter_pass"]:
            filtered.append(item)
        else:
            excluded.append({"resource_name": str(name), "reason": item["filter_exclusion_reason"]})
    summary: Dict[str, Any] = {"total_candidates": len(candidates), "passed": len(filtered), "excluded": len(excluded), "excluded_samples": excluded[:30]}
    for reason in ["지원 영역 불일치", "학교급 불일치", "지역 범위 밖"]:
        summary[reason] = sum(1 for x in excluded if reason in x.get("reason", ""))
    return filtered, summary


def calculate_location_score(candidate: Dict[str, Any], selected_school_district: str, school_lat: Optional[float], school_lon: Optional[float], allowed_districts: List[str]) -> Tuple[float, Optional[float]]:
    meta = candidate.get("metadata", {}) or {}
    district = meta.get("district") or meta.get("자치구") or ""
    lat = safe_float(meta.get("latitude") or meta.get("위도"))
    lon = safe_float(meta.get("longitude") or meta.get("경도"))
    distance = None
    if school_lat is not None and school_lon is not None and lat is not None and lon is not None:
        distance = haversine_km(school_lat, school_lon, lat, lon)
    if district == selected_school_district:
        if distance is not None and distance <= 3:
            return 20.0, round(distance, 2)
        return 18.0, round(distance, 2) if distance is not None else None
    if district in allowed_districts:
        if distance is not None and distance <= 5:
            return 16.0, round(distance, 2)
        return 14.0, round(distance, 2) if distance is not None else None
    if is_common_or_wide_area_candidate(meta):
        return 10.0, round(distance, 2) if distance is not None else None
    if not district:
        return 8.0, round(distance, 2) if distance is not None else None
    return 5.0, round(distance, 2) if distance is not None else None


def rank_resource_candidates(filtered_candidates: List[Dict[str, Any]], selected_school_info: Dict[str, Any], allowed_districts: List[str]) -> List[Dict[str, Any]]:
    school_lat = safe_float(selected_school_info.get("위도"))
    school_lon = safe_float(selected_school_info.get("경도"))
    district = selected_school_info.get("자치구", "")
    dedup: Dict[str, Dict[str, Any]] = {}
    for item in filtered_candidates:
        meta = item.get("metadata", {}) or {}
        name = meta.get("resource_name") or meta.get("기관명") or meta.get("name") or item.get("id")
        phone = meta.get("phone") or meta.get("대표전화") or meta.get("전화번호") or ""
        address = meta.get("address") or meta.get("주소") or ""
        key = f"{name}|{phone or address}"
        student_fit = distance_to_similarity(item.get("distance")) * 80
        location_score, distance_km = calculate_location_score(item, district, school_lat, school_lon, allowed_districts)
        score = student_fit + location_score
        candidate = {
            "resource_name": name,
            "resource_category": meta.get("resource_category") or meta.get("service_type") or "-",
            "support_area": normalize_area_name(meta.get("support_area") or meta.get("linked_area") or meta.get("filter_support_area_list") or "공통"),
            "district": meta.get("district") or meta.get("자치구") or "",
            "education_office": meta.get("education_office") or meta.get("교육지원청") or "",
            "address": address,
            "phone": phone,
            "homepage": meta.get("homepage") or meta.get("homepage_url") or meta.get("홈페이지") or "",
            "latitude": safe_float(meta.get("latitude") or meta.get("위도")),
            "longitude": safe_float(meta.get("longitude") or meta.get("경도")),
            "distance_km": distance_km,
            "student_fit_score": round(student_fit, 1),
            "location_score": round(location_score, 1),
            "recommendation_score": round(score, 1),
            "recommendation_fit": "높음" if score >= 85 else ("보통" if score >= 70 else ("보조 검토" if score >= 55 else "낮음")),
            "existing_support_status": item.get("existing_support_status", "확인 필요"),
            "score_breakdown": {"student_fit_score": round(student_fit, 1), "location_score": round(location_score, 1)},
            "matched_query": item.get("matched_query", ""),
            "document_text": item.get("document_text", ""),
            "metadata": meta,
        }
        if key not in dedup or candidate["student_fit_score"] > dedup[key]["student_fit_score"]:
            dedup[key] = candidate
    ranked = sorted(dedup.values(), key=lambda x: x["recommendation_score"], reverse=True)
    for i, item in enumerate(ranked, start=1):
        item["rank"] = i
    return ranked[:5]


def run_rag_search() -> Optional[Dict[str, Any]]:
    analysis = st.session_state.get("structured_counseling_analysis")
    if not analysis:
        st.warning("먼저 2차 상담 결과 분석을 실행해 주세요.")
        return None
    school = st.session_state.get("selected_school_info", {})
    district = school.get("자치구", "")
    level = school.get("학교급", "")
    if not district:
        st.warning("학교 자치구 정보가 없어 지역 필터를 적용할 수 없습니다.")
    chroma_dir = ensure_chroma_db()
    if chroma_dir is None or not chroma_dir.exists():
        st.error("chroma_db 폴더가 없습니다. GitHub Release zip URL을 CHROMA_DB_ZIP_URL에 설정하거나 chroma_db 폴더를 업로드해 주세요.")
        return None
    try:
        client = init_chroma_client_cached(str(chroma_dir))
    except Exception as exc:
        st.error(f"Chroma DB 연결에 실패했습니다: {exc}")
        return None
    adjacency = load_json_with_fallback(JSON_PATHS.get("district_adjacency", []))
    allowed_districts = get_allowed_districts(district, adjacency)
    existing = st.session_state.get("existing_support_info", "기존 지원 없음")
    queries = analysis.get("rag_search_queries") or []
    if not queries:
        queries = make_fallback_queries(analysis)
    if not any(q.get("target_collection") == "policy_chunks" for q in queries):
        queries.extend([q for q in make_fallback_queries(analysis) if q["target_collection"] == "policy_chunks"])
    if not any(q.get("target_collection") == "service_catalog" for q in queries):
        queries.extend([q for q in make_fallback_queries(analysis) if q["target_collection"] == "service_catalog"])
    if not any(q.get("target_collection") == "resource_catalog" for q in queries):
        queries.extend([q for q in make_fallback_queries(analysis) if q["target_collection"] == "resource_catalog"])

    policy_items: List[Dict[str, Any]] = []
    service_items: List[Dict[str, Any]] = []
    resource_raw: List[Dict[str, Any]] = []
    for q in queries:
        collection = q.get("target_collection")
        query = q.get("query")
        try:
            if collection == "policy_chunks":
                policy_items.extend([result_to_simple(x) for x in query_chroma_collection(client, "policy_chunks", query, n_results=6)])
            elif collection == "service_catalog":
                service_items.extend([result_to_simple(x) for x in query_chroma_collection(client, "service_catalog", query, n_results=6)])
            elif collection == "resource_catalog":
                resource_raw.extend(query_chroma_collection(client, "resource_catalog", query, n_results=50))
        except Exception as exc:
            st.warning(f"{collection} 검색 중 오류: {exc}")
    primary_area = normalize_area_name(analysis.get("primary_area", "공통")) or "공통"
    filtered, debug = filter_resource_candidates(resource_raw, primary_area, level, district, allowed_districts, existing)
    ranked = rank_resource_candidates(filtered, school, allowed_districts)
    results = {
        "policy_evidence": policy_items[:8],
        "service_catalog_results": service_items[:8],
        "ranked_resources": ranked,
        "filter_debug_summary": debug,
        "search_context": {
            "primary_area": primary_area,
            "selected_school_district": district,
            "selected_school_level": normalize_school_level(level),
            "allowed_districts": allowed_districts,
            "existing_support_info": existing,
            "used_query_count": len(queries),
        },
    }
    st.session_state["rag_search_results"] = results
    return results


def render_rag_search_section() -> None:
    st.markdown("<div class='panel'><div class='panel-title'>RAG 기반 공식 근거·지역기관 후보 검색</div>", unsafe_allow_html=True)
    st.write("상담 결과 분석에서 생성된 검색어를 바탕으로 공식 자료, 서비스 카탈로그, 지역기관 DB를 검색합니다.")
    analysis = st.session_state.get("structured_counseling_analysis")
    if not analysis:
        st.info("2차 상담 결과 분석이 완료되면 RAG 검색을 실행할 수 있습니다.")
        st.markdown("</div>", unsafe_allow_html=True)
        return
    school = st.session_state.get("selected_school_info", {})
    adjacency = load_json_with_fallback(JSON_PATHS.get("district_adjacency", []))
    allowed = get_allowed_districts(school.get("자치구", ""), adjacency)
    c1, c2, c3, c4 = st.columns(4)
    with c1: st.markdown(metric_card("우선 영역", analysis.get("primary_area", "-"), "상담 분석 결과"), unsafe_allow_html=True)
    with c2: st.markdown(metric_card("학교 자치구", school.get("자치구", "-"), "지역 필터 기준"), unsafe_allow_html=True)
    with c3: st.markdown(metric_card("학교급", school.get("학교급", "-"), "대상 필터 기준"), unsafe_allow_html=True)
    with c4: st.markdown(metric_card("기존 지원", st.session_state.get("existing_support_info", "-"), "중복 지원 점검"), unsafe_allow_html=True)
    st.caption("인접 자치구: " + (", ".join(allowed[1:]) if len(allowed) > 1 else "정보 없음"))
    if st.button("RAG 검색 실행하기", type="primary", use_container_width=True, key="btn_run_rag"):
        with st.spinner("공식 근거와 지역기관 후보를 검색하고 있습니다..."):
            run_rag_search()
    results = st.session_state.get("rag_search_results")
    if results:
        st.write("공식 근거 검색 결과")
        pe = pd.DataFrame(results.get("policy_evidence", []))
        if not pe.empty:
            cols = [c for c in ["title", "source_doc", "chunk_type", "support_area", "source_page", "text_summary"] if c in pe.columns]
            st.dataframe(pe[cols], use_container_width=True, hide_index=True)
        st.write("서비스 카탈로그 검색 결과")
        sc = pd.DataFrame(results.get("service_catalog_results", []))
        if not sc.empty:
            cols = [c for c in ["service_type", "support_area", "recommended_conditions", "text_summary"] if c in sc.columns]
            st.dataframe(sc[cols], use_container_width=True, hide_index=True)
        st.write("지역기관 후보")
        if not results.get("ranked_resources"):
            st.warning("현재 필터 조건에서 적합한 기관 후보가 없습니다. 보조 영역 검색 또는 지역 범위 확장이 필요할 수 있습니다.")
        for r in results.get("ranked_resources", []):
            st.markdown(
                f"""
                <div class="recommend-card">
                    <div style="font-weight:900;"><span class="recommend-rank">{r.get('rank')}</span>{r.get('resource_name')}</div>
                    <table class="info-table" style="margin-top:8px;">
                        <tr><th>기관유형</th><td>{r.get('resource_category')}</td><th>지원 영역</th><td>{r.get('support_area')}</td></tr>
                        <tr><th>자치구</th><td>{r.get('district')}</td><th>거리</th><td>{r.get('distance_km')}</td></tr>
                        <tr><th>주소</th><td colspan="3">{r.get('address')}</td></tr>
                        <tr><th>전화번호</th><td>{r.get('phone')}</td><th>홈페이지</th><td>{r.get('homepage')}</td></tr>
                        <tr><th>추천 적합도</th><td>{r.get('recommendation_fit')}</td><th>총점</th><td>{r.get('recommendation_score')}</td></tr>
                        <tr><th>학생 상황 적합도</th><td>{r.get('student_fit_score')}</td><th>지역·접근성</th><td>{r.get('location_score')}</td></tr>
                        <tr><th>기존 지원 상태</th><td colspan="3">{r.get('existing_support_status')}</td></tr>
                    </table>
                </div>
                """,
                unsafe_allow_html=True,
            )
        with st.expander("상세 점수 및 필터링 로그"):
            st.json(results.get("filter_debug_summary", {}))
            st.json(results.get("ranked_resources", []))
        with st.expander("RAG 검색 결과 JSON 원본"):
            st.json(results)
        st.download_button("RAG 검색 결과 JSON 다운로드", _safe_json(results).encode("utf-8-sig"), "rag_search_results.json", "application/json", use_container_width=True)
    st.markdown("</div>", unsafe_allow_html=True)


# ------------------------------ 기관 추천 이유 생성 ------------------------------
def build_resource_recommendation_payload(structured_counseling_analysis: Dict[str, Any], first_check_result: Dict[str, Any], context_result: Dict[str, Any], existing_support_info: str, rag_search_results: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "structured_counseling_analysis": structured_counseling_analysis,
        "first_check_result": first_check_result,
        "context_result": context_result,
        "existing_support_info": existing_support_info,
        "policy_evidence": rag_search_results.get("policy_evidence", []),
        "service_catalog_results": rag_search_results.get("service_catalog_results", []),
        "ranked_resources": rag_search_results.get("ranked_resources", []),
        "search_context": rag_search_results.get("search_context", {}),
    }


def build_resource_recommendation_system_prompt() -> str:
    return """
너는 학생맞춤통합지원 업무를 돕는 교사용 AI 기관 추천 설명 보조도구이다.
제공된 공식 근거, 서비스 유형, 지역기관 후보 안에서만 교사가 검토할 수 있는 기관 추천 설명을 작성한다.
새로운 기관명, 제도, 연락처, 주소를 만들지 않는다. Python 코드가 정한 ranked_resources 순서를 바꾸지 않는다.
학생을 진단하거나 판정하지 않고, 추천은 교사와 학교 협의체가 검토할 후보로 표현한다.
이 단계에서는 Red Flag, urgent_flag, 긴급확인 관련 내용을 사용하지 않는다.
출력은 반드시 지정된 JSON 형식으로 작성한다.
""".strip()


def build_resource_recommendation_user_prompt(payload: Dict[str, Any]) -> str:
    return f"""
아래 자료를 바탕으로 학생맞춤통합지원 지역기관 추천 설명을 생성하라.
기관을 새로 찾지 말고 이미 RAG 검색과 Python 필터링·순위화를 통해 추려진 후보를 설명하라.
ranked_resources 입력 순서를 반드시 유지하라.

[상담 결과 구조화 정보]
{_safe_json(payload.get('structured_counseling_analysis'))}

[1차 체크리스트 결과]
{_safe_json(payload.get('first_check_result'))}

[학교·지역 맥락 참고 정보]
{_safe_json(payload.get('context_result'))}

[기존 지원 여부]
{payload.get('existing_support_info')}

[RAG 검색 결과: 공식 근거]
{_safe_json(payload.get('policy_evidence'))}

[RAG 검색 결과: 서비스 카탈로그 후보]
{_safe_json(payload.get('service_catalog_results'))}

[RAG 검색 결과: 지역기관 후보]
{_safe_json(payload.get('ranked_resources'))}

출력 형식:
{{
  "recommendation_summary": {{
    "one_sentence_summary": "추천 결과를 한 문장으로 요약",
    "primary_area": "진로 / 학업 / 심리정서 / 복지경제 / 공통",
    "support_needed_status": "현재 유지 / 추가 관찰 / 지원 검토 필요 / 판단 보류",
    "recommendation_mode": "일반 추천 / 기존 지원 점검 / 후보 부족",
    "summary_for_teacher": "교사용 요약 설명"
  }},
  "recommended_resources": [
    {{
      "rank": 1,
      "service_type": "추천서비스 유형",
      "resource_name": "기관명",
      "resource_category": "기관유형",
      "linked_area": "진로 / 학업 / 심리정서 / 복지경제 / 공통 중 하나",
      "district": "자치구",
      "education_office": "교육지원청",
      "address": "주소",
      "phone": "전화번호",
      "homepage": "홈페이지",
      "distance_km": null,
      "recommendation_fit": "높음 / 보통 / 보조 검토",
      "recommendation_score": null,
      "score_breakdown": {{"student_fit_score": null, "location_score": null}},
      "existing_support_status": "신규 연계 후보 / 기존 지원 점검 / 확인 필요",
      "recommendation_reasons": ["추천 이유"],
      "student_context_basis": ["상담 메모 또는 체크리스트와 연결되는 근거"],
      "official_basis": [{{"basis_title": "공식 근거 제목", "basis_summary": "요약", "source_doc": "출처 문서명", "source_page": "출처 페이지"}}],
      "location_or_access_basis": "지역·접근성 관련 설명",
      "teacher_confirmation_items": ["교사가 확인해야 할 사항"],
      "referral_cautions": ["연계 시 유의사항"],
      "meeting_record_sentence": "협의록에 넣을 수 있는 문장"
    }}
  ],
  "if_no_suitable_resource": {{"no_resource_flag": false, "reason": "", "suggested_next_steps": []}},
  "overall_teacher_checklist": ["추천 전 확인사항 1", "확인사항 2", "확인사항 3"],
  "rag_trace_summary": {{"used_policy_chunks": [], "used_service_catalog_items": [], "used_resource_candidates": [], "note": "제공된 RAG 결과 안에서만 작성"}},
  "safety_and_ethics_note": "AI 추천은 자동 결정이 아니라 교사와 학교 협의체 검토를 위한 참고자료입니다."
}}
""".strip()


def build_resource_recommendation_repair_prompt(validation_error: str, previous_output: str) -> str:
    return f"""
이전 출력은 RAG 기반 기관 추천 설명 조건을 충족하지 못했습니다.
검증 실패 사유: {validation_error}
반드시 JSON 형식으로만 다시 작성하세요.
ranked_resources에 제공된 기관 후보 안에서만 작성하고, 기관명·주소·전화번호·홈페이지를 새로 만들지 말고, 추천 순서를 바꾸지 마세요.
Red Flag, urgent_flag, urgent_notice, 긴급확인 관련 내용은 출력하지 마세요.

[이전 출력]
{previous_output}
""".strip()


def render_resource_recommendation_section() -> None:
    st.markdown("<div class='panel'><div class='panel-title'>AI 기관 추천 이유 설명</div>", unsafe_allow_html=True)
    st.write("RAG 검색과 필터링·순위화 결과를 바탕으로, 교사가 검토할 수 있는 기관 추천 이유와 확인사항을 생성합니다.")
    if not st.session_state.get("rag_search_results"):
        st.info("먼저 RAG 검색을 실행해 주세요.")
        st.markdown("</div>", unsafe_allow_html=True)
        return
    if not st.session_state.get("structured_counseling_analysis"):
        st.warning("먼저 2차 상담 결과 분석을 실행해 주세요.")
        st.markdown("</div>", unsafe_allow_html=True)
        return
    if not get_gemini_api_key():
        st.warning("Gemini API 키가 설정되어 있지 않습니다. Streamlit secrets 또는 환경변수에 GEMINI_API_KEY를 설정해 주세요.")
    if st.button("기관 추천 이유 생성하기", type="primary", use_container_width=True, key="btn_resource_reason"):
        if not get_gemini_api_key():
            st.warning("API 키가 설정되지 않아 기관 추천 이유 생성을 실행할 수 없습니다.")
        else:
            rag = st.session_state["rag_search_results"]
            payload = build_resource_recommendation_payload(
                st.session_state.get("structured_counseling_analysis", {}),
                st.session_state.get("first_check_result", {}),
                st.session_state.get("context_result", {}),
                st.session_state.get("existing_support_info", "기존 지원 없음"),
                rag,
            )
            with st.spinner("기관 추천 이유를 생성하고 있습니다..."):
                result = call_llm_with_validation(
                    build_resource_recommendation_system_prompt(),
                    build_resource_recommendation_user_prompt(payload),
                    validate_resource_recommendation_output,
                    build_resource_recommendation_repair_prompt,
                    validation_kwargs={"ranked_resources": rag.get("ranked_resources", []), "policy_evidence": rag.get("policy_evidence", [])},
                )
            if result["success"]:
                st.session_state["resource_recommendation_explanation"] = result["data"]
                st.success("기관 추천 이유 설명 생성이 완료되었습니다.")
                if result.get("warnings"):
                    st.warning("검증 경고: " + " / ".join(map(str, result["warnings"][:3])))
            else:
                st.error("기관 추천 이유 생성에 실패했습니다: " + str(result.get("error")))
    data = st.session_state.get("resource_recommendation_explanation")
    if data:
        summ = data.get("recommendation_summary", {})
        st.markdown(f"<div class='callout'>{summ.get('one_sentence_summary', '')}</div>", unsafe_allow_html=True)
        if data.get("if_no_suitable_resource", {}).get("no_resource_flag"):
            st.warning(data.get("if_no_suitable_resource", {}).get("reason", "후보가 부족합니다."))
            for step in data.get("if_no_suitable_resource", {}).get("suggested_next_steps", []):
                st.write("- " + str(step))
        for r in data.get("recommended_resources", []):
            st.markdown(
                f"""
                <div class="recommend-card">
                    <div style="font-weight:900;"><span class="recommend-rank">{r.get('rank')}</span>{r.get('resource_name')}</div>
                    <table class="info-table" style="margin-top:8px;">
                        <tr><th>기관유형</th><td>{r.get('resource_category')}</td><th>서비스 유형</th><td>{r.get('service_type')}</td></tr>
                        <tr><th>지원 영역</th><td>{r.get('linked_area')}</td><th>추천 적합도</th><td>{r.get('recommendation_fit')}</td></tr>
                        <tr><th>주소</th><td colspan="3">{r.get('address')}</td></tr>
                        <tr><th>전화번호</th><td>{r.get('phone')}</td><th>거리</th><td>{r.get('distance_km')}</td></tr>
                        <tr><th>추천 이유</th><td colspan="3">{' / '.join(map(str, r.get('recommendation_reasons', [])))}</td></tr>
                        <tr><th>교사 확인사항</th><td colspan="3">{' / '.join(map(str, r.get('teacher_confirmation_items', [])))}</td></tr>
                        <tr><th>협의록 문장</th><td colspan="3">{r.get('meeting_record_sentence', '')}</td></tr>
                    </table>
                </div>
                """,
                unsafe_allow_html=True,
            )
        if data.get("overall_teacher_checklist"):
            st.write("공통 교사 확인사항")
            for x in data.get("overall_teacher_checklist", []): st.write("- " + str(x))
        with st.expander("RAG 추적 요약"):
            st.json(data.get("rag_trace_summary", {}))
        with st.expander("기관 추천 설명 JSON 원본"):
            st.json(data)
        st.download_button("기관 추천 설명 JSON 다운로드", _safe_json(data).encode("utf-8-sig"), "resource_recommendation_explanation.json", "application/json", use_container_width=True)
        st.info("다음 단계에서는 이 기관 추천 설명과 상담 결과 분석 내용을 공식 서식에 맞춰 협의록 초안으로 생성합니다.")
    st.markdown("</div>", unsafe_allow_html=True)


# ------------------------------ 문서 생성 ------------------------------
def build_document_generation_payload(structured_counseling_analysis: Dict[str, Any], resource_recommendation_explanation: Dict[str, Any], rag_search_results: Dict[str, Any], first_check_result: Dict[str, Any], document_type: str) -> Dict[str, Any]:
    return {
        "document_type": document_type,
        "first_check_result": first_check_result,
        "structured_counseling_analysis": structured_counseling_analysis,
        "resource_recommendation_explanation": resource_recommendation_explanation,
        "policy_evidence": rag_search_results.get("policy_evidence", []),
        "recommended_resources": resource_recommendation_explanation.get("recommended_resources", []),
    }


def build_document_generation_system_prompt() -> str:
    return """
너는 학생맞춤통합지원 업무를 돕는 문서 초안 작성 보조도구이다.
제공된 1차 체크리스트 결과, 상담 결과 분석, RAG 기관 추천 설명, 공식 근거를 바탕으로 정해진 문서 서식의 서술형 내용을 작성한다.
개인정보를 생성하거나 추정하지 않고, 기관명은 제공된 추천기관 결과 안에서만 사용한다.
학생을 진단하거나 판정하지 않으며, 협의체가 검토할 초안으로 작성한다.
출력은 반드시 지정된 JSON 형식으로만 작성한다.
""".strip()


def build_document_generation_user_prompt(payload: Dict[str, Any]) -> str:
    return f"""
아래 자료를 바탕으로 협의록과 학생성장기록지에 들어갈 서술형 내용을 JSON으로 작성하라.
개인정보는 제공하지 않는다. 학생명, 생년월일, 연락처, 주소는 Python이 나중에 직접 삽입한다.
기관명은 제공된 추천기관 안에서만 사용한다.

[문서 생성 대상]
{payload.get('document_type')}

[1차 체크리스트 결과]
{_safe_json(payload.get('first_check_result'))}

[상담 결과 분석]
{_safe_json(payload.get('structured_counseling_analysis'))}

[RAG 기관 추천 설명]
{_safe_json(payload.get('resource_recommendation_explanation'))}

[공식 근거 및 추천기관]
{_safe_json(payload.get('rag_search_results'))}

출력 JSON 형식:
{{
  "meeting_record": {{
    "agenda": "회의 안건 초안",
    "meeting_content": "대상 학생 협의 내용 초안",
    "decision_items": ["결정사항 1", "결정사항 2"],
    "followup_plan": ["향후계획 1", "향후계획 2"]
  }},
  "student_growth_record": {{
    "student_difficulties": "학생의 어려움 서술 초안",
    "internal_resource_summary": "내부자원 활용 방향 서술",
    "external_resource_summary": "외부자원 연계 방향 서술",
    "monthly_support_records": [
      {{"month": "3월", "content": "맞춤지원 현황 초안"}},
      {{"month": "4월", "content": ""}},
      {{"month": "5월", "content": ""}},
      {{"month": "6월", "content": ""}}
    ],
    "comprehensive_evaluation": "학생성장 종합평가 초안",
    "closure_reason": "학생지원 종결사유 또는 지속관리 필요 사유 초안",
    "followup_items": ["후속관리 항목 1", "후속관리 항목 2"]
  }},
  "safety_and_ethics_note": "AI 결과는 자동 판정이 아니라 교사와 학교 협의체 검토를 위한 초안입니다."
}}
""".strip()


def build_document_generation_repair_prompt(validation_error: str, previous_output: str) -> str:
    return f"""
이전 출력은 문서 생성 조건을 충족하지 못했습니다.
검증 실패 사유: {validation_error}
반드시 JSON 형식으로만 다시 작성하세요. meeting_record와 student_growth_record 및 필수 필드를 모두 포함하세요.
개인정보를 생성하거나 추정하지 말고, 기관명은 제공된 추천기관 목록 안에서만 사용하세요.
Red Flag, urgent_flag, 긴급확인 관련 내용은 출력하지 마세요.

[이전 출력]
{previous_output}
""".strip()


def _set_cell_text(cell: Any, text: str) -> None:
    cell.text = str(text or "")


def _join_list(values: Any) -> str:
    if isinstance(values, list):
        return "\n".join([f"- {v}" for v in values])
    return str(values or "")


def build_checkbox_values_from_ui() -> Dict[str, bool]:
    checkbox_defs = {
        "성별": [("G1", "남"), ("G2", "여")],
        "기초수급 보장현황": [("W1", "기초수급"), ("W2", "생계"), ("W3", "의료"), ("W4", "주거"), ("W5", "교육"), ("W6", "법정한부모"), ("W7", "법정차상위"), ("W8", "기타저소득"), ("W9", "일반")],
        "가족현황": [("F1", "한부모(부)"), ("F2", "한부모(모)"), ("F3", "조부모(부)"), ("F4", "조부모(모)"), ("F5", "부모가정"), ("F6", "조부모가정"), ("F7", "새혼가정"), ("F8", "기타")],
        "학생현황": [("S1", "이주배경"), ("S2", "특수교육대상"), ("S3", "기타")],
        "내부자원": [("I1", "학습"), ("I2", "진로"), ("I3", "심리·정서"), ("I4", "복지·경제"), ("I5", "기타")],
        "외부자원": [("O1", "학습"), ("O2", "진로"), ("O3", "심리·정서"), ("O4", "복지·경제"), ("O5", "기타")],
    }
    values: Dict[str, bool] = {}
    for group, items in checkbox_defs.items():
        st.write(group)
        cols = st.columns(min(4, len(items)))
        for i, (code, label) in enumerate(items):
            with cols[i % len(cols)]:
                values[code] = st.checkbox(label, key=f"doc_checkbox_{code}")
    return values


def replace_checkbox_markers_with_unicode_fallback(docx_path: Path, checkbox_values: Dict[str, bool]) -> None:
    from docx import Document
    doc = Document(str(docx_path))
    for p in doc.paragraphs:
        for code, checked in checkbox_values.items():
            p.text = p.text.replace(f"[{code}]", "☑" if checked else "☐")
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for p in cell.paragraphs:
                    for code, checked in checkbox_values.items():
                        if f"[{code}]" in p.text:
                            p.text = p.text.replace(f"[{code}]", "☑" if checked else "☐")
    doc.save(str(docx_path))


def fill_meeting_docx(template_path: Path, output_path: Path, basic: Dict[str, Any], llm_result: Dict[str, Any]) -> None:
    from docx import Document
    import shutil
    shutil.copyfile(template_path, output_path)
    doc = Document(str(output_path))
    mr = llm_result.get("meeting_record", {})
    table = doc.tables[0]
    table.cell(0, 0).text = f"제({basic.get('meeting_round', '')})차 통합지원팀 회의록"
    table.cell(2, 1).text = basic.get("meeting_date", "")
    table.cell(2, 3).text = basic.get("writer", "")
    table.cell(2, 5).text = basic.get("place", "")
    table.cell(3, 1).text = basic.get("attendees", "")
    table.cell(4, 1).text = basic.get("agenda", "") or mr.get("agenda", "")
    table.cell(5, 1).text = mr.get("meeting_content", "")
    table.cell(6, 1).text = _join_list(mr.get("decision_items", []))
    table.cell(7, 1).text = _join_list(mr.get("followup_plan", []))
    doc.save(str(output_path))


def fill_growth_docx(template_path: Path, output_path: Path, basic: Dict[str, Any], checkbox_values: Dict[str, bool], llm_result: Dict[str, Any]) -> bool:
    from docx import Document
    import shutil
    shutil.copyfile(template_path, output_path)
    doc = Document(str(output_path))
    sg = llm_result.get("student_growth_record", {})
    t = doc.tables[1]
    # 기본정보 위치 기반 삽입
    t.cell(0, 2).text = basic.get("selection_date", "")
    t.cell(0, 11).text = basic.get("applicant", "")
    t.cell(0, 24).text = basic.get("relation_to_student", "")
    t.cell(2, 2).text = basic.get("student_name", "")
    t.cell(2, 5).text = basic.get("class_name", "")
    t.cell(2, 18).text = basic.get("birth_date", "")
    t.cell(2, 24).text = basic.get("gender_text", "")
    t.cell(3, 3).text = basic.get("student_phone", "")
    t.cell(3, 18).text = basic.get("address", "")
    t.cell(4, 3).text = basic.get("guardian_phone", "")
    # 서술형 필드: 빈 큰 셀에 삽입
    if len(t.rows) > 14:
        t.cell(14, 2).text = sg.get("student_difficulties", "")
    if len(t.rows) > 15:
        t.cell(15, 2).text = sg.get("internal_resource_summary", "")
    if len(t.rows) > 16:
        t.cell(16, 2).text = sg.get("external_resource_summary", "")
    monthly = sg.get("monthly_support_records", [])
    for idx, rownum in enumerate([14, 15, 16, 17]):
        if idx < len(monthly) and rownum < len(t.rows):
            cur = t.cell(rownum, 2).text
            add = monthly[idx].get("content", "")
            if add:
                t.cell(rownum, 2).text = (cur + "\n" + add).strip()
    if len(t.rows) > 20:
        t.cell(20, 2).text = sg.get("comprehensive_evaluation", "")
    if len(t.rows) > 21:
        t.cell(21, 2).text = sg.get("closure_reason", "")
        t.cell(21, 18).text = basic.get("closure_date", "")
    doc.save(str(output_path))
    replace_checkbox_markers_with_unicode_fallback(output_path, checkbox_values)
    return True


def validate_generated_docx(path: Path) -> Tuple[bool, str]:
    if not path.exists() or path.stat().st_size <= 0:
        return False, "파일이 생성되지 않았습니다."
    try:
        from docx import Document
        doc = Document(str(path))
        text = "\n".join([p.text for p in doc.paragraphs] + [cell.text for table in doc.tables for row in table.rows for cell in row.cells])
        if "{{" in text or "}}" in text:
            return False, "남은 placeholder가 있습니다."
        if re.search(r"\[[GWFISO]\d\]", text):
            return False, "체크박스 표시자가 남아 있습니다."
        banned = [w for w in HARD_BANNED_COMMON if w in text]
        if banned:
            return False, "금지 표현이 문서에 포함되었습니다: " + ", ".join(banned)
    except Exception as exc:
        return False, f"docx 검증 중 오류: {exc}"
    return True, "검증 통과"


def render_document_generation_section() -> None:
    st.markdown("<div class='panel'><div class='panel-title'>협의록 및 학생성장기록지 생성</div>", unsafe_allow_html=True)
    if not st.session_state.get("structured_counseling_analysis") or not st.session_state.get("resource_recommendation_explanation"):
        st.info("상담 결과 분석과 기관 추천 이유 설명이 완료되면 문서를 생성할 수 있습니다.")
        st.markdown("</div>", unsafe_allow_html=True)
        return
    doc_types = st.multiselect("문서 유형 선택", ["통합지원팀 회의록", "학생성장 기록지"], default=["통합지원팀 회의록", "학생성장 기록지"])
    st.write("협의록 기본정보")
    c1, c2, c3 = st.columns(3)
    with c1:
        meeting_round = st.text_input("회차", value="1")
        meeting_date = st.text_input("일시", value=str(date.today()))
    with c2:
        writer = st.text_input("작성자")
        place = st.text_input("장소", value="교내 협의실")
    with c3:
        agenda_user = st.text_input("안건", value="대상 학생 맞춤지원 방안 협의")
    attendees = st.text_area("참석자", placeholder="예: 담임교사, 학년부장, 상담교사, 보건교사")

    st.write("학생성장기록지 기본정보")
    g1, g2, g3 = st.columns(3)
    with g1:
        selection_date = st.text_input("지원대상 선정일", value=str(date.today()))
        applicant = st.text_input("신청자")
        relation = st.text_input("학생과의 관계", value="담임교사")
        student_name = st.text_input("학생명")
    with g2:
        class_name = st.text_input("학반")
        birth_date = st.text_input("생년월일")
        gender_text = st.selectbox("성별", ["", "남", "여"])
        student_phone = st.text_input("학생 연락처")
    with g3:
        guardian_phone = st.text_input("보호자 연락처")
        address = st.text_input("주소")
        closure_date = st.text_input("종결일자")
    st.write("학생성장기록지 체크박스")
    checkbox_values = build_checkbox_values_from_ui()
    if not get_gemini_api_key():
        st.warning("Gemini API 키가 설정되어 있지 않습니다. Streamlit secrets 또는 환경변수에 GEMINI_API_KEY를 설정해 주세요.")
    if st.button("선택 문서 생성하기", type="primary", use_container_width=True, key="btn_generate_docs"):
        if not doc_types:
            st.warning("생성할 문서 유형을 선택해 주세요.")
        elif not get_gemini_api_key():
            st.warning("API 키가 설정되지 않아 문서 서술형 초안 생성을 실행할 수 없습니다.")
        else:
            rag = st.session_state.get("rag_search_results", {})
            rec = st.session_state.get("resource_recommendation_explanation", {})
            allowed_names = [r.get("resource_name") for r in rec.get("recommended_resources", [])]
            payload = build_document_generation_payload(st.session_state.get("structured_counseling_analysis", {}), rec, rag, st.session_state.get("first_check_result", {}), "meeting_record_and_student_growth_record")
            with st.spinner("문서 서술형 내용을 생성하고 있습니다..."):
                result = call_llm_with_validation(
                    build_document_generation_system_prompt(),
                    build_document_generation_user_prompt(payload),
                    validate_document_generation_output,
                    build_document_generation_repair_prompt,
                    validation_kwargs={"allowed_resource_names": allowed_names},
                )
            if result["success"]:
                st.session_state["generated_document_json"] = result["data"]
                out_dir = APP_DIR / "outputs"
                out_dir.mkdir(exist_ok=True)
                generated_files = {}
                meeting_basic = {"meeting_round": meeting_round, "meeting_date": meeting_date, "writer": writer, "place": place, "attendees": attendees, "agenda": agenda_user}
                student_basic = {"selection_date": selection_date, "applicant": applicant, "relation_to_student": relation, "student_name": student_name, "class_name": class_name, "birth_date": birth_date, "gender_text": gender_text, "student_phone": student_phone, "guardian_phone": guardian_phone, "address": address, "closure_date": closure_date}
                if "통합지원팀 회의록" in doc_types:
                    tpl = TEMPLATE_DIR / "협의록.docx"
                    out = out_dir / f"통합지원팀_회의록_{datetime.now().strftime('%Y%m%d_%H%M%S')}.docx"
                    if not tpl.exists():
                        st.error("templates/협의록.docx 템플릿을 찾을 수 없습니다.")
                    else:
                        fill_meeting_docx(tpl, out, meeting_basic, result["data"])
                        ok, msg = validate_generated_docx(out)
                        if ok:
                            generated_files["meeting"] = out
                        else:
                            st.warning("협의록 검증 경고: " + msg)
                            generated_files["meeting"] = out
                if "학생성장 기록지" in doc_types:
                    tpl = TEMPLATE_DIR / "학생성장기록지.docx"
                    out = out_dir / f"학생성장기록지_{datetime.now().strftime('%Y%m%d_%H%M%S')}.docx"
                    if not tpl.exists():
                        st.error("templates/학생성장기록지.docx 템플릿을 찾을 수 없습니다.")
                    else:
                        fill_growth_docx(tpl, out, student_basic, checkbox_values, result["data"])
                        ok, msg = validate_generated_docx(out)
                        if ok:
                            generated_files["growth"] = out
                        else:
                            st.warning("학생성장기록지 검증 경고: " + msg)
                            generated_files["growth"] = out
                            st.info("클릭 가능한 체크박스가 아닌 표시용 체크박스로 생성되었습니다.")
                st.session_state["generated_docx_files"] = {k: str(v) for k, v in generated_files.items()}
                st.success("문서 생성이 완료되었습니다.")
                if result.get("warnings"):
                    st.warning("검증 경고: " + " / ".join(map(str, result["warnings"][:3])))
            else:
                st.error("문서 생성에 실패했습니다: " + str(result.get("error")))
    data = st.session_state.get("generated_document_json")
    files = st.session_state.get("generated_docx_files", {})
    if data:
        with st.expander("생성된 문서 서술형 JSON"):
            st.json(data)
        if files.get("meeting") and Path(files["meeting"]).exists():
            st.download_button("협의록 DOCX 다운로드", Path(files["meeting"]).read_bytes(), Path(files["meeting"]).name, "application/vnd.openxmlformats-officedocument.wordprocessingml.document", use_container_width=True)
        if files.get("growth") and Path(files["growth"]).exists():
            st.download_button("학생성장기록지 DOCX 다운로드", Path(files["growth"]).read_bytes(), Path(files["growth"]).name, "application/vnd.openxmlformats-officedocument.wordprocessingml.document", use_container_width=True)
    st.markdown("</div>", unsafe_allow_html=True)


def render_followup_workflow_sections() -> None:
    render_counseling_question_section()
    render_counseling_analysis_section()
    render_rag_search_section()
    render_resource_recommendation_section()
    render_document_generation_section()


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
    df = get_view_students()
    total = len(df)
    deep = int(df["최종단계"].isin(["심층 파악 필요", "심층 파악 권고"]).sum())
    watch = int((df["최종단계"] == "주의 및 탐색").sum())
    red = int(df["RedFlag"].astype(bool).sum())
    meeting = deep

    metric_cols = st.columns(5)
    metrics = [
        ("조회 학생", f"{total}명", role),
        ("심층 파악 필요/권고", f"{deep}명", "2차 상담 질문 후보"),
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
        show = df[df["최종단계"].isin(["심층 파악 필요", "심층 파악 권고", "주의 및 탐색"])].copy()
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
        "1차 체크리스트 입력 및 후속 지원 흐름",
        "1차 체크리스트 결과를 바탕으로 2차 상담 질문, 상담 메모 구조화, RAG 검색, 기관 추천 이유, 문서 생성까지 연결합니다.",
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
    active_deep_rules = activate_deep_rules(responses, rule_map_df, deep_rules_df)
    counseling_areas = derive_counseling_consideration_areas(
        first_result["domain_scores"], responses, red_flag_result, active_deep_rules, items_df
    )
    context_result = calculate_context_result(
        first_result["primary_areas"],
        first_result["student_raw_score"],
        first_result["student_scaled_score"],
        red_flag_result,
        st.session_state.get("selected_school_context"),
        st.session_state.get("selected_region_context"),
    )
    stage_result = {
        "score_based_stage": context_result["score_based_stage"],
        "score_based_action": context_result["score_based_action"],
        "final_action_stage": context_result["final_action_stage"],
        "final_action": context_result["final_action"],
        "final_action_reason": context_result["final_action_reason"],
        "activate_counseling_form": context_result["activate_counseling_form"],
    }
    payload = build_counseling_payload(
        first_result, red_flag_result, context_result, active_deep_rules, counseling_areas, stage_result
    )

    # 이후 기능에서 재사용할 세션 저장. 검증된 LLM 결과는 각 기능별 버튼 클릭 시 별도로 저장됩니다.
    st.session_state["first_check_result"] = payload["first_check_result"]
    st.session_state["red_flag_result"] = payload["red_flag_result"]
    st.session_state["context_result"] = payload["context_result"]
    st.session_state["active_deep_rules"] = payload["active_deep_rules"]
    st.session_state["counseling_consideration_areas"] = counseling_areas
    st.session_state["last_payload"] = payload

    with right:
        st.markdown("<div class='panel'><div class='panel-title'>즉시 계산 결과</div>", unsafe_allow_html=True)
        summary_for_cards = {
            "raw_score": first_result["student_raw_score"],
            "scaled_score": first_result["student_scaled_score"],
            "score_based_stage": context_result["score_based_stage"],
            "urgent_flag": red_flag_result.get("urgent_flag", False),
            "context_adjustment_applied": context_result["context_adjustment_applied"],
            "context_adjustment_reason": context_result["context_adjustment_reason"],
            "context_check_score": context_result["context_check_score"],
            "final_action_stage": context_result["final_action_stage"],
            "final_action_reason": context_result["final_action_reason"],
            "final_action": context_result["final_action"],
        }
        render_summary_cards(summary_for_cards)
        final_stage = context_result["final_action_stage"]
        if final_stage == "일상적 관찰":
            st.info("현재 1차 체크리스트 기준으로는 뚜렷한 지원 신호가 높지 않습니다. 평소 관찰과 라포 형성을 유지합니다.")
        elif final_stage == "주의 및 탐색":
            st.warning("일부 지원 신호가 관찰됩니다. 담임교사의 가벼운 면담을 통해 학생의 최근 변화와 어려움을 탐색할 수 있습니다.")
        elif final_stage == "심층 파악 권고":
            st.warning("체크리스트 기준으로는 주의 및 탐색 단계이나, 학교·지역 지원여건을 고려할 때 2차 상담 질문을 통해 한 번 더 확인하는 것이 권장됩니다.")
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
        all_df = st.session_state.students.copy()
        idx = all_df.index[all_df["학생코드"] == selected_student]
        if len(idx) > 0:
            idx0 = idx[0]
            for _, row in first_result["domain_scores"].iterrows():
                area = row["지원 영역"]
                all_df.at[idx0, area] = min(4, int(round(float(row["domain_scaled_score"]) / 25)))
            all_df.at[idx0, "RedFlag"] = bool(red_flag_result.get("urgent_flag"))
            all_df.at[idx0, "최종단계"] = context_result["final_action_stage"]
            all_df.at[idx0, "권장Action"] = context_result["final_action"]
            checked_codes = []
            for _, row in items_df.iterrows():
                item_id = normalize_text(row.get("item_id"))
                if int(responses.get(item_id, 0)) >= 1:
                    checked_codes.append(normalize_text(row.get("item_code")))
            all_df.at[idx0, "주요신호"] = ", ".join(checked_codes) if checked_codes else "선택된 신호 없음"
            all_df.at[idx0, "기한"] = str(date.today()) if context_result["final_action_stage"] != "일상적 관찰" else "-"
            st.session_state.students = all_df
        st.session_state.checklist_responses[selected_student] = responses
        st.success("계산 결과가 학생 기록에 반영되었습니다.")

    render_followup_workflow_sections()

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
        ["담임교사 대시보드", "1차 체크리스트", "학생 상세 리포트", "지원 현황표"],
        index=0,
        label_visibility="collapsed",
    )

    school = st.session_state.selected_school_info
    st.sidebar.divider()
    st.sidebar.markdown("### 현재 학교 정보")
    st.sidebar.write(f"학교: {school.get('학교명')}")
    st.sidebar.write(f"학교급: {school.get('학교급')}")
    st.sidebar.write(f"자치구: {school.get('자치구')}")
    st.sidebar.write(f"교육지원청: {school.get('교육지원청')}")
    st.sidebar.write(f"학생 수: {int(school.get('학교_학생수', 0)):,}명" if school.get('학교_학생수', 0) else "학생 수: -")
    st.sidebar.write(f"교원 1인당 학생수: {school.get('학교_교원1인당학생수', 0):.1f}명" if school.get('학교_교원1인당학생수', 0) else "교원 1인당 학생수: -")
    st.sidebar.write(f"위클래스: {'있음' if school.get('위클래스_있음') else '없음'}")
    st.sidebar.write(f"전문상담교사: {school.get('전문상담교사_수')}명")
    st.sidebar.write(f"보건교사: {school.get('보건교사_수')}명")
    st.sidebar.write(f"진로상담실: {'있음' if school.get('진로상담실_있음') else '없음'}")
    st.sidebar.caption("학교 정보는 DB CSV에서 불러와 왼쪽 정보란에 표시합니다.")
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
