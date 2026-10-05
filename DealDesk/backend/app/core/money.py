"""Small money helpers shared by the Researcher and the Simulator."""

_SYMBOL = {"USD": "$", "GBP": "£", "EUR": "€"}


def format_price(value: float, currency: str = "USD") -> str:
    shown = f"{value:,.0f}" if value >= 100 else f"{value:,.2f}"
    return f"{_SYMBOL[currency]}{shown}" if currency in _SYMBOL else f"{currency} {shown}"


def round_price(value: float) -> float:
    return float(round(value)) if value >= 100 else round(value, 2)
