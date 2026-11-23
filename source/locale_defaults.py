from __future__ import annotations

import logging
from typing import Any

from .components.geometry_adapter import acquire_geometry_worker
from .constants import VERSION
from .environment import is_dev_mode
from .i18n import (
    LANGUAGE_AR,
    LANGUAGE_DE,
    LANGUAGE_EN,
    LANGUAGE_ES,
    LANGUAGE_FR,
    LANGUAGE_IT,
    LANGUAGE_JA,
    LANGUAGE_KO,
    LANGUAGE_PT,
    LANGUAGE_PT_BR,
    LANGUAGE_RU,
    LANGUAGE_TR,
    LANGUAGE_ZH,
)

logger = logging.getLogger(__name__)

COUNTRY_CODE_TIMEOUT_SECONDS = 10

_COUNTRY_LANGUAGE_MAP: dict[str, str] = {
    "AD": LANGUAGE_ES,
    "AR": LANGUAGE_ES,
    "AE": LANGUAGE_AR,
    "BH": LANGUAGE_AR,
    "DZ": LANGUAGE_AR,
    "EG": LANGUAGE_AR,
    "IQ": LANGUAGE_AR,
    "JO": LANGUAGE_AR,
    "KW": LANGUAGE_AR,
    "LB": LANGUAGE_AR,
    "LY": LANGUAGE_AR,
    "MA": LANGUAGE_AR,
    "OM": LANGUAGE_AR,
    "PS": LANGUAGE_AR,
    "QA": LANGUAGE_AR,
    "SA": LANGUAGE_AR,
    "SD": LANGUAGE_AR,
    "SY": LANGUAGE_AR,
    "TN": LANGUAGE_AR,
    "YE": LANGUAGE_AR,
    "BO": LANGUAGE_ES,
    "CL": LANGUAGE_ES,
    "CO": LANGUAGE_ES,
    "CR": LANGUAGE_ES,
    "CU": LANGUAGE_ES,
    "DO": LANGUAGE_ES,
    "EC": LANGUAGE_ES,
    "ES": LANGUAGE_ES,
    "GQ": LANGUAGE_ES,
    "GT": LANGUAGE_ES,
    "HN": LANGUAGE_ES,
    "MX": LANGUAGE_ES,
    "NI": LANGUAGE_ES,
    "PA": LANGUAGE_ES,
    "PE": LANGUAGE_ES,
    "PR": LANGUAGE_ES,
    "PY": LANGUAGE_ES,
    "SV": LANGUAGE_ES,
    "UY": LANGUAGE_ES,
    "VE": LANGUAGE_ES,
    "AO": LANGUAGE_PT,
    "BR": LANGUAGE_PT_BR,
    "CV": LANGUAGE_PT,
    "GW": LANGUAGE_PT,
    "MZ": LANGUAGE_PT,
    "PT": LANGUAGE_PT,
    "ST": LANGUAGE_PT,
    "TL": LANGUAGE_PT,
    "AT": LANGUAGE_DE,
    "CH": LANGUAGE_DE,
    "DE": LANGUAGE_DE,
    "LI": LANGUAGE_DE,
    "BF": LANGUAGE_FR,
    "BJ": LANGUAGE_FR,
    "CD": LANGUAGE_FR,
    "CG": LANGUAGE_FR,
    "CI": LANGUAGE_FR,
    "CM": LANGUAGE_FR,
    "DJ": LANGUAGE_FR,
    "FR": LANGUAGE_FR,
    "GA": LANGUAGE_FR,
    "GN": LANGUAGE_FR,
    "GP": LANGUAGE_FR,
    "LU": LANGUAGE_FR,
    "MC": LANGUAGE_FR,
    "ML": LANGUAGE_FR,
    "MQ": LANGUAGE_FR,
    "NC": LANGUAGE_FR,
    "NE": LANGUAGE_FR,
    "PF": LANGUAGE_FR,
    "RE": LANGUAGE_FR,
    "SN": LANGUAGE_FR,
    "TD": LANGUAGE_FR,
    "TF": LANGUAGE_FR,
    "TG": LANGUAGE_FR,
    "YT": LANGUAGE_FR,
    "CY": LANGUAGE_TR,
    "TR": LANGUAGE_TR,
    "IT": LANGUAGE_IT,
    "SM": LANGUAGE_IT,
    "VA": LANGUAGE_IT,
    "BY": LANGUAGE_RU,
    "KG": LANGUAGE_RU,
    "KZ": LANGUAGE_RU,
    "RU": LANGUAGE_RU,
    "JP": LANGUAGE_JA,
    "KR": LANGUAGE_KO,
    "CN": LANGUAGE_ZH,
    "HK": LANGUAGE_ZH,
    "MO": LANGUAGE_ZH,
    "SG": LANGUAGE_ZH,
    "TW": LANGUAGE_ZH,
}


def _normalize_country_code(value: Any) -> str:
    code = str(value or "").strip().upper()
    return code if len(code) == 2 and code.isalpha() else ""


def _extract_country_code(payload: Any) -> str:
    if isinstance(payload, dict):
        for key in ("country", "country_code", "countryCode", "cf_country", "code"):
            value = payload.get(key)
            country_code = (
                _extract_country_code(value)
                if isinstance(value, dict)
                else _normalize_country_code(value)
            )
            if country_code:
                return country_code
        return ""

    if isinstance(payload, str):
        return _normalize_country_code(payload)

    return ""


def language_for_country_code(country_code: Any) -> str:
    return _COUNTRY_LANGUAGE_MAP.get(_normalize_country_code(country_code), LANGUAGE_EN)


def detect_language_from_country() -> tuple[str, str]:
    try:
        response = acquire_geometry_worker(authorize=False).country_code_request(
            dev_requested=is_dev_mode(),
            timeout_seconds=COUNTRY_CODE_TIMEOUT_SECONDS,
        )
        if not response.ok:
            raise RuntimeError(f"country-code service returned {response.status_code}")
    except Exception:
        logger.debug("Could not fetch country code for language default", exc_info=True)
        return LANGUAGE_EN, ""

    try:
        payload: Any = response.json()
    except ValueError:
        payload = response.text

    country_code = _extract_country_code(payload)
    return language_for_country_code(country_code), country_code


def should_detect_default_language(
    prefs: Any | None,
    *,
    redetect_auto_language: bool = False,
) -> bool:
    if prefs is None:
        return False

    if bool(getattr(prefs, "language_user_selected", False)):
        return False

    if redetect_auto_language:
        return True

    attempted_version = str(getattr(prefs, "language_auto_detected_version", "")).strip()
    return attempted_version != VERSION
