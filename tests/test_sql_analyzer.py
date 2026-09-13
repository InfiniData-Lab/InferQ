"""SQL feature extraction, including the join topology the features report."""

from inferq.features.sql_analyzer import SQLFeatureExtractor


def extract(sql: str):
    return SQLFeatureExtractor.extract_sql_features(sql)


def test_explicit_join_produces_an_edge():
    """A JOIN ... ON names both relations only inside the ON condition.

    The join node itself carries just the right-hand relation, so reading the
    pair off the node compared a relation with itself and found no join at all.
    """
    features, edges = extract(
        "SELECT a.i FROM t0 AS a JOIN t1 AS b ON a.j = b.j"
    )

    assert edges == {("a", "b")}
    assert features["NUM_UNIQUE_JOIN_EDGES"] == 1
    assert features["NUM_JOIN_OCCURRENCES"] == 1


def test_implicit_join_produces_an_edge():
    _, edges = extract("SELECT a.i FROM t0 AS a, t1 AS b WHERE a.j = b.j")

    assert edges == {("a", "b")}


def test_single_relation_predicate_is_not_a_join():
    features, edges = extract("SELECT a.i FROM t0 AS a WHERE a.i > 0")

    assert edges == set()
    assert features["NUM_JOIN_OCCURRENCES"] == 0


def test_clause_and_predicate_counts():
    features, _ = extract(
        "SELECT SUM(a.v) FROM t0 AS a WHERE a.i > 0 AND a.k = 1 GROUP BY a.i"
    )

    assert features["SELECT"] == 1
    assert features["WHERE"] == 1
    assert features["GROUP_BY"] == 1
    assert features["AGG_FUNC"] == 1
    assert features["AND"] == 1
    assert features["RANGE_PRED"] == 1
    assert features["EQ_PRED"] == 1


def test_unparseable_sql_yields_empty_features():
    features, edges = extract("this is not sql (((")

    assert features == {} or features["NUM_JOIN_OCCURRENCES"] == 0
    assert edges == set()
