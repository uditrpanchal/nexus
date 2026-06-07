"""
Number formatting utilities — mirrors dexter's formatters.ts
"""


def fmt_num(n, decimals: int = 1) -> str:
    """Format large numbers: 1.5B, 2.3T, etc."""
    if n is None:
        return "—"
    try:
        num = float(n)
        if num != num:  # NaN
            return "—"
        abs_val = abs(num)
        sign = "-" if num < 0 else ""
        if abs_val >= 1e12:
            return f"{sign}{abs_val / 1e12:.{decimals}f}T"
        if abs_val >= 1e9:
            return f"{sign}{abs_val / 1e9:.{decimals}f}B"
        if abs_val >= 1e6:
            return f"{sign}{abs_val / 1e6:.{decimals}f}M"
        if abs_val >= 1e3:
            return f"{sign}{abs_val / 1e3:.{decimals}f}K"
        return f"{sign}{abs_val:.0f}"
    except (ValueError, TypeError):
        return "—"


def fmt_pct(n, decimals: int = 1) -> str:
    """Format as percentage: 0.156 -> 15.6%"""
    if n is None:
        return "—"
    try:
        num = float(n)
        if num != num:
            return "—"
        return f"{num * 100:.{decimals}f}%"
    except (ValueError, TypeError):
        return "—"


def fmt_price(n, decimals: int = 2) -> str:
    """Format as currency: $123.45"""
    if n is None:
        return "—"
    try:
        num = float(n)
        if num != num:
            return "—"
        return f"${num:,.{decimals}f}"
    except (ValueError, TypeError):
        return "—"


def fmt_date(d) -> str:
    """Format date string: '2024-12-31' -> 'Q4 24'"""
    if not d:
        return "—"
    s = str(d)
    if len(s) >= 10:
        try:
            month = int(s[5:7])
            year = s[2:4]
            quarter = (month - 1) // 3 + 1
            return f"Q{quarter} {year}"
        except (ValueError, IndexError):
            pass
    return s


def fmt_ratio(n) -> str:
    """Format ratio: show 2 decimal places."""
    if n is None:
        return "—"
    try:
        num = float(n)
        if num != num:
            return "—"
        return f"{num:.2f}"
    except (ValueError, TypeError):
        return "—"


def fmt_shares(n) -> str:
    """Format share counts."""
    return fmt_num(n, decimals=1)


def fmt_multiple(n, prefix: str = "", suffix: str = "x") -> str:
    """Format multiple: P/E 15.2x, EV/EBITDA 8.5x"""
    if n is None:
        return "—"
    try:
        num = float(n)
        if num != num:
            return "—"
        return f"{prefix}{num:.1f}{suffix}"
    except (ValueError, TypeError):
        return "—"
