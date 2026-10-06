from __future__ import annotations

import csv
import io
import os
from typing import Iterable

_TRUE_TOKENS = {"true", "t", "yes", "y", "on"}
_FALSE_TOKENS = {"false", "f", "no", "n", "off"}

_TYPE_RANK = {
    "bool": 0,
    "int": 1,
    "float": 2,
    "date": 3,
    "datetime": 4,
    "string": 5,
}


def _parse_int(s: str) -> int | None:
    if s == "":
        return None
    if "_" in s:
        return None
    try:
        return int(s, 10)
    except ValueError:
        return None


def _parse_float(s: str) -> float | None:
    if s == "":
        return None
    lowered = s.lower()
    if "inf" in lowered or "nan" in lowered:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _parse_bool(s: str) -> bool | None:
    lowered = s.lower()
    if lowered in _TRUE_TOKENS:
        return True
    if lowered in _FALSE_TOKENS:
        return False
    return None


def _check_date(s: str) -> str | None:
    if s == "":
        return None
    from datetime import datetime, date

    try:
        parsed = date.fromisoformat(s)
        if isinstance(parsed, date) and "T" not in s.upper():
            return "date"
    except ValueError:
        pass

    try:
        datetime.fromisoformat(s)
        return "datetime"
    except ValueError:
        return None


def _classify_value(s: str) -> str:
    if _parse_bool(s) is not None:
        return "bool"
    if _parse_int(s) is not None:
        return "int"
    if _parse_float(s) is not None:
        return "float"
    dt = _check_date(s)
    if dt is not None:
        return dt
    return "string"


def _widen(current: str, candidate: str) -> str:
    if _TYPE_RANK[candidate] > _TYPE_RANK[current]:
        return candidate
    return current


class TypeInferer:
    def __init__(self, column_names: list[str]):
        self.column_names = list(column_names)
        self.types: list[str] = ["bool"] * len(self.column_names)
        self.counts: list[int] = [0] * len(self.column_names)
        self.nonempty: list[int] = [0] * len(self.column_names)

    def observe_row(self, row: Iterable[str]) -> None:
        row_list = list(row)
        for i in range(len(self.column_names)):
            self.counts[i] += 1
            raw = row_list[i] if i < len(row_list) else ""
            v = raw.strip()
            if v == "":
                continue
            self.nonempty[i] += 1
            kind = _classify_value(v)
            self.types[i] = _widen(self.types[i], kind)

    def finalize(self) -> list[dict]:
        out: list[dict] = []
        for i, name in enumerate(self.column_names):
            t = self.types[i]
            if self.nonempty[i] == 0:
                t = "string"
            out.append(
                {
                    "name": name,
                    "type": t,
                    "count": self.counts[i],
                    "nonempty": self.nonempty[i],
                }
            )
        return out


def infer_column_types(
    path: str,
    sample_size: int = 100,
    has_header: bool = True,
    encoding: str = "utf-8",
    delimiter: str = ",",
) -> list[dict]:
    if sample_size < 0:
        raise ValueError("sample_size must be non-negative")
    if len(delimiter) != 1:
        raise ValueError("delimiter must be a single character")

    with open(path, "r", encoding=encoding, newline="") as fh:
        reader = csv.reader(fh, delimiter=delimiter)

        try:
            first_row = next(reader)
        except StopIteration:
            return []

        if has_header:
            column_names = [c.strip() for c in first_row]
            inferer = TypeInferer(column_names)
        else:
            column_names = [f"col_{i}" for i in range(len(first_row))]
            inferer = TypeInferer(column_names)
            inferer.observe_row(first_row)

        rows_consumed = 0 if has_header else 1
        for row in reader:
            if rows_consumed >= sample_size:
                break
            inferer.observe_row(row)
            rows_consumed += 1

        return inferer.finalize()


def infer_schema(
    path: str,
    sample_size: int = 100,
    has_header: bool = True,
    encoding: str = "utf-8",
    delimiter: str = ",",
) -> list[dict]:
    return infer_column_types(
        path,
        sample_size=sample_size,
        has_header=has_header,
        encoding=encoding,
        delimiter=delimiter,
    )
