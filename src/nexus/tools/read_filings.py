"""
SEC Filings Parser for NEXUS.

Extracts distinct structural sections from SEC filings:
  - Item 1 (Business Overview)
  - Item 1A (Risk Disclosures)
  - Item 7 / MD&A (Management's Discussion and Analysis)
  - Financial statements and notes

Supports 10-K, 10-Q, and 8-K filings from SEC EDGAR.
"""

from __future__ import annotations

import re
from typing import Any, Optional


# Section patterns for 10-K filings
SECTION_PATTERNS_10K = {
    "item1_business": (
        r"(?i)item\s+1\.?\s*(?:business|description\s+of\s+business)",
        r"(?i)item\s+1a\.?\s*risk\s+factors",
    ),
    "item1a_risk_factors": (
        r"(?i)item\s+1a\.?\s*risk\s+factors",
        r"(?i)item\s+1b\.?\s*unresolved\s+staff\s+comments",
    ),
    "item7_mda": (
        r"(?i)item\s+7\.?\s*(?:management'?s?\s+discussion|mda)",
        r"(?i)item\s+7a\.?\s*quantitative",
    ),
}

# Section patterns for 10-Q filings
SECTION_PATTERNS_10Q = {
    "item1_financials": (
        r"(?i)item\s+1\.?\s*financial\s+statements",
        r"(?i)item\s+2\.?\s*management",
    ),
    "item2_mda": (
        r"(?i)item\s+2\.?\s*(?:management'?s?\s+discussion|mda)",
        r"(?i)item\s+3\.?\s*quantitative",
    ),
}


def clean_filing_text(html_text: str) -> str:
    """Basic HTML-to-text cleaning for SEC filings."""
    # Remove HTML tags
    text = re.sub(r'<[^>]+>', ' ', html_text)
    # Remove SEC header/footer boilerplate
    text = re.sub(r'<SEC-DOCUMENT>.*?</SEC-DOCUMENT>', '', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<DOCUMENT>.*?</DOCUMENT>', '', text, flags=re.DOTALL | re.IGNORECASE)
    # Decode HTML entities
    text = text.replace('&nbsp;', ' ').replace('&amp;', '&')
    text = text.replace('&lt;', '<').replace('&gt;', '>')
    text = text.replace('&#160;', ' ').replace('&#32;', ' ')
    # Collapse whitespace
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r' {2,}', ' ', text)
    return text.strip()


def extract_section(
    text: str,
    start_pattern: str,
    end_pattern: str,
) -> Optional[str]:
    """
    Extract a section bounded by regex patterns.
    Returns the text between start_pattern and end_pattern (exclusive).
    """
    start_match = re.search(start_pattern, text, re.IGNORECASE)
    if not start_match:
        return None

    start_pos = start_match.start()

    # Search for end pattern after the start
    end_match = re.search(end_pattern, text[start_pos:], re.IGNORECASE)
    if end_match:
        end_pos = start_pos + end_match.start()
    else:
        end_pos = min(start_pos + 50000, len(text))  # Cap at 50K chars

    section_text = text[start_pos:end_pos].strip()
    return section_text


def parse_10k(filing_text: str) -> dict[str, Any]:
    """
    Parse a 10-K filing, extracting key sections.

    Returns dict with keys: item1_business, item1a_risk_factors, item7_mda
    """
    cleaned = clean_filing_text(filing_text)
    result = {
        "filing_type": "10-K",
        "item1_business": None,
        "item1a_risk_factors": None,
        "item7_mda": None,
    }

    for section_name, (start_pat, end_pat) in SECTION_PATTERNS_10K.items():
        extracted = extract_section(cleaned, start_pat, end_pat)
        if extracted:
            result[section_name] = extracted[:20000]  # Cap each section

    return result


def parse_10q(filing_text: str) -> dict[str, Any]:
    """
    Parse a 10-Q filing, extracting key sections.

    Returns dict with keys: item1_financials, item2_mda
    """
    cleaned = clean_filing_text(filing_text)
    result = {
        "filing_type": "10-Q",
        "item1_financials": None,
        "item2_mda": None,
    }

    for section_name, (start_pat, end_pat) in SECTION_PATTERNS_10Q.items():
        extracted = extract_section(cleaned, start_pat, end_pat)
        if extracted:
            result[section_name] = extracted[:20000]

    return result


def parse_8k(filing_text: str) -> dict[str, Any]:
    """
    Parse an 8-K filing.

    Returns the entire cleaned text (8-Ks are shorter and event-driven).
    """
    cleaned = clean_filing_text(filing_text)
    return {
        "filing_type": "8-K",
        "full_text": cleaned[:15000],
        "items_referenced": _extract_8k_items(cleaned),
    }


def _extract_8k_items(text: str) -> list[str]:
    """Extract referenced items from an 8-K filing."""
    items = []
    matches = re.findall(r'(?i)item\s+([0-9]\.[0-9]{2})', text)
    for m in matches:
        items.append(f"Item {m}")
    return list(set(items)) if items else []


def parse_filing(
    filing_text: str,
    filing_type: str = "10-K",
) -> dict[str, Any]:
    """
    Main entry point: parse an SEC filing and extract relevant sections.

    Args:
        filing_text: Raw filing HTML/text content
        filing_type: "10-K", "10-Q", or "8-K"

    Returns:
        Dict with filing_type and extracted sections
    """
    ft = filing_type.upper().strip()

    if ft in ("10-K", "10K"):
        return parse_10k(filing_text)
    elif ft in ("10-Q", "10Q"):
        return parse_10q(filing_text)
    elif ft in ("8-K", "8K"):
        return parse_8k(filing_text)
    else:
        return {
            "filing_type": ft,
            "error": f"Unsupported filing type: {ft}. Supported: 10-K, 10-Q, 8-K",
            "raw_preview": filing_text[:5000],
        }


def extract_risk_factors(filing_text: str) -> Optional[str]:
    """Convenience: extract only risk factors from a filing."""
    parsed = parse_filing(filing_text)
    return parsed.get("item1a_risk_factors") or parsed.get("full_text")


def extract_business_overview(filing_text: str) -> Optional[str]:
    """Convenience: extract only business overview from a filing."""
    parsed = parse_filing(filing_text)
    return parsed.get("item1_business") or parsed.get("full_text")


def extract_mda(filing_text: str) -> Optional[str]:
    """Convenience: extract only MD&A from a filing."""
    parsed = parse_filing(filing_text)
    return parsed.get("item7_mda") or parsed.get("item2_mda")
