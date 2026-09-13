import argparse
from unittest.mock import MagicMock, patch

import pytest

from backfill_dividends import (
    backfill_dividends,
    format_backfill_telegram_message,
    run_standalone_backfill,
)


def test_format_backfill_telegram_message():
    summary = {
        "total_inserted": 150,
        "total_updated": 5,
        "total_deleted": 0,
        "total_unchanged": 20,
        "by_year": {
            2025: {"inserted_count": 100, "updated_count": 2, "unchanged_count": 10},
            2026: {"inserted_count": 50, "updated_count": 3, "unchanged_count": 10},
        },
    }
    msg = format_backfill_telegram_message(2025, 2026, summary)
    assert "<b>[StockWatch Dividends - Backfill 2025-2026]</b>" in msg
    assert "Newly inserted: <b>+150</b>" in msg
    assert "• <b>2025</b>: +100 inserted, ~2 updated, 10 unchanged" in msg


def test_backfill_dividends_validation():
    with pytest.raises(
        ValueError, match="start_year .* cannot be greater than end_year"
    ):
        backfill_dividends(start_year=2026, end_year=2020)


def test_backfill_dividends_success():
    with (
        patch("scripts.backfill_dividends.sync_dividends") as mock_sync,
        patch(
            "scripts.backfill_dividends.send_telegram_notification", return_value=True
        ) as mock_send,
    ):
        mock_sync.side_effect = [
            {
                "status": "success",
                "inserted_count": 10,
                "updated_count": 1,
                "deleted_count": 0,
                "unchanged_count": 0,
            },
            {
                "status": "success",
                "inserted_count": 5,
                "updated_count": 0,
                "deleted_count": 0,
                "unchanged_count": 5,
            },
        ]

        mock_engine = MagicMock()
        summary = backfill_dividends(
            start_year=2024,
            end_year=2025,
            db_engine=mock_engine,
            delay=0.0,
            send_notification=True,
        )

        assert summary["total_inserted"] == 15
        assert summary["total_updated"] == 1
        assert summary["total_unchanged"] == 5
        assert summary["telegram_sent"] is True
        assert mock_sync.call_count == 2
        mock_send.assert_called_once()


def test_run_standalone_backfill():
    with (
        patch("argparse.ArgumentParser.parse_args") as mock_args,
        patch("scripts.backfill_dividends.backfill_dividends") as mock_backfill,
    ):
        mock_args.return_value = argparse.Namespace(
            years=10,
            start_year=2017,
            end_year=2026,
            delay=0.0,
            no_telegram=False,
        )
        mock_backfill.return_value = {
            "total_inserted": 500,
            "total_updated": 0,
            "total_deleted": 0,
            "total_unchanged": 0,
        }
        run_standalone_backfill()
        mock_backfill.assert_called_once_with(
            start_year=2017,
            end_year=2026,
            delay=0.0,
            send_notification=True,
        )
