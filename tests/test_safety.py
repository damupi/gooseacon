import csv
import io

import pytest
from pydantic import ValidationError

from gooseacon.analytics import Query
from gooseacon.output import Format, render


@pytest.mark.parametrize("dimension", ["date", "hour"])
def test_filter_dimensions_reject_date_and_hour(dimension):
    with pytest.raises(ValidationError):
        Query(
            startDate="2026-08-01",
            endDate="2026-08-31",
            dimensionFilterGroups=[
                {"filters": [{"dimension": dimension, "expression": "2026-08-01"}]}
            ],
        )


@pytest.mark.parametrize(
    "text",
    [
        '=HYPERLINK("https://example.com")',
        "+1+2",
        "-1+2",
        "@SUM(A1:A2)",
        "  =1+2",
        "\t=1+2",
        "\r=1+2",
        "\n=1+2",
    ],
)
def test_csv_formula_safety(text):
    row = list(csv.DictReader(io.StringIO(render([{"query": text, "change": -1}], Format.csv))))[0]
    assert row["query"] == "'" + text
    assert row["change"] == "-1"
    assert render([{"query": text}], Format.json).find("'" + text) == -1


def test_csv_preserves_normal_text():
    rows = [{"query": "normal search", "clicks": 10, "ctr": 0.2}]
    assert render(rows, Format.csv) == "query,clicks,ctr\nnormal search,10,0.2\n"
