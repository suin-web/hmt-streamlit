# -*- coding: utf-8 -*-
"""Gemini API 공통 호출 모듈.

Streamlit secrets 또는 환경변수에서 Gemini API 키를 읽고,
기능별 검증 함수를 통과한 JSON 응답만 다음 단계로 넘기기 위한 공통 유틸입니다.
"""
from __future__ import annotations

import os
import re
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

    response = client.models.generate_content(
        model=get_gemini_model(),
        contents=user_prompt,
        config=types.GenerateContentConfig(**config_kwargs),
    )
    return strip_json_code_fence(extract_text_from_gemini_response(response))


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
        return {"success": False, "data": None, "raw_output": "", "retried": False, "error": str(exc), "warnings": []}

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
                "error": str(exc),
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
        "error": last_error,
        "warnings": warnings,
    }
