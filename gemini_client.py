# -*- coding: utf-8 -*-
"""Gemini API 공통 호출 모듈.

Streamlit secrets 또는 환경변수에서 Gemini API 키를 읽고,
기능별 검증 함수를 통과한 JSON 응답만 다음 단계로 넘기기 위한 공통 유틸입니다.
"""
from __future__ import annotations

import os
import re
import time
import random
from datetime import datetime
from typing import Any, Callable, Dict, Optional

import streamlit as st


def _secret_get(key: str, default: Optional[str] = None) -> Optional[str]:
    try:
        value = st.secrets.get(key, None)
        if value:
            return str(value)
    except Exception:
        pass
    return default


def get_gemini_api_key() -> Optional[str]:
    return _secret_get("GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")


def get_gemini_model() -> str:
    return _secret_get("GEMINI_MODEL") or os.getenv("GEMINI_MODEL") or "gemini-2.5-flash"


@st.cache_resource(show_spinner=False)
def get_gemini_client(api_key: Optional[str] = None):
    api_key = api_key or get_gemini_api_key()
    if not api_key:
        return None
    try:
        from google import genai
        return genai.Client(api_key=api_key)
    except Exception as exc:
        raise RuntimeError(f"Gemini 클라이언트를 초기화하지 못했습니다: {exc}") from exc


def strip_json_code_fence(text: str) -> str:
    if text is None:
        return ""
    t = str(text).strip()
    # ```json ... ``` 또는 ``` ... ``` 제거
    m = re.match(r"^```(?:json)?\s*(.*?)\s*```$", t, flags=re.IGNORECASE | re.DOTALL)
    if m:
        return m.group(1).strip()
    return t


def extract_text_from_gemini_response(response: Any) -> str:
    if hasattr(response, "text") and response.text is not None:
        return str(response.text)
    try:
        return response.candidates[0].content.parts[0].text
    except Exception:
        return str(response)




def _safe_session_get(key: str, default: Any = None) -> Any:
    try:
        return st.session_state.get(key, default)
    except Exception:
        return default


def _safe_session_set(key: str, value: Any) -> None:
    try:
        st.session_state[key] = value
    except Exception:
        pass


def _record_gemini_call(model: str) -> None:
    """현재 Streamlit 세션에서 실제 Gemini API 호출 횟수를 기록한다.

    Google 쪽 quota의 공식 카운터는 아니지만, 버튼 한 번에 몇 회 호출되는지
    앱 내부에서 추적하기 위한 값이다.
    """
    count = int(_safe_session_get("gemini_call_count_session", 0) or 0) + 1
    _safe_session_set("gemini_call_count_session", count)
    log = list(_safe_session_get("gemini_call_log_session", []) or [])
    log.append({"time": datetime.now().strftime("%H:%M:%S"), "model": model})
    _safe_session_set("gemini_call_log_session", log[-30:])


def _friendly_gemini_error(exc: Exception) -> str:
    raw = str(exc)
    if "RESOURCE_EXHAUSTED" in raw or "429" in raw:
        retry = ""
        m = re.search(r"retryDelay['\"]?\s*[:=]\s*['\"]?(\d+)s", raw)
        if m:
            retry = f" 약 {m.group(1)}초 뒤 다시 시도할 수 있습니다."
        return (
            "Gemini API 사용량 제한에 걸렸습니다. "
            "무료 등급에서는 RPM/RPD 제한이 낮고, 검증 실패 시 재호출이 추가로 발생할 수 있습니다."
            + retry
            + " 앱에서는 이번 요청 결과를 저장하지 않았습니다."
        )
    if "PERMISSION_DENIED" in raw or "403" in raw:
        return "Gemini API 프로젝트 또는 API 키 접근 권한이 거부되었습니다. API 키가 속한 프로젝트와 결제/권한 설정을 확인해 주세요."
    if "UNAVAILABLE" in raw or "503" in raw:
        return "Gemini 모델 서버가 일시적으로 혼잡합니다. 잠시 후 다시 시도하거나 더 가벼운 모델을 사용해 주세요."
    return raw




def _friendly_validation_failure(message: str) -> str:
    """LLM 출력 검증 실패 사유를 사용자에게 직접 노출하지 않기 위한 문구."""
    return (
        "생성된 내용을 학교 업무 표현 기준에 맞게 정리하지 못했습니다. "
        "다시 생성해 주세요."
    )


def _get_int_setting(key: str, default: int) -> int:
    try:
        value = _secret_get(key)
        if value is None:
            value = os.getenv(key)
        if value is None or value == "":
            return default
        return int(value)
    except Exception:
        return default


def _is_transient_503(exc: Exception) -> bool:
    raw = str(exc)
    return "UNAVAILABLE" in raw or "503" in raw or "high demand" in raw.lower()


def _transient_retry_sleep(attempt: int) -> None:
    # 503은 모델 서버 혼잡/일시 용량 부족일 때 발생하므로 짧은 지수 백오프를 적용한다.
    # 무료 티어 quota 보호를 위해 기본 재시도 횟수는 낮게 둔다.
    base = _get_int_setting("GEMINI_TRANSIENT_RETRY_BASE_SECONDS", 4)
    delay = min(15, base * (2 ** attempt)) + random.uniform(0, 1.0)
    time.sleep(delay)


def call_llm(system_prompt: str, user_prompt: str, response_schema: Any = None) -> str:
    api_key = get_gemini_api_key()
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY가 설정되어 있지 않습니다.")
    client = get_gemini_client(api_key)
    if client is None:
        raise RuntimeError("Gemini API 키가 설정되어 있지 않습니다.")

    try:
        from google.genai import types
    except Exception as exc:
        raise RuntimeError("google-genai 패키지가 설치되어 있지 않습니다. requirements.txt를 확인해 주세요.") from exc

    config_kwargs: Dict[str, Any] = {
        "system_instruction": system_prompt,
        "temperature": 0.2,
        "response_mime_type": "application/json",
    }
    if response_schema is not None:
        config_kwargs["response_schema"] = response_schema

    model = get_gemini_model()

    max_transient_retries = _get_int_setting("GEMINI_TRANSIENT_RETRIES", 1)
    last_exc = None
    for attempt in range(max_transient_retries + 1):
        try:
            _record_gemini_call(model)
            response = client.models.generate_content(
                model=model,
                contents=user_prompt,
                config=types.GenerateContentConfig(**config_kwargs),
            )
            return strip_json_code_fence(extract_text_from_gemini_response(response))
        except Exception as exc:
            last_exc = exc
            if attempt < max_transient_retries and _is_transient_503(exc):
                _transient_retry_sleep(attempt)
                continue
            raise
    raise last_exc if last_exc is not None else RuntimeError("Gemini 호출에 실패했습니다.")


def call_llm_with_validation(
    system_prompt: str,
    user_prompt: str,
    validate_func: Callable[..., Dict[str, Any]],
    repair_prompt_builder: Callable[[str, str], str],
    validation_kwargs: Optional[Dict[str, Any]] = None,
    response_schema: Any = None,
    max_retry: int = 1,
) -> Dict[str, Any]:
    validation_kwargs = validation_kwargs or {}
    try:
        output = call_llm(system_prompt, user_prompt, response_schema=response_schema)
    except Exception as exc:
        return {"success": False, "data": None, "raw_output": "", "retried": False, "error": _friendly_gemini_error(exc), "internal_error": str(exc), "warnings": []}

    validation = validate_func(output, **validation_kwargs)
    if validation.get("ok"):
        return {
            "success": True,
            "data": validation.get("parsed_data"),
            "raw_output": output,
            "retried": False,
            "error": None,
            "warnings": validation.get("warnings", []),
        }

    previous_output = output
    last_error = validation.get("message", "검증 실패")
    warnings = validation.get("warnings", [])

    retried = False
    for _ in range(max_retry):
        retried = True
        repair_prompt = repair_prompt_builder(last_error, previous_output)
        try:
            repaired = call_llm(system_prompt, repair_prompt, response_schema=response_schema)
        except Exception as exc:
            return {
                "success": False,
                "data": None,
                "raw_output": previous_output,
                "retried": retried,
                "error": _friendly_gemini_error(exc),
                "internal_error": str(exc),
                "warnings": warnings,
            }
        validation2 = validate_func(repaired, **validation_kwargs)
        if validation2.get("ok"):
            return {
                "success": True,
                "data": validation2.get("parsed_data"),
                "raw_output": repaired,
                "retried": retried,
                "error": None,
                "warnings": validation2.get("warnings", []),
            }
        previous_output = repaired
        last_error = validation2.get("message", "검증 실패")
        warnings = validation2.get("warnings", [])

    return {
        "success": False,
        "data": None,
        "raw_output": previous_output,
        "retried": retried,
        "error": _friendly_validation_failure(str(last_error)),
        "internal_error": str(last_error),
        "warnings": warnings,
    }
