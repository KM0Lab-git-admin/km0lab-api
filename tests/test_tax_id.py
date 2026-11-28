"""Check digits of Spanish tax ids (``app/services/tax_id.py``)."""

import pytest

from app.services.tax_id import is_valid_tax_id, normalize_tax_id


@pytest.mark.parametrize(
    "value",
    [
        "12345678Z",  # NIF: the textbook example
        "00000000T",
        "X1234567L",  # NIE
        "Y1234567X",
        "Z1234567R",
        "B12345674",  # CIF of a limited company: control as a digit
        "A58818501",
        "B00000000",
        "Q2826000H",  # public body: control as a letter
        "P0808300H",
        "G12345674",  # association: digit...
        "G1234567D",  # ...or its letter
    ],
)
def test_well_formed_ids_pass(value):
    assert is_valid_tax_id(value)


@pytest.mark.parametrize(
    "value",
    [
        "12345678A",  # wrong letter
        "X1234567A",
        "B12345678",  # wrong control digit
        "B1234567D",  # a limited company never has a letter
        "Q28260008",  # a public body never has a digit
        "1234567Z",  # too short
        "123456789",
        "I1234567A",  # no such kind of CIF
        "",
        None,
        "no tinc nif",
    ],
)
def test_typos_and_inventions_do_not(value):
    assert not is_valid_tax_id(value)


def test_written_the_way_people_write_it():
    assert normalize_tax_id(" b-12.345.674 ") == "B12345674"
    assert is_valid_tax_id("b-12.345.674")
    assert is_valid_tax_id("12 345 678 z")
    assert is_valid_tax_id("x-1234567-l")
