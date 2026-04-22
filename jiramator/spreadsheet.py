"""Spreadsheet ingestion for CSV and XLSX import workflows."""

from __future__ import annotations

import csv
from pathlib import Path

import openpyxl


def _normalize_headers(headers: list[object]) -> list[str]:
    return [str(header).strip() for header in headers]


def _coerce_cell(value: object) -> str:
    if value is None:
        return ""
    return str(value)


def _read_csv(path: Path, *, max_rows: int | None = None) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            return []

        headers = _normalize_headers(list(reader.fieldnames))
        rows: list[dict[str, str]] = []
        for index, raw_row in enumerate(reader):
            if max_rows is not None and index >= max_rows:
                break
            normalized: dict[str, str] = {}
            for original, normalized_header in zip(reader.fieldnames, headers, strict=True):
                normalized[normalized_header] = _coerce_cell(raw_row.get(original))
            rows.append(normalized)
        return rows


def _read_xlsx(
    path: Path,
    *,
    sheet_name: str | None = None,
    max_rows: int | None = None,
) -> list[dict[str, str]]:
    workbook = openpyxl.load_workbook(path, data_only=True, read_only=True)
    sheet = workbook[sheet_name] if sheet_name else workbook[workbook.sheetnames[0]]

    rows_iter = sheet.iter_rows(values_only=True)
    try:
        raw_headers = next(rows_iter)
    except StopIteration:
        return []

    headers = _normalize_headers(list(raw_headers))
    rows: list[dict[str, str]] = []
    for row in rows_iter:
        normalized = {
            header: _coerce_cell(value)
            for header, value in zip(headers, row, strict=False)
        }
        if len(row) < len(headers):
            for header in headers[len(row):]:
                normalized[header] = ""
        if all(value == "" for value in normalized.values()):
            continue
        rows.append(normalized)
        if max_rows is not None and len(rows) >= max_rows:
            break
    return rows


def read_spreadsheet(
    path: str | Path,
    *,
    sheet_name: str | None = None,
    max_rows: int | None = None,
) -> list[dict[str, str]]:
    """Read a CSV or XLSX spreadsheet into a list of row dicts."""
    path = Path(path)
    suffix = path.suffix.lower()

    if suffix == ".csv":
        return _read_csv(path, max_rows=max_rows)
    if suffix == ".xlsx":
        return _read_xlsx(path, sheet_name=sheet_name, max_rows=max_rows)
    if suffix == ".xls":
        raise ValueError(".xls is not supported; save the spreadsheet as .xlsx first")
    raise ValueError(f"Unsupported spreadsheet file type: {path.suffix}")
