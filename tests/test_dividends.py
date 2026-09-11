import argparse
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from core.workers.dividends import (
    _are_values_equal,
    _detect_row_diffs,
    dividends_flow,
    execute_dividends_sync,
    extract_js_variables,
    fetch_dividends_html,
    fetch_existing_dividends,
    format_telegram_message,
    notify_telegram_task,
    parse_currency_code,
    parse_date_string,
    parse_dividends_table,
    parse_numeric_value,
    parse_yield_fraction,
    reconcile_dividends,
    run_standalone,
    sync_dividends,
)


# ==============================================================================
# 1. Helper parsing functions tests
# ==============================================================================


@pytest.mark.parametrize(
    "raw_input, expected",
    [
        ("2026-10-15", date(2026, 10, 15)),
        ("2025-01-01", date(2025, 1, 1)),
        ("", None),
        ("-", None),
        ("brak", None),
        (None, None),
        ("invalid-date-format", None),
    ],
)
def test_parse_date_string(raw_input, expected):
    assert parse_date_string(raw_input) == expected


@pytest.mark.parametrize(
    "raw_input, expected",
    [
        ("0,17", 0.17),
        ("900,00", 900.0),
        ("2,13", 2.13),
        (" 10\xa0000,50 ", 10000.5),
        ("", None),
        ("-", None),
        (".", None),
        (None, None),
        ("abc", None),
    ],
)
def test_parse_numeric_value(raw_input, expected):
    result = parse_numeric_value(raw_input)
    if expected is None:
        assert result is None
    else:
        assert result == pytest.approx(expected)


@pytest.mark.parametrize(
    "raw_input, expected",
    [
        ("4,11%", 0.0411),
        ("1,12%", 0.0112),
        ("0,00%", 0.0),
        ("", None),
        ("-", None),
        (None, None),
    ],
)
def test_parse_yield_fraction(raw_input, expected):
    result = parse_yield_fraction(raw_input)
    if expected is None:
        assert result is None
    else:
        assert result == pytest.approx(expected)


@pytest.mark.parametrize(
    "note, expected",
    [
        ("0,12 euro/akcja", "EUR"),
        ("EUR tranche", "EUR"),
        ("317,58 HUF/akcja", "HUF"),
        ("1.5 USD per share", "USD"),
        ("I rata", "PLN"),
        ("zaliczka na poczet dywidendy", "PLN"),
        ("", "PLN"),
    ],
)
def test_parse_currency_code(note, expected):
    assert parse_currency_code(note) == expected


def test_extract_js_variables():
    html = """
    <script>
        var bbdvt101 = "uchwalona";
        var bbdvm101 = "I rata";
        var bbdvt102 = "proponowana";
        var bbdvm102 = "zaliczka na poczet dywidendy";
    </script>
    """
    vars_dict = extract_js_variables(html)
    assert vars_dict["bbdvt101"] == "uchwalona"
    assert vars_dict["bbdvm101"] == "I rata"
    assert vars_dict["bbdvt102"] == "proponowana"
    assert vars_dict["bbdvm102"] == "zaliczka na poczet dywidendy"


# ==============================================================================
# 2. HTML Table Parsing tests
# ==============================================================================


SAMPLE_HTML = """
<html>
<head>
<script>
    var bbdvt100 = "uchwalona";
    var bbdvm100 = "I rata";
</script>
</head>
<body>
<table class="cctabdt">
    <tr>
        <th>Spółka</th>
        <th>Za okres</th>
        <th>Stan wypłaty</th>
        <th>Dyw. na akcje</th>
        <th>Stopa</th>
        <th>Ustalenie prawa</th>
        <th>Notowanie bez dyw.</th>
        <th>Data WZA</th>
    </tr>
    <tr>
        <td><strong><a href="/gpw/grodno,notowania,dywidendy.aspx">GRODNO</a></strong></td>
        <td class="c range">od&nbsp;2025-01-01<br/>do&nbsp;2025-12-31</td>
        <td class="c">proponowana<div class="stcm">2026-11-19</div></td>
        <td class="c">0,17</td>
        <td class="c">1,12%</td>
        <td class="c">2026-10-15</td>
        <td class="c">2026-10-14</td>
        <td class="c"></td>
    </tr>
    <tr>
        <td><strong><a href="/gpw/lpp,notowania,dywidendy.aspx">LPP</a></strong></td>
        <td class="c range">od&nbsp;2025-01-01<br/>do&nbsp;2025-12-31</td>
        <td class="c">uchwalona
            <span class="bubbly" data-bbm="bbdvm100" data-bbt="bbdvt100"><i class="fas fa-question"></i></span>
            <div class="stcm">2026-10-30</div>
        </td>
        <td class="c">900,00</td>
        <td class="c">4,11%</td>
        <td class="c">2026-10-09</td>
        <td class="c">2026-10-08</td>
        <td class="c">2026-07-10</td>
    </tr>
    <tr>
        <td>Plain Company</td>
        <td>invalid period</td>
        <td>wypłacona</td>
        <td>-</td>
        <td>-</td>
        <td>-</td>
        <td>-</td>
        <td>-</td>
    </tr>
</table>
</body>
</html>
"""


def test_parse_dividends_table():
    records = parse_dividends_table(SAMPLE_HTML, year=2025)
    assert len(records) == 3

    # Row 1: GRODNO
    r0 = records[0]
    assert r0["company_name"] == "GRODNO"
    assert r0["ticker_slug"] == "grodno"
    assert r0["period_from"] == date(2025, 1, 1)
    assert r0["period_to"] == date(2025, 12, 31)
    assert r0["status"] == "proponowana"
    assert r0["payment_date"] == date(2026, 11, 19)
    assert r0["dps"] == 0.17
    assert r0["currency"] == "PLN"
    assert r0["dividend_yield"] == pytest.approx(0.0112)
    assert r0["record_date"] == date(2026, 10, 15)
    assert r0["ex_date"] == date(2026, 10, 14)
    assert r0["agm_date"] is None
    assert r0["note"] == ""

    # Row 2: LPP with note
    r1 = records[1]
    assert r1["company_name"] == "LPP"
    assert r1["ticker_slug"] == "lpp"
    assert r1["status"] == "uchwalona"
    assert r1["payment_date"] == date(2026, 10, 30)
    assert r1["dps"] == 900.0
    assert r1["dividend_yield"] == pytest.approx(0.0411)
    assert r1["note"] == "I rata"

    # Row 3: Plain company with missing fields
    r2 = records[2]
    assert r2["company_name"] == "Plain Company"
    assert r2["period_from"] is None
    assert r2["dps"] is None
    assert r2["dividend_yield"] is None


def test_parse_dividends_table_empty():
    assert parse_dividends_table("<html><body>No table here</body></html>", 2025) == []


# ==============================================================================
# 3. Value Equality & Diff Detection tests
# ==============================================================================


@pytest.mark.parametrize(
    "val1, val2, expected",
    [
        (None, None, True),
        ("", None, True),
        (None, "", True),
        (10.5, Decimal("10.5000"), True),
        ("TEXT", "TEXT", True),
        ("TEXT ", "TEXT", True),
        (date(2026, 1, 1), date(2026, 1, 1), True),
        (date(2026, 1, 1), date(2026, 1, 2), False),
        (10.5, 10.6, False),
        ("A", "B", False),
    ],
)
def test_are_values_equal(val1, val2, expected):
    assert _are_values_equal(val1, val2) is expected


def test_detect_row_diffs():
    existing = {
        "status": "proponowana",
        "payment_date": date(2026, 10, 15),
        "dps": Decimal("0.17"),
        "note": "",
    }
    scraped = {
        "status": "uchwalona",
        "payment_date": date(2026, 11, 19),
        "dps": 0.17,
        "note": "",
    }
    diffs = _detect_row_diffs(existing, scraped)
    assert "status" in diffs
    assert diffs["status"] == ("proponowana", "uchwalona")
    assert "payment_date" in diffs
    assert diffs["payment_date"] == (date(2026, 10, 15), date(2026, 11, 19))
    assert "dps" not in diffs


# ==============================================================================
# 4. Reconciliation Engine tests
# ==============================================================================


def test_reconcile_single_company_update():
    existing = [
        {
            "id": 1,
            "company_name": "GRODNO",
            "dividend_year": 2025,
            "status": "proponowana",
            "payment_date": date(2026, 10, 15),
            "dps": Decimal("0.17"),
            "note": "",
        }
    ]
    scraped = [
        {
            "company_name": "GRODNO",
            "dividend_year": 2025,
            "status": "uchwalona",
            "payment_date": date(2026, 11, 19),
            "dps": 0.17,
            "note": "",
        }
    ]
    rec = reconcile_dividends(existing, scraped)
    assert len(rec["to_insert"]) == 0
    assert len(rec["to_delete"]) == 0
    assert len(rec["to_update"]) == 1
    assert rec["unchanged_count"] == 0
    assert rec["to_update"][0]["id"] == 1
    assert "status" in rec["to_update"][0]["diffs"]


def test_reconcile_single_company_unchanged():
    existing = [
        {
            "id": 1,
            "company_name": "GRODNO",
            "dividend_year": 2025,
            "status": "uchwalona",
            "payment_date": date(2026, 11, 19),
            "dps": Decimal("0.17"),
            "note": "",
        }
    ]
    scraped = [
        {
            "company_name": "GRODNO",
            "dividend_year": 2025,
            "status": "uchwalona",
            "payment_date": date(2026, 11, 19),
            "dps": 0.17,
            "note": "",
        }
    ]
    rec = reconcile_dividends(existing, scraped)
    assert len(rec["to_insert"]) == 0
    assert len(rec["to_update"]) == 0
    assert len(rec["to_delete"]) == 0
    assert rec["unchanged_count"] == 1


def test_reconcile_insert_and_delete():
    existing = [{"id": 10, "company_name": "OLD_CO", "payment_date": date(2025, 5, 1)}]
    scraped = [{"company_name": "NEW_CO", "payment_date": date(2025, 6, 1), "note": ""}]
    rec = reconcile_dividends(existing, scraped)
    assert len(rec["to_insert"]) == 1
    assert rec["to_insert"][0]["company_name"] == "NEW_CO"
    assert len(rec["to_delete"]) == 1
    assert rec["to_delete"][0]["company_name"] == "OLD_CO"


def test_reconcile_multi_tranche_matching():
    existing = [
        {
            "id": 1,
            "company_name": "BETACOM",
            "note": "I rata",
            "payment_date": date(2025, 10, 17),
            "status": "uchwalona",
        },
        {
            "id": 2,
            "company_name": "BETACOM",
            "note": "II rata",
            "payment_date": date(2025, 12, 16),
            "status": "uchwalona",
        },
    ]
    scraped = [
        {
            "company_name": "BETACOM",
            "note": "I rata",
            "payment_date": date(2025, 10, 17),
            "status": "wypłacona",
        },
        {
            "company_name": "BETACOM",
            "note": "II rata",
            "payment_date": date(2025, 12, 16),
            "status": "uchwalona",
        },
    ]
    rec = reconcile_dividends(existing, scraped)
    assert len(rec["to_insert"]) == 0
    assert len(rec["to_delete"]) == 0
    assert len(rec["to_update"]) == 1
    assert rec["to_update"][0]["id"] == 1
    assert rec["unchanged_count"] == 1


# ==============================================================================
# 5. Telegram Message Formatting tests
# ==============================================================================


def test_format_telegram_message_no_changes():
    res = {
        "status": "success",
        "inserted_count": 0,
        "updated_count": 0,
        "deleted_count": 0,
        "unchanged_count": 10,
    }
    msg = format_telegram_message(2026, res)
    assert "Database is already up to date" in msg
    assert "10 entries match" in msg


def test_format_telegram_message_with_changes():
    res = {
        "status": "success",
        "inserted_count": 1,
        "updated_count": 1,
        "deleted_count": 1,
        "unchanged_count": 5,
        "inserted_items": [
            {
                "company_name": "NEW_CO",
                "dps": 1.5,
                "currency": "PLN",
                "status": "proponowana",
                "payment_date": date(2026, 9, 1),
                "note": "I rata",
            }
        ],
        "updated_items": [
            {
                "company_name": "GRODNO",
                "diffs": {
                    "payment_date": (date(2026, 10, 15), date(2026, 11, 19)),
                    "status": ("proponowana", "uchwalona"),
                },
            }
        ],
        "deleted_items": [{"company_name": "OLD_CO", "payment_date": date(2026, 4, 1)}],
    }
    msg = format_telegram_message(2026, res)
    assert "<b>[StockWatch Dividends - 2026]</b>" in msg
    assert "NEW_CO" in msg
    assert "GRODNO" in msg
    assert "OLD_CO" in msg
    assert "payment_date: <code>2026-10-15</code> ➔ <code>2026-11-19</code>" in msg


def test_format_telegram_message_failed():
    res = {"status": "failed", "error": "Connection timeout"}
    msg = format_telegram_message(2026, res)
    assert "🚨" in msg
    assert "Connection timeout" in msg


# ==============================================================================
# 6. Database Execution and Prefect Flow tests
# ==============================================================================


def test_fetch_dividends_html():
    with patch("requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.text = "<html>test</html>"
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        html = fetch_dividends_html(2026)
        assert html == "<html>test</html>"
        mock_get.assert_called_once()


def test_notify_telegram_task():
    with patch(
        "core.workers.dividends.send_telegram_notification", return_value=True
    ) as mock_send:
        result = notify_telegram_task("Test notification")
        assert result is True
        mock_send.assert_called_once_with("Test notification")


def test_sync_dividends_success():
    with (
        patch("core.workers.dividends.fetch_dividends_html", return_value=SAMPLE_HTML),
        patch("core.workers.dividends.fetch_existing_dividends", return_value=[]),
        patch("core.workers.dividends.execute_dividends_sync") as mock_exec,
        patch("core.workers.dividends.send_telegram_notification", return_value=True),
    ):
        mock_exec.side_effect = lambda **kwargs: {
            "status": "success",
            "inserted_count": 3,
            "updated_count": 0,
            "deleted_count": 0,
            "unchanged_count": 0,
            "inserted_items": [],
            "updated_items": [],
            "deleted_items": [],
        }

        mock_engine = MagicMock()
        res = sync_dividends(year=2025, db_engine=mock_engine, send_notification=True)
        assert res["status"] == "success"
        assert res["inserted_count"] == 3
        assert res["telegram_sent"] is True

        # Test with send_notification=False and year=None
        res_no_notify = sync_dividends(
            year=None, db_engine=mock_engine, send_notification=False
        )
        assert res_no_notify["status"] == "success"
        assert "telegram_sent" not in res_no_notify


def test_sync_dividends_default_db_engine():
    mock_engine = MagicMock()
    from core.data_hub.connection_manager import connection_manager

    old_engine = connection_manager._pg_engine
    try:
        connection_manager._pg_engine = mock_engine
        with (
            patch(
                "core.workers.dividends.fetch_dividends_html", return_value=SAMPLE_HTML
            ),
            patch("core.workers.dividends.fetch_existing_dividends", return_value=[]),
            patch("core.workers.dividends.execute_dividends_sync") as mock_exec,
        ):
            mock_exec.return_value = {
                "status": "success",
                "inserted_count": 3,
                "updated_count": 0,
                "deleted_count": 0,
                "unchanged_count": 0,
                "inserted_items": [],
                "updated_items": [],
                "deleted_items": [],
            }
            res = sync_dividends(year=2025, db_engine=None, send_notification=False)
            assert res["status"] == "success"

            with patch(
                "core.workers.dividends.sync_dividends",
                return_value={"status": "success"},
            ) as mock_sync:
                flow_res = dividends_flow(year=2025)
                assert flow_res["status"] == "success"
                mock_sync.assert_called_once_with(
                    year=2025, db_engine=mock_engine, send_notification=True
                )
    finally:
        connection_manager._pg_engine = old_engine


def test_format_telegram_message_truncation():
    # Test > 15 items for inserts, updates, and deletes
    res = {
        "status": "success",
        "inserted_count": 20,
        "updated_count": 20,
        "deleted_count": 20,
        "unchanged_count": 0,
        "inserted_items": [
            {
                "company_name": f"CO_{i}",
                "dps": None,
                "currency": "PLN",
                "status": "proponowana",
                "payment_date": None,
                "note": "",
            }
            for i in range(20)
        ],
        "updated_items": [
            {"company_name": f"CO_{i}", "diffs": {"status": ("old", "new")}}
            for i in range(20)
        ],
        "deleted_items": [
            {"company_name": f"CO_{i}", "payment_date": None} for i in range(20)
        ],
    }
    msg = format_telegram_message(2026, res)
    assert "...and 5 more" in msg


def test_sync_dividends_error_handling_no_notification():
    with (
        patch(
            "core.workers.dividends.fetch_dividends_html",
            side_effect=ValueError("Invalid page"),
        ),
        patch("core.workers.dividends.send_telegram_notification") as mock_telegram,
    ):
        with pytest.raises(ValueError, match="Invalid page"):
            sync_dividends(year=2026, send_notification=False)
        mock_telegram.assert_not_called()


def test_sync_dividends_error_handling():
    with (
        patch(
            "core.workers.dividends.fetch_dividends_html",
            side_effect=RuntimeError("Network failure"),
        ),
        patch("core.workers.dividends.send_telegram_notification") as mock_telegram,
    ):
        with pytest.raises(RuntimeError, match="Network failure"):
            sync_dividends(year=2026, send_notification=True)
        mock_telegram.assert_called_once()
        assert "Network failure" in mock_telegram.call_args[0][0]


def test_run_standalone():
    with (
        patch("argparse.ArgumentParser.parse_args") as mock_args,
        patch("core.workers.dividends.sync_dividends") as mock_sync,
    ):
        mock_args.return_value = argparse.Namespace(year=2026, no_telegram=False)
        mock_sync.return_value = {
            "inserted_count": 1,
            "updated_count": 2,
            "deleted_count": 0,
            "unchanged_count": 4,
        }
        run_standalone()
        mock_sync.assert_called_once_with(year=2026, send_notification=True)


# ==============================================================================
# 7. Database Integration tests
# ==============================================================================


@pytest.mark.db_test
def test_database_operations_integration():
    from core.data_hub.connection_manager import connection_manager
    from sqlalchemy import text

    engine = connection_manager.postgres_engine

    # Clean up test year
    test_year = 1999
    with engine.begin() as conn:
        conn.execute(
            text("DELETE FROM mdh.dividends WHERE dividend_year = :year;"),
            {"year": test_year},
        )

    # 1. Test insert via execute_dividends_sync
    reconciliation = {
        "to_insert": [
            {
                "dividend_year": test_year,
                "company_name": "TEST_CO_A",
                "ticker_slug": "test_a",
                "period_from": date(test_year, 1, 1),
                "period_to": date(test_year, 12, 31),
                "status": "proponowana",
                "payment_date": date(test_year + 1, 6, 1),
                "record_date": date(test_year + 1, 5, 20),
                "ex_date": date(test_year + 1, 5, 19),
                "agm_date": date(test_year + 1, 4, 15),
                "dps": 1.25,
                "currency": "PLN",
                "dividend_yield": 0.035,
                "note": "I rata",
            }
        ],
        "to_update": [],
        "to_delete": [],
        "unchanged_count": 0,
    }
    res = execute_dividends_sync(engine, test_year, reconciliation)
    assert res["inserted_count"] == 1

    # 2. Fetch existing
    existing = fetch_existing_dividends(engine, test_year)
    assert len(existing) == 1
    assert existing[0]["company_name"] == "TEST_CO_A"
    assert existing[0]["id"] is not None

    # 3. Test update via reconciliation
    scraped_updated = [
        {
            "dividend_year": test_year,
            "company_name": "TEST_CO_A",
            "ticker_slug": "test_a",
            "period_from": date(test_year, 1, 1),
            "period_to": date(test_year, 12, 31),
            "status": "uchwalona",
            "payment_date": date(test_year + 1, 6, 10),
            "record_date": date(test_year + 1, 5, 20),
            "ex_date": date(test_year + 1, 5, 19),
            "agm_date": date(test_year + 1, 4, 15),
            "dps": 1.50,
            "currency": "PLN",
            "dividend_yield": 0.040,
            "note": "I rata",
        }
    ]
    rec_update = reconcile_dividends(existing, scraped_updated)
    assert len(rec_update["to_update"]) == 1
    res_update = execute_dividends_sync(engine, test_year, rec_update)
    assert res_update["updated_count"] == 1

    updated_rows = fetch_existing_dividends(engine, test_year)
    assert updated_rows[0]["status"] == "uchwalona"
    assert updated_rows[0]["payment_date"] == date(test_year + 1, 6, 10)
    assert float(updated_rows[0]["dps"]) == 1.50

    # 4. Test delete via reconciliation
    rec_delete = reconcile_dividends(updated_rows, [])
    assert len(rec_delete["to_delete"]) == 1
    res_delete = execute_dividends_sync(engine, test_year, rec_delete)
    assert res_delete["deleted_count"] == 1

    final_rows = fetch_existing_dividends(engine, test_year)
    assert len(final_rows) == 0
