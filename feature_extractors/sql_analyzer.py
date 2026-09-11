
import sqlglot
from sqlglot import exp
from collections import Counter
from itertools import combinations
import logging

logger = logging.getLogger(__name__)

# Ordered on purpose: a node is counted under the first entry it matches, which
# is what the original if/elif chain did and what keeps overlapping sqlglot
# classes (an ``EQ`` is also a ``Binary``, say) from being counted twice.
_NODE_FEATURES = (
    # Clauses
    (exp.Where, "WHERE"),
    (exp.Group, "GROUP_BY"),
    (exp.Having, "HAVING"),
    (exp.Order, "ORDER_BY"),
    (exp.Limit, "LIMIT"),
    (exp.With, "CTE"),
    # Set operations
    (exp.Union, "UNION"),
    (exp.Intersect, "INTERSECT"),
    (exp.Except, "EXCEPT"),
    # Aggregates & predicates
    (exp.AggFunc, "AGG_FUNC"),
    (exp.And, "AND"),
    (exp.Or, "OR"),
    (exp.Not, "NOT"),
    (exp.EQ, "EQ_PRED"),
    ((exp.GT, exp.GTE, exp.LT, exp.LTE), "RANGE_PRED"),
    (exp.In, "IN_PRED"),
    (exp.Like, "LIKE_PRED"),
)

class SQLFeatureExtractor:
    """
    Extracts features from SQL queries using sqlglot.
    """
    
    @staticmethod
    def extract_sql_features(sql, dialect=None):
        """
        Parses a SQL query and extracts static features and join information.
        
        Args:
            sql (str): The SQL query string.
            dialect (str, optional): The SQL dialect (e.g., "postgres", "sqlite").
            
        Returns:
            tuple: (features (Counter), join_edges (set))
        """
        try:
            asts = [ast for ast in sqlglot.parse(sql, read=dialect) if ast is not None]
        except Exception as e:
            logger.error(f"Failed to parse SQL: {e}")
            return Counter(), set()

        features = Counter()

        # ---------- 1. COUNT TOP-LEVEL COMMANDS / CLAUSES / AGGREGATES ----------
        cmd_map = {
            exp.Select: "SELECT",
            exp.Insert: "INSERT",
            exp.Update: "UPDATE",
            exp.Delete: "DELETE",
            exp.Create: "CREATE",
        }
        
        for ast in asts:
            for node in ast.walk():
                # Top-level SQL commands
                if type(node) in cmd_map:
                    features[cmd_map[type(node)]] += 1
                # Clauses, set operations, aggregates and predicates
                for node_types, feature_name in _NODE_FEATURES:
                    if isinstance(node, node_types):
                        features[feature_name] += 1
                        break

        # ---------- 2. SEMANTIC JOIN COUNT (IMPLICIT + EXPLICIT) ----------
        join_edges = set()
        join_occurrences = 0

        def referenced_relations(expr):
            rels = set()
            for col in expr.find_all(exp.Column):
                table_name = col.table
                if table_name:
                    # resolve alias if needed
                    if isinstance(table_name, exp.TableAlias):
                        table_name = table_name.alias_or_name
                    rels.add(table_name)
            return rels

        def visit_select(select):
            nonlocal join_edges, join_occurrences

            # Implicit joins via WHERE
            where = select.args.get("where")
            if where:
                for pred in where.walk():
                    if isinstance(pred, (exp.EQ, exp.GT, exp.GTE, exp.LT, exp.LTE)):
                        rels = referenced_relations(pred)
                        if len(rels) >= 2:
                            join_occurrences += 1
                            for a, b in combinations(sorted(rels), 2):
                                join_edges.add((a, b))

            # Explicit JOIN ... ON. A sqlglot Join node holds only the
            # right-hand relation, so the pair of relations has to be read out
            # of the ON condition, exactly as the implicit case reads WHERE.
            for join in select.find_all(exp.Join):
                on_clause = join.args.get("on")
                if on_clause is None:
                    continue
                rels = referenced_relations(on_clause)
                if len(rels) >= 2:
                    join_occurrences += 1
                    for a, b in combinations(sorted(rels), 2):
                        join_edges.add((a, b))

            # Recurse into subqueries in FROM
            from_clause = select.args.get("from")
            if from_clause:
                for subq in from_clause.find_all(exp.Subquery):
                    for inner in subq.find_all(exp.Select):
                        visit_select(inner)

        for ast in asts:
            for select in ast.find_all(exp.Select):
                visit_select(select)

        features["NUM_UNIQUE_JOIN_EDGES"] = len(join_edges)
        features["NUM_JOIN_OCCURRENCES"] = join_occurrences

        return features, join_edges
