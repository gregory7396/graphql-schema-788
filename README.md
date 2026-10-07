# CSV Schema Inferer

Analyzes a CSV file by sampling rows and reports an inferred type (`bool`, `int`, `float`, `date`, `datetime`, `string`) for each column. Standard library only, no third-party dependencies.

## Usage

```python
import tempfile, os
from csv_schema_inferer import infer_schema, infer_column_types, TypeInferer

data = "id,name,score,active,joined,note\n1,Alice,9.5,true,2023-01-15,hello\n2,Bob,7.0,false,2023-01-16,world\n3,Cara,8.25,true,2023-01-17,foo\n"
fd, path = tempfile.mkstemp(suffix=".csv", text=True)
with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
    fh.write(data)

# Full file-based inference:
schema = infer_schema(path, sample_size=100)
for column in schema:
    print(column["name"], column["type"], column["count"], column["nonempty"])

os.unlink(path)

# `infer_column_types` is the same function under a more precise name.
# `TypeInferer` lets you feed rows yourself when you already have an iterator.
```

Each entry in the returned list is a dict with four keys: `name` (str), `type` (str), `count` (int, sampled data rows), and `nonempty` (int, sampled non-empty values).

## Why this exists

The problem: you have a CSV of unknown provenance and you need to know whether each column is numeric before you load it into a database, a dataframe, or a typed struct. Doing this wrong means either crashing your parser on a stray non-numeric value, or silently coercing everything to string and losing the ability to do arithmetic.

The trade-off this library makes is sampling. It reads at most `sample_size` data rows (default 100) per file, so it is bounded in memory and usable on multi-gigabyte exports. The cost: a column that happens to look numeric in the first 100 rows but contains text later will be reported as `int` or `float`. For ETL pipelines that re-validate on load, that is the right trade; for one-shot forensic analysis it is not.

## Awkward edges you will hit

- **Dates are ISO 8601 only.** `2023-01-15` and `2023-01-15T10:30:00` are recognised; `01/15/2023` is reported as `string`. Supporting locale date formats opens the `dd/mm` vs `mm/dd` ambiguity, which is not worth the complexity. If your source uses another format, pre-normalise or accept `string`.
- **Booleans are strict.** Only `true`/`false`/`yes`/`no`/`on`/`off` (case-insensitive, plus `t`/`f`/`y`/`n`) qualify. The string `"1"` is an `int`, not a `bool`. Mixing the two would silently corrupt downstream consumers that distinguish 1/0 booleans from 1/0 counts.
- **`NaN` and `Infinity` are rejected** as float literals. A column containing both `1.5` and `NaN` is reported as `string`, because in real data that combination is almost always an ingestion bug rather than a genuine floating-point sentinel.
- **Empty cells are skipped when narrowing.** A column of `1, 2, "", 3` is `int`. A column that is entirely empty is reported as `string` (the least-lossy bucket), not `bool`.
- **Rows shorter than the header** contribute empty strings for the missing cells. Rows longer than the header have their extra cells dropped rather than raising — real CSV exports are routinely one-delimiter-messy and the tool would be unusable if it crashed on the first malformed line.
- **Quoted fields with embedded newlines** are handled via the stdlib `csv` module; `"1,\"line one\nline two\""` is one data cell.

## Constructor arguments

`infer_schema(path, sample_size=100, has_header=True, encoding="utf-8", delimiter=",")`

`has_header=False` synthesises column names `col_0`, `col_1`, ... and treats the first row as data.
