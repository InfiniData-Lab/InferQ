"""Tests for the InfiniQuantumSim method-omission list.

`benchmark_ciruit_performance` runs every backend that is absent from the list
InferQ hands it. Upstream carries two array stores -- SciDB, reached over HTTP
on localhost, and TileDB -- that this project neither configures nor records.
Leaving them in blocks the monolithic path on a refused connection before any
timing is taken, so they have to be omitted unconditionally, whatever a caller
or the config file asks for.
"""

from __future__ import annotations

from inferq.simulation.infiniquantum import (
    _UNSUPPORTED_IQS_METHODS,
    _normalise_omit_methods,
)


def test_array_stores_are_omitted_when_the_caller_asks_for_nothing():
    assert set(_normalise_omit_methods([])) == set(_UNSUPPORTED_IQS_METHODS)


def test_array_stores_are_omitted_when_no_list_is_given_at_all():
    assert set(_normalise_omit_methods(None)) == set(_UNSUPPORTED_IQS_METHODS)


def test_caller_methods_are_kept_alongside_the_array_stores():
    omitted = _normalise_omit_methods(["psql", "umbra"])
    assert set(omitted) == {"psql", "umbra", *_UNSUPPORTED_IQS_METHODS}


def test_aliases_are_normalised_to_the_upstream_names():
    omitted = _normalise_omit_methods(["duckdb", "np_mps", "np_one_shot"])
    assert {"ducksql", "np-mps", "np-one-shot"} <= set(omitted)
    assert "duckdb" not in omitted


def test_an_explicit_array_store_is_not_listed_twice():
    omitted = _normalise_omit_methods(["scidb", "sqlite"])
    assert omitted.count("scidb") == 1
    assert set(omitted) == {"sqlite", *_UNSUPPORTED_IQS_METHODS}
