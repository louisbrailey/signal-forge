"""Liquid U.S. research-universe pipeline (grouped-daily bulk path).

Discovery -> raw bulk archive -> eligibility screen (exact exclusion reasons)
-> normalized bars for eligible symbols only -> post-close scan. Every stage
reports counts; every snapshot states that bulk history is split-adjusted AS
OF the fetch date (not point-in-time) and discovery is active-only (not
survivorship-free). Research / paper-trading only: this package never
promotes a strategy, widens alert eligibility, auto-simulates, or creates a
paper trade.
"""
