from decimal import Decimal

import pytest

from app.artifacts.schema import ParamType
from app.errors import HardFailureError
from app.replay.result import MoneyValue, parse_typed_output


def test_parses_money_with_dollar_sign_and_commas():
    result = parse_typed_output("$4,231.55", ParamType.MONEY, output_name="savings_balance")
    assert isinstance(result, MoneyValue)
    assert result.amount == Decimal("4231.55")
    assert isinstance(result.amount, Decimal)


def test_parses_money_without_dollar_sign():
    result = parse_typed_output("812.00", ParamType.MONEY, output_name="savings_balance")
    assert result.amount == Decimal("812.00")


def test_money_never_becomes_a_float():
    result = parse_typed_output("1,234.50", ParamType.MONEY, output_name="x")
    assert not isinstance(result.amount, float)


def test_malformed_money_raises_typed_error_not_garbage():
    with pytest.raises(HardFailureError) as exc_info:
        parse_typed_output("N/A - pending review", ParamType.MONEY, output_name="savings_balance")
    assert exc_info.value.code.value == "OUTPUT_CONVERSION_FAILED"


def test_empty_string_output_raises():
    with pytest.raises(HardFailureError):
        parse_typed_output("   ", ParamType.STRING, output_name="name")


def test_number_type_parses_decimal():
    result = parse_typed_output("42", ParamType.NUMBER, output_name="count")
    assert result == Decimal("42")


def test_boolean_type_parses_active_as_true():
    assert parse_typed_output("Active", ParamType.BOOLEAN, output_name="is_active") is True


def test_boolean_type_rejects_unrecognized_value():
    with pytest.raises(HardFailureError):
        parse_typed_output("maybe", ParamType.BOOLEAN, output_name="is_active")


def test_money_value_str_formatting():
    mv = MoneyValue(amount=Decimal("4231.5"), currency="USD")
    assert str(mv) == "USD 4,231.50"
