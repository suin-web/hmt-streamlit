# -*- coding: utf-8 -*-
"""
학맞통 AI 교사용 의사결정 보조 프로토타입
- 실행: streamlit run hakmatch_streamlit_app.py
- 목적: 담임교사용 학급 대시보드, 학생 체크리스트, 학생 상세 리포트,
        학교 인프라 기반 지원서비스 추천, 지원 현황표 다운로드를 시연합니다.

주의: 이 파일은 대회/발표용 MVP입니다. 실제 운영 시에는 개인정보보호,
      사용자 권한, NEIS/학교 DB 연계, 로그 관리, 보안 검토가 필요합니다.
"""

from __future__ import annotations

import io
from datetime import date
from pathlib import Path
from typing import Dict, List

import pandas as pd
import streamlit as st

try:
    import plotly.express as px
except Exception:  # plotly가 없어도 표와 카드 화면은 동작하게 처리
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

DOMAINS = ["학습·진로", "심리·정서", "복지·경제", "건강·안전"]
RISK_ORDER = ["긴급", "지원필요", "관찰", "안정"]
STATUS_CLASS = {
    "긴급": "risk-emergency",
    "지원필요": "risk-need",
    "관찰": "risk-watch",
    "안정": "risk-stable",
}

DEFAULT_SCHOOL = {
    "학교명": "○○고등학교",
    "학교급": "고등학교",
    "자치구": "강서구",
    "학년": "2학년",
    "반": "3반",
    "담임교사": "조○○",
    "위클래스": True,
    "전문상담교사 수": 1,
    "보건교사 수": 1,
    "진로상담실": True,
    "교육복지우선지원학교": False,
    "교원 1인당 학생수": 12.4,
}


# -----------------------------------------------------------------------------
# 스타일: 실제 교사용 업무포털 느낌을 참고한 상단바/좌측메뉴/표 스타일
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
            font-weight: 800;
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
            font-weight: 700;
            margin-right: 8px;
        }
        .edu-actions span {
            border: 1px solid rgba(255,255,255,0.7);
            border-radius: 3px;
            padding: 3px 8px;
            margin-left: 5px;
            background: #ffffff;
            color: #0f172a;
            font-weight: 700;
        }
        .edu-nav {
            height: 40px;
            display: flex;
            align-items: center;
            gap: 30px;
            padding: 0 18px;
            font-weight: 800;
            color: #0f2a50;
            border-top: 1px solid #cbd5e1;
        }
        .edu-nav span { white-space: nowrap; }
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
            font-size: 1.9rem;
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
        .risk-emergency { border-left: 8px solid var(--red); background: #fff7f7; }
        .risk-need { border-left: 8px solid var(--orange); background: #fffaf0; }
        .risk-watch { border-left: 8px solid var(--blue); background: #f7fbff; }
        .risk-stable { border-left: 8px solid #94a3b8; }
        .badge {
            display: inline-block;
            border-radius: 999px;
            padding: 3px 9px;
            font-weight: 900;
            font-size: 0.78rem;
            margin-right: 5px;
            border: 1px solid transparent;
        }
        .badge-emergency { background: #fee2e2; color: #b91c1c; border-color: #fecaca; }
        .badge-need { background: #ffedd5; color: #c2410c; border-color: #fed7aa; }
        .badge-watch { background: #dbeafe; color: #1d4ed8; border-color: #bfdbfe; }
        .badge-stable { background: #f1f5f9; color: #475569; border-color: #e2e8f0; }
        .mini-grid {
            display: grid;
            grid-template-columns: repeat(4, minmax(90px, 1fr));
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
        }
        .notice-row {
            display: grid;
            grid-template-columns: 48px 1fr 95px;
            gap: 8px;
            border-bottom: 1px solid #e5e7eb;
            padding: 9px 2px;
            font-size: 0.86rem;
        }
        .new-icon {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 18px;
            height: 18px;
            border-radius: 5px;
            background: #ff5b45;
            color: white;
            font-size: 0.65rem;
            font-weight: 900;
            margin-right: 6px;
        }
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
        .small-muted { color: #64748b; font-size: 0.84rem; }
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
# 데모 데이터
# -----------------------------------------------------------------------------
def status_from_scores(row: pd.Series) -> str:
    score_sum = int(sum(row[d] for d in DOMAINS))
    urgent = bool(row.get("긴급신호", False))
    if urgent or int(row.get("심리·정서", 0)) >= 4 or int(row.get("건강·안전", 0)) >= 4:
        return "긴급"
    if score_sum >= 5 or max(int(row[d]) for d in DOMAINS) >= 3:
        return "지원필요"
    if score_sum >= 2:
        return "관찰"
    return "안정"


def priority_from_status(status: str) -> str:
    return {"긴급": "긴급", "지원필요": "높음", "관찰": "중간", "안정": "낮음"}.get(status, "중간")


def normalize_students(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for d in DOMAINS:
        df[d] = df[d].clip(lower=0, upper=4).astype(int)
    df["총점"] = df[DOMAINS].sum(axis=1).astype(int)
    df["상태"] = df.apply(status_from_scores, axis=1)
    df["우선순위"] = df["상태"].map(priority_from_status)
    df["회의자료필요"] = df["상태"].isin(["긴급", "지원필요"])
    return df


def load_demo_students() -> pd.DataFrame:
    rows = [
        ["A-01", "학생 A-01", "2학년", "3반", 0, 0, 0, 0, False, "특이 신호 없음", "안정", "담임 관찰 지속", "담임교사", "-"],
        ["A-02", "학생 A-02", "2학년", "3반", 1, 1, 0, 0, False, "수업 참여 저하, 위축된 표정", "관찰", "담임 면담 후 경과 관찰", "담임교사", "2026-05-20"],
        ["A-03", "학생 A-03", "2학년", "3반", 1, 4, 2, 1, True, "자해·극단 표현, 결석 증가, 또래관계 단절", "긴급", "담임 면담 → 위클래스 → 학맞통 회의", "담임교사", "2026-05-16"],
        ["A-04", "학생 A-04", "2학년", "3반", 0, 0, 0, 1, False, "보건실 방문 1회 증가", "관찰", "보건교사 확인", "보건교사", "2026-05-24"],
        ["A-05", "학생 A-05", "2학년", "3반", 0, 0, 0, 0, False, "특이 신호 없음", "안정", "정상 학급 활동", "담임교사", "-"],
        ["A-06", "학생 A-06", "2학년", "3반", 2, 1, 0, 0, False, "과제 미제출, 수업 집중 저하", "관찰", "학습지원 프로그램 검토", "담임교사", "2026-05-23"],
        ["A-07", "학생 A-07", "2학년", "3반", 3, 0, 1, 0, False, "과제 미제출, 진로 목표 부재, 학습동기 저하", "지원필요", "기초학력 지원 → 진로상담실", "담임교사", "2026-05-21"],
        ["A-08", "학생 A-08", "2학년", "3반", 0, 0, 0, 0, False, "특이 신호 없음", "안정", "정상 학급 활동", "담임교사", "-"],
        ["A-09", "학생 A-09", "2학년", "3반", 1, 2, 0, 0, False, "친구 관계 갈등, 발표 회피", "관찰", "담임 면담 → 필요시 위클래스", "담임교사", "2026-05-25"],
        ["A-10", "학생 A-10", "2학년", "3반", 0, 0, 0, 0, False, "특이 신호 없음", "안정", "정상 학급 활동", "담임교사", "-"],
        ["A-11", "학생 A-11", "2학년", "3반", 0, 1, 2, 0, False, "돌봄 공백 의심, 식사 상태 우려", "관찰", "보호자 상담 → 지역교육복지센터 검토", "담임교사", "2026-05-27"],
        ["A-12", "학생 A-12", "2학년", "3반", 0, 2, 0, 1, False, "보건실 방문 증가, 위축된 표정", "관찰", "보건교사 확인 → 담임 관찰", "보건교사", "2026-05-22"],
        ["A-13", "학생 A-13", "2학년", "3반", 0, 0, 0, 0, False, "특이 신호 없음", "안정", "정상 학급 활동", "담임교사", "-"],
        ["A-14", "학생 A-14", "2학년", "3반", 1, 0, 0, 0, False, "숙제 미제출", "관찰", "학습 루틴 점검", "담임교사", "2026-05-29"],
        ["A-15", "학생 A-15", "2학년", "3반", 0, 0, 0, 0, False, "특이 신호 없음", "안정", "정상 학급 활동", "담임교사", "-"],
        ["A-16", "학생 A-16", "2학년", "3반", 0, 0, 0, 0, False, "특이 신호 없음", "안정", "정상 학급 활동", "담임교사", "-"],
        ["A-17", "학생 A-17", "2학년", "3반", 2, 2, 1, 0, False, "결석 증가, 무기력, 가정 상담 필요", "지원필요", "담임 면담 → 학맞통 회의 검토", "담임교사", "2026-05-20"],
        ["A-18", "학생 A-18", "2학년", "3반", 0, 0, 0, 0, False, "특이 신호 없음", "안정", "정상 학급 활동", "담임교사", "-"],
        ["A-19", "학생 A-19", "2학년", "3반", 0, 0, 0, 0, False, "특이 신호 없음", "안정", "정상 학급 활동", "담임교사", "-"],
        ["A-20", "학생 A-20", "2학년", "3반", 1, 0, 2, 0, False, "체험활동 비용 부담, 준비물 미비", "관찰", "교육비·교육급여 확인", "담임교사", "2026-05-28"],
        ["A-21", "학생 A-21", "2학년", "3반", 0, 0, 0, 0, False, "특이 신호 없음", "안정", "정상 학급 활동", "담임교사", "-"],
        ["A-22", "학생 A-22", "2학년", "3반", 0, 3, 0, 0, False, "또래관계 단절, 우울 표현", "지원필요", "위클래스 상담 예약", "전문상담교사", "2026-05-18"],
        ["A-23", "학생 A-23", "2학년", "3반", 0, 0, 0, 0, False, "특이 신호 없음", "안정", "정상 학급 활동", "담임교사", "-"],
        ["A-24", "학생 A-24", "2학년", "3반", 1, 1, 1, 0, False, "수업 집중 저하, 가정상담 필요", "관찰", "담임 면담 및 보호자 연락 검토", "담임교사", "2026-05-30"],
    ]
    columns = [
        "학생코드", "이름", "학년", "반", *DOMAINS, "긴급신호", "주요신호", "상태", "추천첫조치", "담당자", "기한"
    ]
    return normalize_students(pd.DataFrame(rows, columns=columns))


CHECKLIST = {
    "학습·진로": [
        ("수업 집중이 어렵다", 1, False),
        ("과제 수행이 지속적으로 부족하다", 1, False),
        ("잦은 지각·결석이 있다", 1, False),
        ("진로 목표가 없거나 진로 상담에서 무기력함이 관찰된다", 1, False),
    ],
    "심리·정서": [
        ("표정이 지나치게 어둡거나 위축되어 있다", 1, False),
        ("친구·교사와 갈등이 잦다", 1, False),
        ("자해·자살·극단적 표현 등 위험 신호가 있다", 3, True),
        ("스마트폰·인터넷 과의존이 의심된다", 1, False),
    ],
    "복지·경제": [
        ("의복, 위생, 식사 상태가 우려된다", 1, False),
        ("가정 내 돌봄 공백이 의심된다", 1, False),
        ("경제적 어려움으로 준비물·체험활동 참여에 어려움이 있다", 1, False),
        ("가족·문화·이주배경 등 추가 지원 검토가 필요하다", 1, False),
    ],
    "건강·안전": [
        ("반복적인 신체 증상 호소가 있다", 1, False),
        ("학교폭력·학대·방임 가능성이 있다", 3, True),
        ("보건실 방문이 잦다", 1, False),
        ("건강·안전 관련 추가 확인이 필요하다", 1, False),
    ],
}


# -----------------------------------------------------------------------------
# 세션 상태
# -----------------------------------------------------------------------------
def init_state() -> None:
    if "students" not in st.session_state:
        st.session_state.students = load_demo_students()
    if "school" not in st.session_state:
        st.session_state.school = DEFAULT_SCHOOL.copy()
    if "selected_student" not in st.session_state:
        st.session_state.selected_student = "A-03"


# -----------------------------------------------------------------------------
# 공통 UI 함수
# -----------------------------------------------------------------------------
def render_header() -> None:
    school = st.session_state.school
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
                        <span class="edu-school-badge">{school['학교명']}</span>
                        {school['담임교사']} · {school['학년']} {school['반']} 담임
                    </div>
                    <div class="edu-actions">
                        <span>로그아웃</span><span>튜토리얼</span><span>사용자지원</span>
                    </div>
                </div>
                <div class="edu-nav">
                    <span>학급담임</span><span>교과담임</span><span>동아리담임</span><span>기획</span><span>전체교사</span><span>정보공시</span>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_page_title(title: str, subtitle: str) -> None:
    st.markdown(f"<div class='page-title'>{title}</div>", unsafe_allow_html=True)
    st.markdown(f"<div class='page-subtitle'>{subtitle}</div>", unsafe_allow_html=True)


def risk_badge(status: str) -> str:
    cls = {
        "긴급": "badge-emergency",
        "지원필요": "badge-need",
        "관찰": "badge-watch",
        "안정": "badge-stable",
    }.get(status, "badge-stable")
    return f"<span class='badge {cls}'>{status}</span>"


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
            <div class="domain-name">{d}</div>
            {dots(int(row[d]))}
        </div>
        """
        for d in DOMAINS
    )
    return f"<div class='mini-grid'>{cells}</div>"


def render_student_card(row: pd.Series) -> None:
    status = row["상태"]
    cls = STATUS_CLASS.get(status, "risk-stable")
    top_domain = max(DOMAINS, key=lambda d: int(row[d]))
    st.markdown(
        f"""
        <div class="student-card {cls}">
            <div style="display:flex;justify-content:space-between;align-items:center;gap:10px;">
                <div style="font-weight:900;font-size:1.02rem;color:#0f172a;">
                    {risk_badge(status)} {row['이름']} <span class="small-muted">({row['학생코드']})</span>
                </div>
                <div class="small-muted">우선 영역: <b>{top_domain}</b> · 총점 {row['총점']}</div>
            </div>
            {domain_grid(row)}
            <div style="margin-top:10px;color:#334155;font-size:.9rem;">
                <b>주요 신호</b>: {row['주요신호']}<br>
                <b>추천 첫 조치</b>: {row['추천첫조치']}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_notice_panel() -> None:
    notices = [
        (1, "지시/전달사항", "2026-05-14"),
        (2, "지시/전달사항", "2026-05-13"),
        (3, "지시/전달사항", "2026-05-12"),
        (4, "학맞통 정례회의 자료 제출 안내", "2026-05-11"),
        (5, "학생 지원 개인정보 동의서 점검", "2026-05-08"),
    ]
    rows = "".join(
        f"<div class='notice-row'><div>{no}</div><div><span class='new-icon'>N</span>{title}</div><div>{dt}</div></div>"
        for no, title, dt in notices
    )
    st.markdown(
        f"""
        <div class="panel">
            <div class="panel-title">학교일지/전달사항</div>
            <div style="display:grid;grid-template-columns:1fr 92px 76px;gap:6px;margin-bottom:8px;">
                <input style="border:1px solid #cbd5e1;padding:7px;border-radius:4px;" placeholder="제목"/>
                <button style="background:#2f6bff;color:white;border:0;border-radius:4px;font-weight:800;">조회</button>
                <select style="border:1px solid #cbd5e1;border-radius:4px;"><option>2026년</option></select>
            </div>
            {rows}
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_request_panel() -> None:
    st.markdown(
        """
        <div class="panel">
            <div class="panel-title">업무요청내역</div>
            <div class="notice-row" style="grid-template-columns:70px 1fr 95px;">
                <div>나눔포털</div>
                <div><span class='new-icon'>N</span>미오픈학생의 봉사활동 실적 8건이 전송되었습니다.</div>
                <div>2026-05-09</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def metric_card(label: str, value: str, help_text: str = "") -> str:
    return f"""
    <div class="metric-card">
        <div class="metric-label">{label}</div>
        <div class="metric-value">{value}</div>
        <div class="metric-help">{help_text}</div>
    </div>
    """


def chart_bar(data: pd.DataFrame, x: str, y: str, title: str):
    if px is None:
        st.bar_chart(data.set_index(x)[y])
    else:
        fig = px.bar(data, x=x, y=y, text=y, title=title)
        fig.update_layout(height=300, margin=dict(l=10, r=10, t=45, b=10))
        fig.update_traces(textposition="outside")
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


# -----------------------------------------------------------------------------
# 추천 로직
# -----------------------------------------------------------------------------
def build_recommendations(student: pd.Series, school: Dict) -> List[Dict[str, str]]:
    recs: List[Dict[str, str]] = []

    def add(name: str, category: str, domain: str, reason: str, action: str) -> None:
        if not any(r["기관/서비스"] == name for r in recs):
            recs.append(
                {
                    "기관/서비스": name,
                    "구분": category,
                    "지원영역": domain,
                    "추천이유": reason,
                    "연계방법": action,
                }
            )

    emotional = int(student["심리·정서"])
    learning = int(student["학습·진로"])
    welfare = int(student["복지·경제"])
    health = int(student["건강·안전"])
    urgent = student["상태"] == "긴급" or bool(student.get("긴급신호", False))

    if emotional > 0:
        if school.get("위클래스", False):
            add(
                "교내 위클래스",
                "교내",
                "심리·정서",
                "학교 내 위클래스가 있어 초기 상담과 정서 상태 확인을 교내에서 바로 시작할 수 있습니다.",
                "전문상담교사 상담 예약 → 담임 공유 → 필요시 학맞통 회의",
            )
        if urgent or int(school.get("전문상담교사 수", 0)) == 0 or emotional >= 3:
            add(
                "교육지원청 위(Wee)센터",
                "교육지원청",
                "심리·정서",
                "위기 신호가 높거나 전문 진단·상담이 필요한 경우 교육지원청 센터 연계가 적합합니다.",
                "학교장 확인 → 학맞통 Sen콜/메일 또는 공문 의뢰",
            )
        add(
            "청소년상담복지센터",
            "지역사회",
            "심리·정서",
            "학교 밖 전문 상담, 가족 상담, 위기 청소년 긴급 개입이 필요할 때 활용할 수 있습니다.",
            "자치구 센터 상담 가능 여부 확인 → 보호자 동의 후 연계",
        )

    if learning > 0:
        add(
            "교내 기초학력 지원 프로그램",
            "교내",
            "학습·진로",
            "과제 미제출, 수업 집중 저하 등 학습 신호가 관찰되어 교내 1차 지원을 우선 검토합니다.",
            "기초학력 담당교사 확인 → 보충지도·학습코칭 배정",
        )
        add(
            "지역학습진단성장센터",
            "교육지원청",
            "학습·진로",
            "학교 지도만으로 해결이 어려운 특수·복합 학습 요인이 의심될 때 개별 맞춤 지원을 검토합니다.",
            "학교 의뢰 → 학습 요인 진단 → 맞춤형 학습지원",
        )
        if school.get("진로상담실", False):
            add(
                "교내 진로상담실",
                "교내",
                "학습·진로",
                "진로 목표 부재·무기력 신호가 있어 진로상담실 연계가 우선 가능합니다.",
                "진로교사 상담 예약 → 진로검사·진로활동 추천",
            )

    if welfare > 0:
        if school.get("교육복지우선지원학교", False):
            add(
                "교내 교육복지 담당",
                "교내",
                "복지·경제",
                "학교 내 복지 지원 인프라가 있어 교내 사례관리와 경제 지원 확인을 우선 진행합니다.",
                "교육복지 담당자 확인 → 교육비·교육급여·교내 지원 검토",
            )
        add(
            "지역교육복지센터",
            "교육지원청/지역",
            "복지·경제",
            "가정 돌봄 공백, 경제적 어려움 등 복합 복지 신호가 있어 사례관리 연계가 필요할 수 있습니다.",
            "학교-지역기관-자치구 연계 가능성 확인",
        )
        add(
            "동주민센터 복지상담",
            "지역사회",
            "복지·경제",
            "교육비·생계·돌봄 등 공공복지 확인이 필요한 경우 지자체 복지 창구와 연결합니다.",
            "보호자 동의 후 복지 상담 안내",
        )
        add(
            "가족센터",
            "지역사회",
            "복지·경제",
            "가족관계, 다문화·이주배경, 돌봄 관련 지원이 필요한 경우 검토합니다.",
            "자치구 가족센터 프로그램 확인",
        )

    if health > 0:
        if int(school.get("보건교사 수", 0)) > 0:
            add(
                "교내 보건실/보건교사",
                "교내",
                "건강·안전",
                "반복적 신체 증상이나 보건실 방문 증가가 있어 건강 기록 확인이 필요합니다.",
                "보건교사 확인 → 건강상담 기록 공유 범위 검토",
            )
        if urgent or health >= 3:
            add(
                "정신건강복지센터 또는 전문치료기관",
                "지역사회",
                "건강·안전",
                "자해·학대·폭력 등 긴급 신호가 있으면 전문기관 병행 검토가 필요합니다.",
                "학교 위기 대응 절차 확인 → 보호자·전문기관 연계",
            )
        add(
            "교육지원청 학생맞춤협력과",
            "교육지원청",
            "건강·안전",
            "학교 내 지원만으로 해결이 어렵거나 지역자원 직접 연계가 어려운 경우 의뢰합니다.",
            "학맞통 Sen콜 1688-3651 또는 Sen메일/공문",
        )

    # 신호가 없는 학생도 기본 안내
    if not recs:
        add(
            "담임 관찰 지속",
            "교내",
            "공통",
            "현재 높은 지원 신호는 없으나 학급 관찰과 정기 상담을 유지합니다.",
            "월 1회 학급 관찰 메모 업데이트",
        )

    return recs[:8]


# -----------------------------------------------------------------------------
# 페이지 1: 학교 입력
# -----------------------------------------------------------------------------
def page_school_input() -> None:
    render_page_title(
        "학교 정보 입력",
        "학교 시설·교사 현황을 반영해 지원 인프라 추천 순서를 조정합니다.",
    )

    school = st.session_state.school.copy()
    left, right = st.columns([1.2, 1])

    with left:
        st.markdown("<div class='panel'><div class='panel-title'>학교 기본 정보</div>", unsafe_allow_html=True)
        col1, col2 = st.columns(2)
        with col1:
            school["학교명"] = st.text_input("학교명", value=school["학교명"])
            school["학교급"] = st.selectbox("학교급", ["초등학교", "중학교", "고등학교"], index=["초등학교", "중학교", "고등학교"].index(school["학교급"]))
            school["자치구"] = st.selectbox(
                "자치구",
                ["강서구", "양천구", "강남구", "서초구", "동작구", "관악구", "성동구", "광진구", "성북구", "강북구"],
                index=0,
            )
            school["교원 1인당 학생수"] = st.number_input("교원 1인당 학생수", min_value=1.0, max_value=40.0, value=float(school["교원 1인당 학생수"]), step=0.1)
        with col2:
            school["학년"] = st.selectbox("학년", ["1학년", "2학년", "3학년"], index=["1학년", "2학년", "3학년"].index(school["학년"]))
            school["반"] = st.selectbox("반", [f"{i}반" for i in range(1, 11)], index=2)
            school["담임교사"] = st.text_input("담임교사", value=school["담임교사"])
            school["교육복지우선지원학교"] = st.toggle("교육복지우선지원학교", value=bool(school["교육복지우선지원학교"]))
        st.markdown("</div>", unsafe_allow_html=True)

        st.markdown("<div class='panel'><div class='panel-title'>교내 지원 인프라</div>", unsafe_allow_html=True)
        col1, col2, col3 = st.columns(3)
        with col1:
            school["위클래스"] = st.toggle("위클래스 있음", value=bool(school["위클래스"]))
        with col2:
            school["전문상담교사 수"] = st.number_input("전문상담교사 수", min_value=0, max_value=10, value=int(school["전문상담교사 수"]))
        with col3:
            school["보건교사 수"] = st.number_input("보건교사 수", min_value=0, max_value=10, value=int(school["보건교사 수"]))
        school["진로상담실"] = st.toggle("진로상담실 있음", value=bool(school["진로상담실"]))
        if st.button("학교 정보 저장", type="primary", use_container_width=True):
            st.session_state.school = school
            st.success("학교 정보가 저장되었습니다. 지원 인프라 추천 순서에 반영됩니다.")
        st.markdown("</div>", unsafe_allow_html=True)

    with right:
        st.markdown("<div class='panel'><div class='panel-title'>학교 인프라 요약</div>", unsafe_allow_html=True)
        wee_text = "있음" if school["위클래스"] else "없음"
        career_text = "있음" if school["진로상담실"] else "없음"
        welfare_text = "해당" if school["교육복지우선지원학교"] else "미해당"
        st.markdown(
            f"""
            <table class="info-table">
                <tr><th>항목</th><th>현재값</th><th>추천 영향</th></tr>
                <tr><td>위클래스</td><td>{wee_text}</td><td>심리·정서 학생의 1순위 연계 조정</td></tr>
                <tr><td>전문상담교사</td><td>{school['전문상담교사 수']}명</td><td>상담 초기 개입 가능성 판단</td></tr>
                <tr><td>보건교사</td><td>{school['보건교사 수']}명</td><td>건강·안전 신호 확인</td></tr>
                <tr><td>진로상담실</td><td>{career_text}</td><td>학습·진로 학생의 교내 연계</td></tr>
                <tr><td>교육복지</td><td>{welfare_text}</td><td>복지·경제 신호의 교내 사례관리</td></tr>
            </table>
            """,
            unsafe_allow_html=True,
        )
        st.markdown("</div>", unsafe_allow_html=True)

        # 선택 학생 기준 인프라 미리보기
        df = st.session_state.students
        selected_code = st.selectbox("추천 미리보기 학생", df["학생코드"].tolist(), index=df["학생코드"].tolist().index(st.session_state.selected_student))
        student = df[df["학생코드"] == selected_code].iloc[0]
        recs = build_recommendations(student, school)
        for i, rec in enumerate(recs[:3], start=1):
            st.markdown(
                f"""
                <div class="recommend-card">
                    <b><span class="recommend-rank">{i}</span>{rec['기관/서비스']}</b><br>
                    <span class="small-muted">{rec['구분']} · {rec['지원영역']}</span><br>
                    <span>{rec['추천이유']}</span>
                </div>
                """,
                unsafe_allow_html=True,
            )


# -----------------------------------------------------------------------------
# 페이지 2: 학생 체크리스트 입력
# -----------------------------------------------------------------------------
def page_checklist() -> None:
    render_page_title(
        "학생 관찰 체크리스트 입력",
        "담임교사가 관찰한 신호를 입력하면 우선 검토 영역과 위험도를 즉시 계산합니다.",
    )
    df = st.session_state.students.copy()
    student_options = [f"{r['학생코드']} | {r['이름']}" for _, r in df.iterrows()]
    selected_label = st.selectbox("학생 선택", student_options, index=student_options.index(f"{st.session_state.selected_student} | {df[df['학생코드']==st.session_state.selected_student].iloc[0]['이름']}"))
    sid = selected_label.split(" | ")[0]
    st.session_state.selected_student = sid

    col_input, col_result = st.columns([1.35, 1])

    selected_items: List[str] = []
    scores = {d: 0 for d in DOMAINS}
    urgent = False

    with col_input:
        st.markdown("<div class='panel'><div class='panel-title'>영역별 관찰 항목</div>", unsafe_allow_html=True)
        tabs = st.tabs(DOMAINS)
        for tab, domain in zip(tabs, DOMAINS):
            with tab:
                for idx, (label, weight, is_urgent) in enumerate(CHECKLIST[domain]):
                    checked = st.checkbox(label, key=f"chk_{sid}_{domain}_{idx}")
                    if checked:
                        selected_items.append(label)
                        scores[domain] += weight
                        urgent = urgent or is_urgent
        teacher_note = st.text_area("추가 관찰 메모", placeholder="예: 최근 2주간 결석이 늘고 친구들과 어울리지 않음", height=100)
        save = st.button("AI 검토 결과 저장", type="primary", use_container_width=True)
        st.markdown("</div>", unsafe_allow_html=True)

    tmp_row = df[df["학생코드"] == sid].iloc[0].copy()
    for d in DOMAINS:
        tmp_row[d] = min(scores[d], 4)
    tmp_row["긴급신호"] = urgent
    signal_text = ", ".join(selected_items) if selected_items else "선택된 신호 없음"
    if teacher_note.strip():
        signal_text += f" / 메모: {teacher_note.strip()}"
    tmp_row["주요신호"] = signal_text
    tmp_row = normalize_students(pd.DataFrame([tmp_row])).iloc[0]

    with col_result:
        st.markdown("<div class='panel'><div class='panel-title'>AI 검토 제안 미리보기</div>", unsafe_allow_html=True)
        render_student_card(tmp_row)
        recs = build_recommendations(tmp_row, st.session_state.school)
        st.markdown("**추천 첫 조치 후보**")
        for i, rec in enumerate(recs[:3], start=1):
            st.write(f"{i}. {rec['기관/서비스']} — {rec['연계방법']}")
        st.caption("※ 자동 판정이 아니라 교사·학교 협의체 검토를 돕는 참고자료입니다.")
        st.markdown("</div>", unsafe_allow_html=True)

    if save:
        idx = df.index[df["학생코드"] == sid][0]
        for d in DOMAINS:
            df.at[idx, d] = min(scores[d], 4)
        df.at[idx, "긴급신호"] = urgent
        df.at[idx, "주요신호"] = signal_text
        df.at[idx, "추천첫조치"] = recs[0]["연계방법"] if recs else "담임 관찰 지속"
        df.at[idx, "담당자"] = "담임교사"
        df.at[idx, "기한"] = str(date.today())
        st.session_state.students = normalize_students(df)
        st.success(f"{sid} 학생의 체크리스트 결과를 저장했습니다.")


# -----------------------------------------------------------------------------
# 페이지 3: 담임교사 대시보드
# -----------------------------------------------------------------------------
def page_dashboard() -> None:
    school = st.session_state.school
    render_page_title(
        f"{school['학년']} {school['반']} 학맞통 지원 신호 대시보드",
        "담임교사는 본인 반 학생만 조회하도록 구성한 화면입니다.",
    )

    df = st.session_state.students
    total = len(df)
    input_done = len(df[df["주요신호"] != "특이 신호 없음"])
    support_needed = len(df[df["상태"].isin(["긴급", "지원필요"])])
    urgent_count = len(df[df["상태"] == "긴급"])
    meeting_needed = int(df["회의자료필요"].sum())

    metric_cols = st.columns(5)
    metrics = [
        ("전체 학생", f"{total}명", "담임 반 기준"),
        ("관찰 입력", f"{input_done}명", "체크리스트·관찰 메모"),
        ("지원 필요 제안", f"{support_needed}명", "긴급+지원필요"),
        ("긴급 검토", f"{urgent_count}명", "즉시 확인 대상"),
        ("회의자료 생성 필요", f"{meeting_needed}건", "학맞통 회의 후보"),
    ]
    for col, (label, value, help_text) in zip(metric_cols, metrics):
        with col:
            st.markdown(metric_card(label, value, help_text), unsafe_allow_html=True)

    left, right = st.columns([1.35, 1])
    with left:
        st.markdown("<div class='panel'><div class='panel-title'>지원 영역별 분포</div>", unsafe_allow_html=True)
        domain_counts = pd.DataFrame({"지원영역": DOMAINS, "학생수": [(df[d] > 0).sum() for d in DOMAINS]})
        chart_bar(domain_counts, "지원영역", "학생수", "")
        st.markdown("</div>", unsafe_allow_html=True)

        st.markdown("<div class='panel'><div class='panel-title'>지원 필요한 학생 목록</div>", unsafe_allow_html=True)
        filtered = df[df["상태"].isin(["긴급", "지원필요", "관찰"])].copy()
        filtered["정렬"] = filtered["상태"].map({"긴급": 0, "지원필요": 1, "관찰": 2, "안정": 3})
        filtered = filtered.sort_values(["정렬", "총점"], ascending=[True, False])
        for _, row in filtered.iterrows():
            render_student_card(row)
        st.markdown("</div>", unsafe_allow_html=True)

    with right:
        st.markdown("<div class='panel'><div class='panel-title'>위험도 분포</div>", unsafe_allow_html=True)
        risk_counts = df["상태"].value_counts().reindex(RISK_ORDER, fill_value=0).reset_index()
        risk_counts.columns = ["상태", "학생수"]
        chart_bar(risk_counts, "상태", "학생수", "")
        st.markdown("</div>", unsafe_allow_html=True)
        render_notice_panel()
        render_request_panel()


# -----------------------------------------------------------------------------
# 페이지 4: 학생 상세 리포트
# -----------------------------------------------------------------------------
def make_meeting_text(student: pd.Series, school: Dict, recs: List[Dict[str, str]]) -> str:
    top_domains = [d for d in DOMAINS if int(student[d]) > 0]
    top_domain_text = ", ".join(top_domains) if top_domains else "특이 신호 없음"
    rec_text = "\n".join([f"- {r['기관/서비스']}({r['구분']}): {r['연계방법']}" for r in recs[:5]])
    return f"""[학생맞춤통합지원 회의자료 초안]

1. 학생 코드: {student['학생코드']}
2. 학년/반: {student['학년']} {student['반']}
3. 지원 필요 제안: {student['상태']} / 우선순위 {student['우선순위']}
4. 우선 검토 영역: {top_domain_text}
5. 주요 관찰 신호: {student['주요신호']}

[학교 인프라]
- 위클래스: {'있음' if school.get('위클래스') else '없음'}
- 전문상담교사: {school.get('전문상담교사 수')}명
- 보건교사: {school.get('보건교사 수')}명
- 진로상담실: {'있음' if school.get('진로상담실') else '없음'}

[추천 연계 후보]
{rec_text}

[회의 검토 사항]
- 학생 본인 면담 필요 여부
- 보호자 상담 및 개인정보 이용 동의 확인
- 교내 단일사업 지원으로 해결 가능한지 여부
- 교육지원청 학생맞춤협력과 의뢰 필요 여부
- 지원 후 모니터링 일정

※ 이 자료는 자동 판정이 아니라 담임교사와 학교 협의체의 논의를 돕는 초안입니다.
"""


def make_parent_notice(student: pd.Series) -> str:
    return f"""[보호자 안내문 초안]

안녕하세요. 담임교사입니다.
최근 {student['이름']} 학생의 학교생활을 보다 세심하게 살피기 위해 상담 및 지원 방안을 검토하고자 합니다.
학교는 학생의 학습·정서·건강·복지 측면에서 필요한 도움을 조기에 확인하고, 보호자와 함께 적절한 지원 방법을 찾아가고자 합니다.

상담에서 다룰 수 있는 내용
- 학교생활 적응 및 학습 상황
- 또래 관계와 정서 상태
- 가정에서 관찰되는 변화
- 필요한 학교 내외 지원

상담 내용은 학생 지원 목적 범위에서 신중하게 다루겠습니다.
가능한 상담 일정을 회신해 주시면 감사하겠습니다.

※ 실제 발송 전 학교 내부 검토와 개인정보 동의 절차를 확인해야 합니다.
"""


def page_student_detail() -> None:
    render_page_title(
        "학생 상세 AI 리포트",
        "지원 필요로 제안된 이유, 판단 근거, 추천 조치, 회의자료 초안을 한 화면에서 확인합니다.",
    )
    df = st.session_state.students
    codes = df["학생코드"].tolist()
    selected = st.selectbox("학생 선택", codes, index=codes.index(st.session_state.selected_student))
    st.session_state.selected_student = selected
    student = df[df["학생코드"] == selected].iloc[0]
    recs = build_recommendations(student, st.session_state.school)

    col1, col2, col3 = st.columns([0.9, 1.4, 1])
    with col1:
        st.markdown("<div class='panel'><div class='panel-title'>학생 요약 카드</div>", unsafe_allow_html=True)
        st.markdown(
            f"""
            <table class="info-table">
                <tr><th>항목</th><th>내용</th></tr>
                <tr><td>학생코드</td><td>{student['학생코드']}</td></tr>
                <tr><td>학년·반</td><td>{student['학년']} {student['반']}</td></tr>
                <tr><td>지원상태</td><td>{student['상태']}</td></tr>
                <tr><td>우선순위</td><td>{student['우선순위']}</td></tr>
                <tr><td>담당자</td><td>{student['담당자']}</td></tr>
                <tr><td>기한</td><td>{student['기한']}</td></tr>
            </table>
            """,
            unsafe_allow_html=True,
        )
        st.markdown("</div>", unsafe_allow_html=True)
        render_student_card(student)

    with col2:
        st.markdown("<div class='panel'><div class='panel-title'>AI 리포트</div>", unsafe_allow_html=True)
        top_domains = sorted(DOMAINS, key=lambda d: int(student[d]), reverse=True)
        nonzero = [d for d in top_domains if int(student[d]) > 0]
        if nonzero:
            st.write(f"**우선 검토 영역:** {', '.join(nonzero[:3])}")
        else:
            st.write("**우선 검토 영역:** 현재 높은 지원 신호 없음")
        st.write(f"**관찰 신호 요약:** {student['주요신호']}")
        st.write("**판단 근거:**")
        for d in DOMAINS:
            if int(student[d]) > 0:
                st.write(f"- {d} 신호 {int(student[d])}점: 해당 영역의 교내·외 지원 검토 필요")
        if bool(student.get("긴급신호", False)):
            st.error("긴급 신호가 포함되어 있어 즉시 담임 확인, 상담교사 공유, 학맞통 회의 검토가 필요합니다.")
        st.info("이 결과는 자동 확정 판정이 아니라 교사와 학교 협의체가 검토할 수 있도록 정리한 참고자료입니다.")
        st.markdown("</div>", unsafe_allow_html=True)

        tabs = st.tabs(["회의자료 초안", "상담 질문", "보호자 안내문"])
        with tabs[0]:
            meeting_text = make_meeting_text(student, st.session_state.school, recs)
            st.text_area("회의자료", value=meeting_text, height=280)
            st.download_button("회의자료 TXT 다운로드", data=meeting_text.encode("utf-8-sig"), file_name=f"{student['학생코드']}_회의자료초안.txt", mime="text/plain")
        with tabs[1]:
            questions = [
                "최근 학교생활에서 가장 힘들었던 순간은 언제였나요?",
                "수업이나 과제 중 어떤 부분이 가장 어렵게 느껴지나요?",
                "친구 관계에서 불편하거나 걱정되는 일이 있나요?",
                "학교에서 어떤 도움을 받으면 좋겠다고 생각하나요?",
                "보호자와 함께 이야기해도 괜찮은 부분과 조심해야 할 부분은 무엇인가요?",
            ]
            for q in questions:
                st.write(f"- {q}")
        with tabs[2]:
            notice = make_parent_notice(student)
            st.text_area("보호자 안내문", value=notice, height=260)
            st.download_button("보호자 안내문 TXT 다운로드", data=notice.encode("utf-8-sig"), file_name=f"{student['학생코드']}_보호자안내문초안.txt", mime="text/plain")

    with col3:
        st.markdown("<div class='panel'><div class='panel-title'>추천 조치</div>", unsafe_allow_html=True)
        for i, rec in enumerate(recs, start=1):
            st.markdown(
                f"""
                <div class="recommend-card">
                    <b><span class="recommend-rank">{i}</span>{rec['기관/서비스']}</b><br>
                    <span class="small-muted">{rec['구분']} · {rec['지원영역']}</span><br>
                    <b>이유</b>: {rec['추천이유']}<br>
                    <b>방법</b>: {rec['연계방법']}
                </div>
                """,
                unsafe_allow_html=True,
            )
        st.markdown("</div>", unsafe_allow_html=True)


# -----------------------------------------------------------------------------
# 페이지 5: 지원 인프라 추천
# -----------------------------------------------------------------------------
def page_infra() -> None:
    render_page_title(
        "맞춤 지원 인프라 추천",
        "학생 신호와 학교 인프라를 함께 반영해 위클래스, 위(Wee)센터, 지역기관 추천 순서를 다르게 보여줍니다.",
    )
    df = st.session_state.students
    codes = df["학생코드"].tolist()
    selected = st.selectbox("학생 선택", codes, index=codes.index(st.session_state.selected_student))
    st.session_state.selected_student = selected
    student = df[df["학생코드"] == selected].iloc[0]
    recs = build_recommendations(student, st.session_state.school)

    st.markdown("<div class='panel'><div class='panel-title'>추천 기준 요약</div>", unsafe_allow_html=True)
    school = st.session_state.school
    st.write(
        f"현재 학교는 위클래스 {'있음' if school.get('위클래스') else '없음'}, "
        f"전문상담교사 {school.get('전문상담교사 수')}명, 보건교사 {school.get('보건교사 수')}명, "
        f"진로상담실 {'있음' if school.get('진로상담실') else '없음'}으로 설정되어 있습니다."
    )
    st.write("위클래스가 있으면 심리·정서 학생의 1순위 추천을 교내 위클래스로 두고, 긴급 신호가 있으면 교육지원청·전문기관을 함께 노출합니다.")
    st.markdown("</div>", unsafe_allow_html=True)

    tab_all, tab_school, tab_office, tab_region = st.tabs(["전체 추천", "교내 인프라", "교육지원청", "지역사회"])
    tab_map = {
        "전체 추천": tab_all,
        "교내": tab_school,
        "교육지원청": tab_office,
        "교육지원청/지역": tab_office,
        "지역사회": tab_region,
    }

    with tab_all:
        for i, rec in enumerate(recs, start=1):
            st.markdown(
                f"""
                <div class="recommend-card">
                    <b><span class="recommend-rank">{i}</span>{rec['기관/서비스']}</b><br>
                    <span class="small-muted">{rec['구분']} · {rec['지원영역']}</span><br>
                    <b>추천 이유</b>: {rec['추천이유']}<br>
                    <b>연계 방법</b>: {rec['연계방법']}
                </div>
                """,
                unsafe_allow_html=True,
            )

    for category, tab in [("교내", tab_school), ("교육지원청", tab_office), ("지역사회", tab_region)]:
        with tab:
            filtered = [r for r in recs if category in r["구분"]]
            if not filtered:
                st.info(f"현재 선택 학생에게 우선 추천되는 {category} 인프라가 없습니다.")
            for i, rec in enumerate(filtered, start=1):
                st.markdown(
                    f"""
                    <div class="recommend-card">
                        <b><span class="recommend-rank">{i}</span>{rec['기관/서비스']}</b><br>
                        <span class="small-muted">{rec['지원영역']}</span><br>
                        {rec['추천이유']}<br>
                        <b>연계</b>: {rec['연계방법']}
                    </div>
                    """,
                    unsafe_allow_html=True,
                )


# -----------------------------------------------------------------------------
# 페이지 6: 지원 현황표 다운로드
# -----------------------------------------------------------------------------
def make_status_table(df: pd.DataFrame) -> pd.DataFrame:
    table = df.copy()
    table["지원영역"] = table.apply(lambda r: ", ".join([d for d in DOMAINS if int(r[d]) > 0]) or "-", axis=1)
    table["추천 인프라"] = table.apply(
        lambda r: " / ".join([rec["기관/서비스"] for rec in build_recommendations(r, st.session_state.school)[:2]]),
        axis=1,
    )
    table["다음 할 일"] = table["추천첫조치"]
    return table[
        [
            "학생코드",
            "우선순위",
            "지원영역",
            "주요신호",
            "상태",
            "추천 인프라",
            "다음 할 일",
            "담당자",
            "기한",
        ]
    ]


def to_excel_bytes(df: pd.DataFrame) -> bytes:
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="지원현황")
    return output.getvalue()


def page_status_table() -> None:
    render_page_title(
        "지원 현황표",
        "회의 준비, 지원 진행 상황, 교육지원청 의뢰 여부를 표로 관리하고 다운로드합니다.",
    )
    df = st.session_state.students.copy()

    col1, col2, col3 = st.columns(3)
    with col1:
        status_filter = st.multiselect("상태", RISK_ORDER, default=["긴급", "지원필요", "관찰"])
    with col2:
        domain_filter = st.multiselect("지원 영역", DOMAINS, default=[])
    with col3:
        manager_filter = st.multiselect("담당자", sorted(df["담당자"].unique()), default=[])

    filtered = df[df["상태"].isin(status_filter)] if status_filter else df
    if domain_filter:
        mask = filtered[domain_filter].sum(axis=1) > 0
        filtered = filtered[mask]
    if manager_filter:
        filtered = filtered[filtered["담당자"].isin(manager_filter)]

    table = make_status_table(filtered)
    st.dataframe(table, use_container_width=True, hide_index=True)

    col_a, col_b, col_c = st.columns([1, 1, 2])
    csv = table.to_csv(index=False).encode("utf-8-sig")
    with col_a:
        st.download_button("CSV 다운로드", data=csv, file_name="학맞통_지원현황표.csv", mime="text/csv", use_container_width=True)
    with col_b:
        st.download_button("Excel 다운로드", data=to_excel_bytes(table), file_name="학맞통_지원현황표.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)
    with col_c:
        st.info("다운로드 표에는 실제 학생 이름 대신 학생코드만 포함했습니다.")


# -----------------------------------------------------------------------------
# 페이지 7: 데이터·모델 설명
# -----------------------------------------------------------------------------
def page_data_model() -> None:
    render_page_title(
        "데이터·AI 활용 설명",
        "대회 제출서에 넣을 수 있도록 활용 데이터, 로직, 개인정보 처리 원칙을 요약합니다.",
    )

    st.markdown("<div class='panel'><div class='panel-title'>MVP 구현 범위</div>", unsafe_allow_html=True)
    st.write(
        "현재 프로토타입은 실제 학생 개인정보를 사용하지 않고, 익명 학생코드와 가상 관찰 체크리스트를 사용합니다. "
        "지원 필요 신호 분류는 규칙 기반 점수화로 구현했고, 향후 공공데이터 및 학교별 인프라 데이터를 연결해 추천 순서를 정교화할 수 있습니다."
    )
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("<div class='panel'><div class='panel-title'>활용 데이터 연결 후보</div>", unsafe_allow_html=True)
    data_rows = [
        ["학교알리미/교육통계", "학교별 시설, 진로상담실, 교원 1인당 학생수, 상담·보건교사 수", "학교 인프라 기반 추천 순서 조정"],
        ["한국교육고용패널", "학업·진로, 심리·정서, 경제·복지 관련 학생 특성 변수", "지원 필요 신호 가중치 및 유형화 근거"],
        ["서울시/교육청 공공데이터", "청소년상담복지센터, Wee센터, 지역교육복지센터, 지역학습진단성장센터", "지역자원 추천 후보 목록"],
        ["교사 입력", "가상 학생 시나리오, 관찰 체크리스트, 상담 메모", "개별 학생 리포트 생성"],
    ]
    st.dataframe(pd.DataFrame(data_rows, columns=["데이터", "사용 항목", "서비스 내 역할"]), use_container_width=True, hide_index=True)
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("<div class='panel'><div class='panel-title'>선택적으로 같은 폴더의 분석 파일 연결</div>", unsafe_allow_html=True)
    base = Path(__file__).parent
    optional_files = [
        "상관분석용_공통지표.csv",
        "분석_1단계_지표간_상관분석.xlsx",
        "분석_2단계_4영역_KMeans_군집분석결과.xlsx",
    ]
    file_rows = []
    for name in optional_files:
        path = base / name
        status = "연결 가능" if path.exists() else "현재 폴더에 없음"
        detail = ""
        if path.exists():
            try:
                if name.endswith(".csv"):
                    data = pd.read_csv(path)
                else:
                    data = pd.read_excel(path)
                detail = f"{data.shape[0]}행 × {data.shape[1]}열"
            except Exception as e:
                detail = f"읽기 실패: {e}"
        file_rows.append([name, status, detail])
    st.dataframe(pd.DataFrame(file_rows, columns=["파일명", "상태", "요약"]), use_container_width=True, hide_index=True)
    st.caption("실제 데이터 연결 시에는 파일 컬럼명에 맞춰 load_demo_students()와 추천 점수 계산 함수를 교체하면 됩니다.")
    st.markdown("</div>", unsafe_allow_html=True)


# -----------------------------------------------------------------------------
# 사이드바 및 메인 라우팅
# -----------------------------------------------------------------------------
def render_sidebar() -> str:
    school = st.session_state.school
    st.sidebar.markdown("### 👤 승인사항")
    st.sidebar.caption("실제 업무포털의 좌측 메뉴 구조를 참고한 데모 메뉴입니다.")
    st.sidebar.metric("미결/협조함", 0)
    st.sidebar.metric("공람함", 130)
    st.sidebar.divider()

    st.sidebar.markdown("### 기본 메뉴")
    page = st.sidebar.radio(
        "화면 선택",
        [
            "학교 입력",
            "학생 체크리스트 입력",
            "담임교사 대시보드",
            "학생 상세 리포트",
            "지원 인프라 추천",
            "지원 현황표",
            "데이터·AI 설명",
        ],
        label_visibility="collapsed",
    )
    st.sidebar.divider()
    st.sidebar.markdown("### 현재 조회 권한")
    st.sidebar.write(f"학교: **{school['학교명']}**")
    st.sidebar.write(f"역할: **학급담임**")
    st.sidebar.write(f"범위: **{school['학년']} {school['반']}만**")
    st.sidebar.caption("대회 제출용 화면에서는 학교명·개인명 등 식별정보를 익명 처리하세요.")
    return page


def main() -> None:
    inject_css()
    init_state()
    render_header()
    page = render_sidebar()

    if page == "학교 입력":
        page_school_input()
    elif page == "학생 체크리스트 입력":
        page_checklist()
    elif page == "담임교사 대시보드":
        page_dashboard()
    elif page == "학생 상세 리포트":
        page_student_detail()
    elif page == "지원 인프라 추천":
        page_infra()
    elif page == "지원 현황표":
        page_status_table()
    elif page == "데이터·AI 설명":
        page_data_model()

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
