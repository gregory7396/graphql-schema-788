import os
import tempfile
import unittest

from csv_schema_inferer.core import (
    _classify_value,
    _parse_bool,
    _parse_float,
    _parse_int,
    infer_column_types,
    infer_schema,
    TypeInferer,
)


def _write_csv(text: str, encoding: str = "utf-8") -> str:
    """Write text to a temporary file and return its path.

    Using delete=False and manually unlinking in tearDown keeps the tests
    deterministic and avoids leaking file handles on Windows.
    """
    fd, path = tempfile.mkstemp(suffix=".csv", text=True)
    with os.fdopen(fd, "w", encoding=encoding, newline="") as fh:
        fh.write(text)
    return path


class TestPrimitives(unittest.TestCase):
    def test_parse_int_clean(self):
        self.assertEqual(_parse_int("42"), 42)
        self.assertEqual(_parse_int("-7"), -7)
        self.assertEqual(_parse_int("+3"), 3)
        self.assertEqual(_parse_int("0"), 0)
        self.assertIsNone(_parse_int("1.5"))
        self.assertIsNone(_parse_int("1_000"))
        self.assertIsNone(_parse_int(""))
        self.assertIsNone(_parse_int("abc"))

    def test_parse_float_clean(self):
        self.assertEqual(_parse_float("1.5"), 1.5)
        self.assertEqual(_parse_float("-0.25"), -0.25)
        self.assertEqual(_parse_float("6.022e23"), 6.022e23)
        self.assertIsNone(_parse_float("NaN"))
        self.assertIsNone(_parse_float("inf"))
        self.assertIsNone(_parse_float("Infinity"))
        self.assertIsNone(_parse_float("abc"))
        self.assertIsNone(_parse_float(""))

    def test_parse_bool_strict(self):
        self.assertTrue(_parse_bool("true"))
        self.assertTrue(_parse_bool("YES"))
        self.assertFalse(_parse_bool("false"))
        self.assertFalse(_parse_bool("No"))
        self.assertIsNone(_parse_bool("1"))
        self.assertIsNone(_parse_bool("0"))
        self.assertIsNone(_parse_bool("maybe"))
        self.assertIsNone(_parse_bool(""))

    def test_classify_date(self):
        self.assertEqual(_classify_value("2023-01-15"), "date")
        self.assertEqual(_classify_value("2023-01-15T10:30:00"), "datetime")
        self.assertEqual(_classify_value("2023-01-15 10:30:00"), "datetime")
        # Bare 4-digit year is not a date under ISO 8601; it falls back to int.
        self.assertEqual(_classify_value("2023"), "int")
        # Insufficient zero padding rejected by fromisoformat -> string.
        self.assertEqual(_classify_value("2023-1-5"), "string")

    def test_classify_precedence(self):
        # bool token even though "true" is not numeric
        self.assertEqual(_classify_value("true"), "bool")
        # int beats float for clean integer strings
        self.assertEqual(_classify_value("7"), "int")
        # float when value has a decimal point
        self.assertEqual(_classify_value("7.0"), "float")
        # scientific notation routes to float
        self.assertEqual(_classify_value("1e3"), "float")
        # pure garbage
        self.assertEqual(_classify_value("hello"), "string")


class TestTypeInferer(unittest.TestCase):
    def test_single_column_widening(self):
        inf = TypeInferer(["a"])
        inf.observe_row(["1"])
        inf.observe_row(["2"])
        inf.observe_row(["3.5"])
        inf.observe_row(["4"])
        # int widened to float once 3.5 appears
        result = inf.finalize()
        self.assertEqual(result[0]["type"], "float")
        self.assertEqual(result[0]["count"], 4)
        self.assertEqual(result[0]["nonempty"], 4)

    def test_empty_values_skipped_in_narrowing(self):
        inf = TypeInferer(["a"])
        inf.observe_row(["1"])
        inf.observe_row([""])
        inf.observe_row(["2"])
        inf.observe_row(["3"])
        # Empty values do not widen to string; the column stays int.
        result = inf.finalize()
        self.assertEqual(result[0]["type"], "int")
        self.assertEqual(result[0]["count"], 4)
        self.assertEqual(result[0]["nonempty"], 3)

    def test_all_empty_column_is_string(self):
        inf = TypeInferer(["a"])
        inf.observe_row([""])
        inf.observe_row([""])
        result = inf.finalize()
        # Initial sentinel bool is overridden to string for empty columns.
        self.assertEqual(result[0]["type"], "string")
        self.assertEqual(result[0]["nonempty"], 0)

    def test_short_row_treated_as_empty(self):
        inf = TypeInferer(["a", "b"])
        inf.observe_row(["1"])  # b missing -> empty
        result = inf.finalize()
        self.assertEqual(result[0]["type"], "int")
        self.assertEqual(result[1]["type"], "string")
        self.assertEqual(result[1]["nonempty"], 0)

    def test_extra_cells_dropped(self):
        inf = TypeInferer(["a", "b"])
        inf.observe_row(["1", "2", "3", "4"])
        result = inf.finalize()
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["type"], "int")
        self.assertEqual(result[1]["type"], "int")

    def test_whitespace_stripped(self):
        inf = TypeInferer(["a"])
        inf.observe_row(["  42  "])
        result = inf.finalize()
        self.assertEqual(result[0]["type"], "int")
        self.assertEqual(result[0]["nonempty"], 1)

    def test_bool_then_int_widens_to_int(self):
        inf = TypeInferer(["a"])
        inf.observe_row(["true"])
        inf.observe_row(["7"])
        result = inf.finalize()
        self.assertEqual(result[0]["type"], "int")

    def test_int_then_string_widens_to_string(self):
        inf = TypeInferer(["a"])
        inf.observe_row(["1"])
        inf.observe_row(["2"])
        inf.observe_row(["banana"])
        result = inf.finalize()
        self.assertEqual(result[0]["type"], "string")

    def test_date_then_datetime_widens_to_datetime(self):
        inf = TypeInferer(["a"])
        inf.observe_row(["2023-01-01"])
        inf.observe_row(["2023-01-02T10:00:00"])
        result = inf.finalize()
        self.assertEqual(result[0]["type"], "datetime")


class TestFileIntegration(unittest.TestCase):
    def setUp(self):
        self.paths: list[str] = []

    def tearDown(self):
        for p in self.paths:
            try:
                os.unlink(p)
            except OSError:
                pass

    def _tmp(self, text: str) -> str:
        path = _write_csv(text)
        self.paths.append(path)
        return path

    def test_basic_mixed_schema(self):
        path = self._tmp(
            "id,name,score,active,joined,note\n"
            "1,Alice,9.5,true,2023-01-15,hello\n"
            "2,Bob,7.0,false,2023-01-16,world\n"
            "3,Cara,8.25,true,2023-01-17,foo\n"
        )
        result = infer_column_types(path)
        types = [c["type"] for c in result]
        self.assertEqual(types, ["int", "string", "float", "bool", "date", "string"])
        self.assertEqual(result[0]["count"], 3)
        self.assertEqual(result[0]["nonempty"], 3)

    def test_empty_file_returns_empty_list(self):
        path = self._tmp("")
        self.assertEqual(infer_column_types(path), [])

    def test_header_only(self):
        path = self._tmp("a,b,c\n")
        result = infer_column_types(path)
        self.assertEqual([c["name"] for c in result], ["a", "b", "c"])
        self.assertEqual([c["type"] for c in result], ["string", "string", "string"])
        for c in result:
            self.assertEqual(c["count"], 0)

    def test_no_header(self):
        path = self._tmp("1,Alice,true\n2,Bob,false\n3,Cara,true\n")
        result = infer_column_types(path, has_header=False)
        self.assertEqual([c["name"] for c in result], ["col_0", "col_1", "col_2"])
        self.assertEqual([c["type"] for c in result], ["int", "string", "bool"])
        # All three data rows consumed.
        self.assertEqual(result[0]["count"], 3)

    def test_sample_size_bounds_rows(self):
        # 5 data rows but sample_size=2 -> count is 2.
        path = self._tmp("n\n1\n2\n3\n4\n5\n")
        result = infer_column_types(path, sample_size=2)
        self.assertEqual(result[0]["count"], 2)
        self.assertEqual(result[0]["type"], "int")

    def test_sample_size_zero(self):
        path = self._tmp("n\n1\n2\n3\n")
        result = infer_column_types(path, sample_size=0)
        self.assertEqual(result[0]["count"], 0)
        # No data rows seen -> empty column -> string.
        self.assertEqual(result[0]["type"], "string")

    def test_negative_sample_raises(self):
        path = self._tmp("a\n1\n")
        with self.assertRaises(ValueError):
            infer_column_types(path, sample_size=-1)

    def test_invalid_delimiter_raises(self):
        path = self._tmp("a\n1\n")
        with self.assertRaises(ValueError):
            infer_column_types(path, delimiter=",,")

    def test_quoted_fields(self):
        path = self._tmp(
            'id,label\n'
            '1,"hello, world"\n'
            '2,"foo"\n'
        )
        result = infer_column_types(path)
        self.assertEqual(result[1]["name"], "label")
        self.assertEqual(result[1]["type"], "string")
        self.assertEqual(result[1]["nonempty"], 2)

    def test_semicolon_delimiter(self):
        path = self._tmp("a;b\n1;2\n3;4\n")
        result = infer_column_types(path, delimiter=";")
        self.assertEqual([c["name"] for c in result], ["a", "b"])
        self.assertEqual([c["type"] for c in result], ["int", "int"])

    def test_alias_returns_same_shape(self):
        path = self._tmp("a\n1\n2\n")
        r1 = infer_column_types(path)
        r2 = infer_schema(path)
        self.assertEqual(r1, r2)

    def test_quoted_newlines_in_field(self):
        path = self._tmp('id,note\n1,"line one\nline two"\n2,plain\n')
        result = infer_column_types(path)
        self.assertEqual(result[0]["count"], 2)
        self.assertEqual(result[1]["name"], "note")
        self.assertEqual(result[1]["type"], "string")

    def test_int_with_leading_plus(self):
        path = self._tmp("a\n+10\n-3\n0\n")
        result = infer_column_types(path)
        self.assertEqual(result[0]["type"], "int")

    def test_float_scientific_notation(self):
        path = self._tmp("a\n1.5e3\n2.0\n-1.25e-2\n")
        result = infer_column_types(path)
        self.assertEqual(result[0]["type"], "float")

    def test_nan_rejected(self):
        # A column with NaN and a real float should fall back to string,
        # because we deliberately reject NaN/Infinity literals.
        path = self._tmp("a\n1.5\nNaN\n2.0\n")
        result = infer_column_types(path)
        self.assertEqual(result[0]["type"], "string")

    def test_datetime_promotion(self):
        path = self._tmp(
            "ts\n"
            "2023-01-01T00:00:00\n"
            "2023-01-02T12:30:45\n"
        )
        result = infer_column_types(path)
        self.assertEqual(result[0]["type"], "datetime")

    def test_trailing_newline_optional(self):
        path_without = self._tmp("a\n1\n2")
        path_with = self._tmp("a\n1\n2\n")
        self.assertEqual(
            [c["type"] for c in infer_column_types(path_without)],
            [c["type"] for c in infer_column_types(path_with)],
        )

    def test_latin1_encoding(self):
        text = "name,city\nPádraig,München\nPlain,London\n"
        path = _write_csv(text, encoding="latin-1")
        self.paths.append(path)
        result = infer_column_types(path, encoding="latin-1")
        # Both columns contain non-numeric text -> string.
        self.assertEqual([c["type"] for c in result], ["string", "string"])
        self.assertEqual(result[0]["nonempty"], 2)


if __name__ == "__main__":
    unittest.main()
