"""Tests for CSV/XLSX spreadsheet ingestion used by the import command."""

from __future__ import annotations

from pathlib import Path

import pytest


class TestReadSpreadsheet:
    def test_read_csv_returns_rows(self, tmp_path: Path):
        from jiramator.spreadsheet import read_spreadsheet

        path = tmp_path / "sample.csv"
        path.write_text("Summary,Priority\nRisk A,High\nRisk B,Medium\n")

        rows = read_spreadsheet(path)

        assert rows == [
            {"Summary": "Risk A", "Priority": "High"},
            {"Summary": "Risk B", "Priority": "Medium"},
        ]

    def test_read_csv_trims_header_whitespace(self, tmp_path: Path):
        from jiramator.spreadsheet import read_spreadsheet

        path = tmp_path / "sample.csv"
        path.write_text(" Summary , Priority \nRisk A,High\n")

        rows = read_spreadsheet(path)

        assert rows == [{"Summary": "Risk A", "Priority": "High"}]

    def test_read_xlsx_returns_rows(self, tmp_path: Path):
        import openpyxl

        from jiramator.spreadsheet import read_spreadsheet

        path = tmp_path / "sample.xlsx"
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Risks"
        ws.append(["Summary", "Priority"])
        ws.append(["Risk A", "High"])
        ws.append(["Risk B", "Medium"])
        wb.save(path)

        rows = read_spreadsheet(path)

        assert rows == [
            {"Summary": "Risk A", "Priority": "High"},
            {"Summary": "Risk B", "Priority": "Medium"},
        ]

    def test_read_xlsx_can_select_sheet(self, tmp_path: Path):
        import openpyxl

        from jiramator.spreadsheet import read_spreadsheet

        path = tmp_path / "sample.xlsx"
        wb = openpyxl.Workbook()
        ws1 = wb.active
        ws1.title = "IgnoreMe"
        ws1.append(["Summary", "Priority"])
        ws1.append(["Wrong", "Low"])
        ws2 = wb.create_sheet("Risks")
        ws2.append(["Summary", "Priority"])
        ws2.append(["Risk A", "High"])
        wb.save(path)

        rows = read_spreadsheet(path, sheet_name="Risks")

        assert rows == [{"Summary": "Risk A", "Priority": "High"}]

    def test_none_cells_become_empty_strings(self, tmp_path: Path):
        import openpyxl

        from jiramator.spreadsheet import read_spreadsheet

        path = tmp_path / "sample.xlsx"
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["Summary", "Priority"])
        ws.append(["Risk A", None])
        wb.save(path)

        rows = read_spreadsheet(path)

        assert rows == [{"Summary": "Risk A", "Priority": ""}]

    def test_max_rows_limits_output(self, tmp_path: Path):
        from jiramator.spreadsheet import read_spreadsheet

        path = tmp_path / "sample.csv"
        path.write_text("Summary\nRisk A\nRisk B\nRisk C\n")

        rows = read_spreadsheet(path, max_rows=2)

        assert rows == [{"Summary": "Risk A"}, {"Summary": "Risk B"}]

    def test_skips_fully_empty_rows(self, tmp_path: Path):
        import openpyxl

        from jiramator.spreadsheet import read_spreadsheet

        path = tmp_path / "sample.xlsx"
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["Summary", "Priority"])
        ws.append(["Risk A", "High"])
        ws.append([None, None])
        ws.append(["Risk B", "Low"])
        wb.save(path)

        rows = read_spreadsheet(path)

        assert rows == [
            {"Summary": "Risk A", "Priority": "High"},
            {"Summary": "Risk B", "Priority": "Low"},
        ]

    def test_rejects_xls_extension(self, tmp_path: Path):
        from jiramator.spreadsheet import read_spreadsheet

        path = tmp_path / "legacy.xls"
        path.write_text("not really xls")

        with pytest.raises(ValueError, match=".xls is not supported"):
            read_spreadsheet(path)

    def test_rejects_unsupported_extension(self, tmp_path: Path):
        from jiramator.spreadsheet import read_spreadsheet

        path = tmp_path / "sample.txt"
        path.write_text("hello")

        with pytest.raises(ValueError, match="Unsupported spreadsheet file type"):
            read_spreadsheet(path)
