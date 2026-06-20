"""
Unit tests for the MINDX-Mart cleaning rules + DQ engine (src/mindx_transforms.py).

Run:  python -m pytest tests/ -v
These run with no Spark cluster, so they are fast CI-friendly guards that the
business rules behave as specified in docs/data_anomalies.md.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import mindx_transforms as mt  # noqa: E402


# --------------------------------------------------------------------------- #
# Field cleaning
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "raw,expected_iso",
    [
        ("2025-12-07T13:55:41.715113", "2025-12-07T13:55:41.715113"),
        ("2024-01-10T10:18:40", "2024-01-10T10:18:40"),
        ("07/11/2024 08:50", "2024-11-07T08:50:00"),
        ("30/09/2025 16:38", "2025-09-30T16:38:00"),
    ],
)
def test_parse_order_date_formats(raw, expected_iso):
    assert mt.parse_order_date(raw).isoformat() == expected_iso


def test_parse_order_date_bad():
    assert mt.parse_order_date("not-a-date") is None
    assert mt.parse_order_date("") is None
    assert mt.parse_order_date(None) is None


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("$1505.69", 1505.69),
        ("$1,905.20", 1905.20),
        ("2456.83", 2456.83),
        ("  $74.37 ", 74.37),
        ("", None),
        (None, None),
        ("abc", None),
    ],
)
def test_clean_amount(raw, expected):
    assert mt.clean_amount(raw) == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("credit_card", "Credit Card"),
        ("Credit Card", "Credit Card"),
        ("CREDITCARD", "Credit Card"),
        ("PayPal", "PayPal"),
        ("paypal", "PayPal"),
        ("COD", "COD"),
        ("cod", "COD"),
    ],
)
def test_normalize_payment_method(raw, expected):
    assert mt.normalize_payment_method(raw) == expected


def test_normalize_device_type_blank_to_unknown():
    assert mt.normalize_device_type("") == "Unknown"
    assert mt.normalize_device_type(None) == "Unknown"
    assert mt.normalize_device_type("Mobile") == "Mobile"


@pytest.mark.parametrize(
    "raw,expected",
    [(1, True), (5, True), (3.0, True), (0, False), (6, False), (99.0, False), (None, False), ("", False)],
)
def test_is_valid_feedback(raw, expected):
    assert mt.is_valid_feedback(raw) is expected


def test_parse_items_and_objects():
    items = mt.parse_items('[{"product_id": "PRD-1", "category": "Books", "price": 10.0, "quantity": 2}]')
    assert len(items) == 1 and items[0]["category"] == "Books"
    assert mt.parse_items("[]") is None
    assert mt.parse_items("garbage") is None
    cust = mt.parse_json_object('{"name": "A", "email": "a@x.com", "phone": "123"}')
    assert cust["email"] == "a@x.com"


# --------------------------------------------------------------------------- #
# DQ engine
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def cfg():
    return mt.load_config()


def _sales_raw(**overrides):
    base = {
        "order_id": "TXN-1",
        "order_date": "2025-01-15T10:00:00",
        "customer_info": '{"name": "A", "email": "a@x.com", "phone": "1"}',
        "customer_age": "30",
        "location": "Townsville",
        "device_type": "Mobile",
        "items": '[{"product_id": "PRD-1", "category": "Books", "price": 10.0, "quantity": 2}]',
        "payment_method": "credit_card",
        "currency": "USD",
        "discount_code": "",
        "shipping_cost": "5.0",
        "total_amount": "25.0",
        "order_status": "Completed",
        "loyalty_points": "2",
        "feedback_score": "4",
    }
    base.update(overrides)
    return base


def test_clean_record_passes_all_reject_rules(cfg):
    stage = mt.build_sales_stage(_sales_raw(), is_duplicate=False)
    res = mt.apply_dq(stage, cfg["data_quality"]["sales"])
    assert res["is_clean"] is True
    assert res["quarantine_reason"] is None


def test_negative_shipping_quarantined(cfg):
    stage = mt.build_sales_stage(_sales_raw(shipping_cost="-10.0"), is_duplicate=False)
    res = mt.apply_dq(stage, cfg["data_quality"]["sales"])
    assert res["is_clean"] is False
    assert res["quarantine_reason"] == "negative_or_invalid_shipping"


def test_duplicate_quarantined(cfg):
    stage = mt.build_sales_stage(_sales_raw(), is_duplicate=True)
    res = mt.apply_dq(stage, cfg["data_quality"]["sales"])
    assert "duplicate_order_id" in res["failed_reject"]


def test_dollar_amount_is_cleaned_and_passes(cfg):
    stage = mt.build_sales_stage(_sales_raw(total_amount="$1505.69"), is_duplicate=False)
    assert stage["total_amount_num"] == 1505.69
    assert mt.apply_dq(stage, cfg["data_quality"]["sales"])["is_clean"] is True


def test_bad_date_quarantined(cfg):
    stage = mt.build_sales_stage(_sales_raw(order_date="???"), is_duplicate=False)
    assert mt.apply_dq(stage, cfg["data_quality"]["sales"])["quarantine_reason"] == "unparseable_order_date"


def test_fake_feedback_is_warn_not_reject(cfg):
    """feedback_score=99 is a WARN (kept in Silver), not a REJECT (quarantine)."""
    stage = mt.build_sales_stage(_sales_raw(feedback_score="99.0"), is_duplicate=False)
    res = mt.apply_dq(stage, cfg["data_quality"]["sales"])
    assert res["is_clean"] is True
    assert "feedback_out_of_scale" in res["failed_warn"]


def test_empty_items_quarantined(cfg):
    stage = mt.build_sales_stage(_sales_raw(items="[]"), is_duplicate=False)
    assert mt.apply_dq(stage, cfg["data_quality"]["sales"])["quarantine_reason"] == "invalid_items_json"


def test_temporal_in_window_passes(cfg):
    """Đơn năm 2024-2025 và không phải tương lai -> không vi phạm luật ngày giờ."""
    stage = mt.build_sales_stage(_sales_raw(order_date="2025-06-15T10:00:00"), is_duplicate=False)
    res = mt.apply_dq(stage, cfg["data_quality"]["sales"])
    assert "order_date_outside_rate_coverage" not in (res["failed_warn"] + res["failed_reject"])
    assert "order_date_in_future" not in res["failed_reject"]


def test_temporal_outside_coverage_warns(cfg):
    """Đơn ngoài 2024-2025 (vd 2023) -> WARN outside_rate_coverage (không có tỷ giá để quy đổi)."""
    stage = mt.build_sales_stage(_sales_raw(order_date="2023-05-10T10:00:00"), is_duplicate=False)
    res = mt.apply_dq(stage, cfg["data_quality"]["sales"])
    assert "order_date_outside_rate_coverage" in res["failed_warn"]


def test_temporal_future_date_rejected(cfg):
    """Đơn có ngày trong tương lai (2099) -> REJECT order_date_in_future."""
    stage = mt.build_sales_stage(_sales_raw(order_date="2099-01-01T10:00:00"), is_duplicate=False)
    res = mt.apply_dq(stage, cfg["data_quality"]["sales"])
    assert "order_date_in_future" in res["failed_reject"]
    assert res["is_clean"] is False


def test_fx_rules(cfg):
    good = mt.build_fx_stage({"year": "2024", "month": "5", "exchange_rate": "24000", "from_currency": "USD", "to_currency": "VND"})
    assert mt.apply_dq(good, cfg["data_quality"]["exchange_rate"])["is_clean"] is True
    bad = mt.build_fx_stage({"year": "2024", "month": "13", "exchange_rate": "-1", "from_currency": "EUR", "to_currency": "VND"})
    res = mt.apply_dq(bad, cfg["data_quality"]["exchange_rate"])
    assert res["is_clean"] is False
    assert "invalid_month" in res["failed_reject"]


def test_every_config_rule_has_python_predicate(cfg):
    """Guards that the config and the Python evaluator never drift apart."""
    dummy = mt.build_sales_stage(_sales_raw(), is_duplicate=False)
    dummy.update(mt.build_fx_stage({"year": "2024", "month": "1", "exchange_rate": "1", "from_currency": "USD", "to_currency": "VND"}))
    for group in cfg["data_quality"].values():
        for rule in group:
            mt.evaluate_rule(rule["rule_id"], dummy)  # raises KeyError if missing
