"""Spanish tax ids: is this NIF, NIE or CIF well formed?

A shop that asks to join gives its tax id. The check digit tells a typo or
an invented number from a real one; it does **not** tell whose it is: no
public service says who a CIF belongs to. That part is a person's call.

Three shapes, all nine characters once spaces, dots and dashes are removed:

- NIF (a person, e.g. a sole trader): 8 digits and a letter.
- NIE (a foreign resident): X, Y or Z, 7 digits and a letter.
- CIF (a company or organisation): a letter, 7 digits and a digit or letter.
"""

from __future__ import annotations

import re

_NIF_LETTERS = "TRWAGMYFPDXBNJZSQVHLCKE"
_CIF_CONTROL_LETTERS = "JABCDEFGHI"
_NIF = re.compile(r"^(\d{8})([A-Z])$")
_NIE = re.compile(r"^([XYZ])(\d{7})([A-Z])$")
# The special K, L, M (old NIFs of minors, residents abroad and foreigners
# without NIE) follow the NIF rule on their 7 digits.
_NIF_KLM = re.compile(r"^([KLM])(\d{7})([A-Z])$")
_CIF = re.compile(r"^([ABCDEFGHJNPQRSUVW])(\d{7})([0-9A-J])$")
# Organisations whose control is always a letter, and those always a digit.
_CIF_LETTER_ONLY = set("PQRSNW")
_CIF_DIGIT_ONLY = set("ABEH")


def normalize_tax_id(value: str | None) -> str:
    """As people type it -> nine characters, upper case: ``b-12.345.674``
    becomes ``B12345674``."""
    return re.sub(r"[\s.\-_/]", "", (value or "")).upper()


def _nif_letter(number: int) -> str:
    return _NIF_LETTERS[number % 23]


def _cif_control(digits: str) -> int:
    even = sum(int(d) for d in digits[1::2])
    odd = sum(sum(divmod(int(d) * 2, 10)) for d in digits[0::2])
    return (10 - (even + odd) % 10) % 10


def is_valid_tax_id(value: str | None) -> bool:
    """A well-formed NIF, NIE or CIF with the right check digit."""
    tax_id = normalize_tax_id(value)

    if match := _NIF.match(tax_id):
        return _nif_letter(int(match.group(1))) == match.group(2)

    if match := _NIE.match(tax_id):
        number = int("XYZ".index(match.group(1)) * 10_000_000 + int(match.group(2)))
        return _nif_letter(number) == match.group(3)

    if match := _NIF_KLM.match(tax_id):
        return _nif_letter(int(match.group(2))) == match.group(3)

    if match := _CIF.match(tax_id):
        kind, digits, control = match.groups()
        expected = _cif_control(digits)
        as_digit = control == str(expected)
        as_letter = control == _CIF_CONTROL_LETTERS[expected]
        if kind in _CIF_LETTER_ONLY:
            return as_letter
        if kind in _CIF_DIGIT_ONLY:
            return as_digit
        return as_digit or as_letter

    return False
