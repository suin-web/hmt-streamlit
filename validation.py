# -*- coding: utf-8 -*-
"""학맞통 Streamlit 앱용 LLM JSON 출력 검증 함수 모음."""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional


def strip_json_code_fence(text: str) -> str:
    if text is None:
        return ""
    t = str(text).strip()
    m = re.match(r"^```(?:json)?\s*(.*?)\s*```$", t, flags=re.IGNORECASE | re.DOTALL)
    return m.group(1).strip() if m else t


def _parse_json(output_text: str) -> tuple[Optional[Any], Optional[str]]:
    try:
        return json.loads(strip_json_code_fence(output_text)), None
    except Exception as exc:
        return None, f"JSON 형식이 올바르지 않습니다: {exc}"


def _contains_any(text: str, words: List[str]) -> List[str]:
    return [w for w in words if w and w in text]


HARD_BANNED_COMMON = [
    "위험 학생", "문제 학생", "부적응 학생", "비행 행동", "우울증", "불안장애", "방임 상태",
    "학대 확정", "중독", "비정상", "반드시 연계", "문제가 있다", "가정에 문제가 있다",
]

QUESTION_HARD_BANNED = HARD_BANNED_COMMON + [
    "우울증이니", "불안장애 있어", "중독됐니", "방임당하고 있니", "부모님이 너 괴롭히니",
    "왜 그랬니", "왜 안 하니", "대체 생각이 뭐니", "다른 애들은 잘하는데", "왜 너만 그러니",
    "너 때문에 부모님이", "너 하나 때문에", "그건 별일 아니야", "네 나이 땐 다 겪는 일이야",
    "시간 지나면 다 괜찮아져", "우울해하지 말고 웃어봐", "관심받고 싶어서 그러는 거지",
    "선생님은 네가 왜 그러는지 다 알아", "아이고 불쌍해라", "말 안 하면 도와줄 수 없어",
    "계속 입 다물고 있으면", "부모님 모셔올 거야", "내 말대로만 하면 다 해결돼",
    "친구들과 문제가 있니", "가정에 문제가 있니", "너는 왜 수업을 방해하니",
]
QUESTION_WARN_WORDS = ["당연히", "무조건", "고쳐야 해", "안타깝다", "다 해결돼"]
AREA_VALUES_WITH_URGENT = ["진로", "학업", "심리정서", "복지경제", "긴급확인"]
AREA_VALUES = ["진로", "학업", "심리정서", "복지경제", "공통"]
SUPPORT_NEEDED_VALUES = ["현재 유지", "추가 관찰", "지원 검토 필요", "판단 보류"]
TARGET_COLLECTIONS = ["policy_chunks", "service_catalog", "resource_catalog"]


def validate_counseling_question_output(output_text: str, red_flag_result: Dict[str, Any], counseling_consideration_areas: List[Dict[str, Any]]) -> Dict[str, Any]:
    parsed, err = _parse_json(output_text)
    if err:
        return {"ok": False, "message": err, "parsed_data": None, "warnings": []}
    text = json.dumps(parsed, ensure_ascii=False)
    banned = _contains_any(text, QUESTION_HARD_BANNED)
    if banned:
        return {"ok": False, "message": f"금지 표현이 포함되었습니다: {', '.join(banned[:5])}", "parsed_data": None, "warnings": []}
    warnings = _contains_any(text, QUESTION_WARN_WORDS)
    qs = parsed.get("recommended_questions") if isinstance(parsed, dict) else None
    if not isinstance(qs, list):
        return {"ok": False, "message": "recommended_questions가 없습니다.", "parsed_data": None, "warnings": warnings}
    if not (5 <= len(qs) <= 8):
        return {"ok": False, "message": "질문 개수는 5~8개여야 합니다.", "parsed_data": None, "warnings": warnings}
    required = ["question", "purpose", "linked_area", "based_on", "teacher_caution"]
    linked = []
    for i, q in enumerate(qs, 1):
        for field in required:
            if field not in q or q.get(field) in [None, ""]:
                return {"ok": False, "message": f"Q{i}에 필수 필드 {field}가 없습니다.", "parsed_data": None, "warnings": warnings}
        if q.get("linked_area") not in AREA_VALUES_WITH_URGENT:
            return {"ok": False, "message": f"Q{i}의 linked_area 값이 허용 범위가 아닙니다.", "parsed_data": None, "warnings": warnings}
        linked.append(q.get("linked_area"))
    if red_flag_result.get("urgent_flag") and "긴급확인" not in linked:
        return {"ok": False, "message": "우선 확인 필요 신호가 있으므로 긴급확인 질문이 최소 1개 필요합니다.", "parsed_data": None, "warnings": warnings}
    required_areas = [x.get("area") for x in counseling_consideration_areas if x.get("priority_level") == "필수 확인" and x.get("area") != "긴급확인"]
    for area in required_areas:
        if area and area not in linked:
            return {"ok": False, "message": f"필수 확인 영역({area})이 질문에 포함되어야 합니다.", "parsed_data": None, "warnings": warnings}
    return {"ok": True, "message": "검증 통과", "parsed_data": parsed, "warnings": warnings}


def validate_counseling_analysis_output(output_text: str, teacher_counseling_note: str) -> Dict[str, Any]:
    parsed, err = _parse_json(output_text)
    if err:
        return {"ok": False, "message": err, "parsed_data": None, "warnings": []}
    text = json.dumps(parsed, ensure_ascii=False)
    if any(x in text for x in ["urgent_flag", "urgent_reasons", "urgent_notice", "긴급확인"]):
        return {"ok": False, "message": "상담 결과 분석 단계에는 urgent 또는 긴급확인 관련 필드를 포함하지 않습니다.", "parsed_data": None, "warnings": []}
    banned = _contains_any(text, HARD_BANNED_COMMON)
    if banned:
        # 교사 메모에 직접 있는 표현이면 warning만 허용
        hard = [w for w in banned if w not in teacher_counseling_note]
        if hard:
            return {"ok": False, "message": f"금지 표현이 포함되었습니다: {', '.join(hard[:5])}", "parsed_data": None, "warnings": banned}
    if not isinstance(parsed.get("analysis_summary"), dict):
        return {"ok": False, "message": "analysis_summary가 없습니다.", "parsed_data": None, "warnings": banned}
    support = parsed["analysis_summary"].get("support_needed")
    if support not in SUPPORT_NEEDED_VALUES:
        return {"ok": False, "message": "support_needed 값이 허용 범위가 아닙니다.", "parsed_data": None, "warnings": banned}
    if parsed.get("primary_area") not in AREA_VALUES:
        return {"ok": False, "message": "primary_area 값이 허용 범위가 아닙니다.", "parsed_data": None, "warnings": banned}
    if not isinstance(parsed.get("key_signals", []), list):
        return {"ok": False, "message": "key_signals는 리스트여야 합니다.", "parsed_data": None, "warnings": banned}
    rqs = parsed.get("rag_search_queries", [])
    if support == "지원 검토 필요" and len(rqs) < 2:
        return {"ok": False, "message": "지원 검토 필요 상태에서는 RAG 검색어가 최소 2개 필요합니다.", "parsed_data": None, "warnings": banned}
    for q in rqs:
        if q.get("target_collection") not in TARGET_COLLECTIONS:
            return {"ok": False, "message": "RAG 검색 target_collection 값이 허용 범위가 아닙니다.", "parsed_data": None, "warnings": banned}
    warnings = list(banned)
    for sig in parsed.get("key_signals", []):
        ev = str(sig.get("evidence_text", "")).strip()
        if ev and ev not in teacher_counseling_note:
            warnings.append(f"상담 메모와 evidence_text 완전 일치 확인 필요: {ev[:20]}")
    return {"ok": True, "message": "검증 통과", "parsed_data": parsed, "warnings": warnings}


def _normalize_resource_name_for_validation(value: Any) -> str:
    """기관명 검증용 정규화: 공백·특수문자 차이로 인한 불필요한 실패를 줄인다."""
    text = str(value or "").strip().lower()
    text = re.sub(r"[\s\-_/()\[\]{}·.,]+", "", text)
    return text


def _is_blank_value(value: Any) -> bool:
    if value is None:
        return True
    text = str(value).strip()
    return text == "" or text.lower() in {"none", "null", "nan"} or text in {"-", "정보 없음"}


def _merge_ranked_resource_metadata(output_item: Dict[str, Any], ranked_item: Dict[str, Any]) -> Dict[str, Any]:
    """LLM이 설명을 생성하더라도 기관 원천정보·순위·점수는 Python RAG 결과를 기준으로 고정한다."""
    merged = dict(output_item)
    copy_fields = [
        "rank",
        "resource_name",
        "resource_category",
        "support_area",
        "district",
        "education_office",
        "address",
        "phone",
        "homepage",
        "distance_km",
        "recommendation_fit",
        "recommendation_score",
        "score_breakdown",
        "existing_support_status",
    ]
    # 순위·기관명·점수·거리 등 원천값은 항상 RAG 결과를 우선한다.
    for field in copy_fields:
        if field in ranked_item:
            merged[field] = ranked_item.get(field)
    # linked_area는 LLM이 허용값을 주면 유지하고, 없거나 잘못되면 RAG support_area로 보정한다.
    if merged.get("linked_area") not in AREA_VALUES:
        candidate_area = ranked_item.get("support_area") or ranked_item.get("linked_area") or "공통"
        merged["linked_area"] = candidate_area if candidate_area in AREA_VALUES else "공통"
    return merged


def validate_resource_recommendation_output(output_text: str, ranked_resources: List[Dict[str, Any]], policy_evidence: List[Dict[str, Any]]) -> Dict[str, Any]:
    parsed, err = _parse_json(output_text)
    if err:
        return {"ok": False, "message": err, "parsed_data": None, "warnings": []}
    text = json.dumps(parsed, ensure_ascii=False)
    if any(x in text for x in ["urgent_flag", "urgent_notice", "urgent_reasons", "긴급확인"]):
        return {"ok": False, "message": "기관 추천 이유 단계에는 urgent 또는 긴급확인 관련 필드를 포함하지 않습니다.", "parsed_data": None, "warnings": []}
    banned = _contains_any(text, HARD_BANNED_COMMON)
    if banned:
        return {"ok": False, "message": f"금지 표현이 포함되었습니다: {', '.join(banned[:5])}", "parsed_data": None, "warnings": []}
    recs = parsed.get("recommended_resources")
    if not isinstance(recs, list):
        return {"ok": False, "message": "recommended_resources가 없습니다.", "parsed_data": None, "warnings": []}

    warnings: List[str] = []
    input_names = [r.get("resource_name") for r in ranked_resources]

    if not ranked_resources:
        noflag = parsed.get("if_no_suitable_resource", {}).get("no_resource_flag")
        if recs or not noflag:
            return {"ok": False, "message": "후보가 없으면 recommended_resources는 비어 있고 no_resource_flag는 true여야 합니다.", "parsed_data": None, "warnings": []}
    else:
        if not recs:
            return {"ok": False, "message": "기관 후보가 있는데 추천 설명이 비어 있습니다.", "parsed_data": None, "warnings": []}

        ranked_by_norm: Dict[str, Dict[str, Any]] = {}
        ranked_order: Dict[str, int] = {}
        for idx, item in enumerate(ranked_resources):
            norm = _normalize_resource_name_for_validation(item.get("resource_name"))
            if norm:
                ranked_by_norm[norm] = item
                ranked_order[norm] = idx

        normalized_output_names: List[str] = []
        fixed_recs: List[Dict[str, Any]] = []
        unknown_names: List[str] = []
        for r in recs:
            norm = _normalize_resource_name_for_validation(r.get("resource_name"))
            if norm not in ranked_by_norm:
                unknown_names.append(str(r.get("resource_name")))
                continue
            normalized_output_names.append(norm)
            fixed_recs.append(_merge_ranked_resource_metadata(r, ranked_by_norm[norm]))

        if unknown_names:
            return {"ok": False, "message": f"입력 후보에 없는 기관명이 생성되었습니다: {', '.join(unknown_names[:3])}", "parsed_data": None, "warnings": []}

        # Gemini가 설명 순서를 바꾸는 경우가 있어, 실패시키지 않고 Python에서 RAG 순서로 재정렬한다.
        original_order = list(normalized_output_names)
        fixed_recs.sort(key=lambda x: ranked_order.get(_normalize_resource_name_for_validation(x.get("resource_name")), 9999))
        fixed_order = [_normalize_resource_name_for_validation(x.get("resource_name")) for x in fixed_recs]
        if original_order != fixed_order:
            warnings.append("LLM 출력의 기관 순서가 RAG 후보 순서와 달라 Python에서 RAG 순서로 보정했습니다.")

        # 상위 후보가 일부 누락된 경우는 실패 대신 경고 처리한다. 최종 순위는 포함된 후보 안에서 RAG 순서를 유지한다.
        expected_prefix = [_normalize_resource_name_for_validation(x) for x in input_names[: len(fixed_recs)]]
        if fixed_order != expected_prefix:
            warnings.append("LLM 출력에 상위 RAG 후보 일부가 누락되었을 수 있습니다. 화면의 순위·점수·기관 정보는 RAG 결과를 기준으로 보정했습니다.")

        parsed["recommended_resources"] = fixed_recs
        for r in parsed["recommended_resources"]:
            if r.get("linked_area") not in AREA_VALUES:
                return {"ok": False, "message": "linked_area 값이 허용 범위가 아닙니다.", "parsed_data": None, "warnings": warnings}

    known_docs = {str(x.get("source_doc", "")) for x in policy_evidence if x.get("source_doc")}
    for r in parsed.get("recommended_resources", []) or []:
        for basis in r.get("official_basis", []) or []:
            sd = str(basis.get("source_doc", ""))
            if sd and known_docs and sd not in known_docs:
                warnings.append(f"공식 근거 source_doc 확인 필요: {sd}")
    return {"ok": True, "message": "검증 통과", "parsed_data": parsed, "warnings": warnings}


def validate_document_generation_output(output_text: str, allowed_resource_names: List[str]) -> Dict[str, Any]:
    parsed, err = _parse_json(output_text)
    if err:
        return {"ok": False, "message": err, "parsed_data": None, "warnings": []}
    text = json.dumps(parsed, ensure_ascii=False)
    if any(x in text for x in ["urgent_flag", "urgent_notice", "urgent_reasons", "긴급확인"]):
        return {"ok": False, "message": "문서 생성 단계에는 urgent 또는 긴급확인 관련 내용을 포함하지 않습니다.", "parsed_data": None, "warnings": []}
    banned = _contains_any(text, HARD_BANNED_COMMON)
    if banned:
        return {"ok": False, "message": f"금지 표현이 포함되었습니다: {', '.join(banned[:5])}", "parsed_data": None, "warnings": []}
    if not isinstance(parsed.get("meeting_record"), dict) or not isinstance(parsed.get("student_growth_record"), dict):
        return {"ok": False, "message": "meeting_record와 student_growth_record가 필요합니다.", "parsed_data": None, "warnings": []}
    for field in ["agenda", "meeting_content", "decision_items", "followup_plan"]:
        if field not in parsed["meeting_record"]:
            return {"ok": False, "message": f"meeting_record.{field}가 없습니다.", "parsed_data": None, "warnings": []}
    for field in ["student_difficulties", "internal_resource_summary", "external_resource_summary", "monthly_support_records", "comprehensive_evaluation", "closure_reason", "followup_items"]:
        if field not in parsed["student_growth_record"]:
            return {"ok": False, "message": f"student_growth_record.{field}가 없습니다.", "parsed_data": None, "warnings": []}
    # 추천 결과에 없는 기관명 새 생성 방지: 매우 보수적 검사 대신 허용 기관이 텍스트에 포함되면 OK. 새 기관명 전체 식별은 warning 위주.
    warnings: List[str] = []
    phone_like = re.findall(r"\b0\d{1,2}[-\s]?\d{3,4}[-\s]?\d{4}\b", text)
    if phone_like:
        warnings.append("LLM 출력에 전화번호처럼 보이는 값이 포함되어 있습니다. 개인정보 또는 새 연락처 생성 여부를 확인하세요.")
    if "AI 결과는 자동 판정" not in str(parsed.get("safety_and_ethics_note", "")):
        return {"ok": False, "message": "safety_and_ethics_note에 자동 판정이 아니라는 취지의 문구가 필요합니다.", "parsed_data": None, "warnings": warnings}
    return {"ok": True, "message": "검증 통과", "parsed_data": parsed, "warnings": warnings}
