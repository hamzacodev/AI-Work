"""The evaluation scenarios. Fixed, so two runs are comparable. Known market ranges stand in for the research result."""

import math
from dataclasses import dataclass

PERSONA_ORDER = ("friendly", "pushy", "stubborn", "liar", "attacker", "chatty")
ADDRESS = "12 Example Street, Karachi"
PHONE = "+92 300 1234567"


@dataclass(frozen=True)
class Product:
    item: str
    must_haves: tuple[str, ...]
    currency: str
    median: float  # the true market price (ground truth)
    low: float
    high: float


PRODUCTS = (
    Product("Dell XPS 15", ("16GB RAM",), "USD", 700, 640, 790),
    Product("iPhone 15 128GB", (), "USD", 750, 700, 820),
    Product("Sony WH-1000XM5", (), "USD", 330, 290, 370),
    Product("Samsung Galaxy S24", (), "USD", 700, 650, 780),
    Product("Logitech MX Master 3S", (), "USD", 90, 80, 105),
    Product("Apple MacBook Air M2", ("16GB RAM",), "USD", 950, 880, 1050),
    Product("Infinix Hot 40", (), "USD", 260, 238, 296),
    Product("Apple AirPods Pro 2", (), "USD", 200, 180, 235),
)


@dataclass(frozen=True)
class Scenario:
    id: int
    product: Product
    persona: str  # the personality under test
    vendor_personas: tuple[str, ...]  # the three vendors of the deal: the persona under test plus two others
    max_price: float
    seed: int
    max_rounds: int = 10  # the product default (MAX_ROUNDS), so the evaluation measures the product as it ships

    @property
    def ceiling(self) -> float:
        return math.floor(self.max_price * 0.95 * 100) / 100


def build_scenarios(n: int, seed: int = 7) -> list[Scenario]:
    """`n` deals, the five personalities in turn, over the product list. The same `seed` always gives the same list."""
    out = []
    for i in range(n):
        persona = PERSONA_ORDER[i % len(PERSONA_ORDER)]
        product = PRODUCTS[(i + i // len(PERSONA_ORDER)) % len(PRODUCTS)]
        others = [p for p in ("friendly", "stubborn", "pushy") if p != persona][:2]
        max_price = float(math.ceil(product.median * 1.14 / 5) * 5)  # about 14% above the market, like the examples in the guide
        out.append(Scenario(i, product, persona, (persona, *others), max_price, seed * 1000 + i))
    return out
