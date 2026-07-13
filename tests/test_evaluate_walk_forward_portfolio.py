from scripts.evaluate_walk_forward_portfolio import evaluate_payload


def test_evaluate_payload_uses_explicit_candidate_series_for_portfolio_metrics() -> None:
    payload = {
        "candidate_series": {
            "trend": {"2021-01": "0.10", "2021-02": "-0.02", "2021-03": "0.04"},
            "range": {"2021-01": "0.00", "2021-02": "0.06", "2021-03": "0.02"},
        }
    }

    result = evaluate_payload(payload)

    assert result["candidate_count"] == 2
    assert result["months"] == ["2021-01", "2021-02", "2021-03"]
    assert result["candidate_series"] == {
        "range": [
            {"month": "2021-01", "return_ratio": "0.00"},
            {"month": "2021-02", "return_ratio": "0.06"},
            {"month": "2021-03", "return_ratio": "0.02"},
        ],
        "trend": [
            {"month": "2021-01", "return_ratio": "0.10"},
            {"month": "2021-02", "return_ratio": "-0.02"},
            {"month": "2021-03", "return_ratio": "0.04"},
        ],
    }
    assert result["portfolio_monthly_returns"] == [
        {"month": "2021-01", "return_ratio": "0.05"},
        {"month": "2021-02", "return_ratio": "0.02"},
        {"month": "2021-03", "return_ratio": "0.03"},
    ]
    assert result["portfolio_summary"] == {
        "average_monthly_return": "0.03333333333333333333333333333",
        "min_monthly_return": "0.02",
        "worst_monthly_drawdown_proxy": "0.02",
        "positive_month_ratio": "1",
        "positive_month_count": 3,
        "month_count": 3,
    }
    assert result["correlations"] == [
        {"candidate_a": "range", "candidate_b": "trend", "correlation": "-0.9819805060619657"}
    ]


def test_evaluate_payload_infers_candidate_series_from_walk_forward_folds() -> None:
    payload = {
        "folds": [
            {
                "test_period": {"start_at": "2021-01-01T00:00:00+00:00"},
                "results": [
                    {"candidate_id": "trend", "return_ratio": "0.10"},
                    {"candidate_id": "range", "return_ratio": "0.00"},
                ],
            },
            {
                "test_period": {"start_at": "2021-02-01T00:00:00+00:00"},
                "results": [
                    {"candidate_id": "trend", "return_ratio": "-0.02"},
                    {"candidate_id": "range", "return_ratio": "0.06"},
                ],
            },
        ]
    }

    result = evaluate_payload(payload)

    assert result["candidate_series"]["trend"] == [
        {"month": "2021-01", "return_ratio": "0.10"},
        {"month": "2021-02", "return_ratio": "-0.02"},
    ]
    assert result["portfolio_monthly_returns"] == [
        {"month": "2021-01", "return_ratio": "0.05"},
        {"month": "2021-02", "return_ratio": "0.02"},
    ]
    assert result["portfolio_summary"]["average_monthly_return"] == "0.035"
