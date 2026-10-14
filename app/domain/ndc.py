"""National Drug Code (NDC) format rules.

An NDC has three parts: labeler (the company), product, and package. FDA
allows three 10 digit layouts, written with dashes:

    4-4-2   e.g. 0002-0095-00
    5-3-2   e.g. 64980-443-01
    5-4-1   e.g. 50090-7387-0

The product NDC is just the first two parts (4-4, 5-3, or 5-4).
"""

from __future__ import annotations

import re

PRODUCT_NDC = re.compile(r"^(\d{4}-\d{4}|\d{5}-\d{3}|\d{5}-\d{4})$")
PACKAGE_NDC = re.compile(r"^(\d{4}-\d{4}-\d{2}|\d{5}-\d{3}-\d{2}|\d{5}-\d{4}-\d)$")


def is_valid_product_ndc(value: str | None) -> bool:
    return bool(value) and PRODUCT_NDC.match(value or "") is not None


def is_valid_package_ndc(value: str | None) -> bool:
    return bool(value) and PACKAGE_NDC.match(value or "") is not None


def package_belongs_to_product(package_ndc: str, product_ndc: str) -> bool:
    """A package NDC should start with its product NDC followed by a dash."""
    return package_ndc.startswith(product_ndc + "-")
