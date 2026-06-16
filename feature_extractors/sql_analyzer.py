
import sqlglot
from sqlglot import exp
from collections import Counter
from itertools import combinations
import logging

logger = logging.getLogger(__name__)

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
                # Clauses
                if isinstance(node, exp.Where): features["WHERE"] += 1
                elif isinstance(node, exp.Group): features["GROUP_BY"] += 1
                elif isinstance(node, exp.Having): features["HAVING"] += 1
                elif isinstance(node, exp.Order): features["ORDER_BY"] += 1
                elif isinstance(node, exp.Limit): features["LIMIT"] += 1
                elif isinstance(node, exp.With): features["CTE"] += 1
                # Set operations
                elif isinstance(node, exp.Union): features["UNION"] += 1
                elif isinstance(node, exp.Intersect): features["INTERSECT"] += 1
                elif isinstance(node, exp.Except): features["EXCEPT"] += 1
                # Aggregates & predicates
                elif isinstance(node, exp.AggFunc): features["AGG_FUNC"] += 1
                elif isinstance(node, exp.And): features["AND"] += 1
                elif isinstance(node, exp.Or): features["OR"] += 1
                elif isinstance(node, exp.Not): features["NOT"] += 1
                elif isinstance(node, exp.EQ): features["EQ_PRED"] += 1
                elif isinstance(node, (exp.GT, exp.GTE, exp.LT, exp.LTE)): features["RANGE_PRED"] += 1
                elif isinstance(node, exp.In): features["IN_PRED"] += 1
                elif isinstance(node, exp.Like): features["LIKE_PRED"] += 1

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

            # Explicit JOIN ... ON
            for join in select.find_all(exp.Join):
                left = join.this
                right = join.args.get("this")
                if left and right:
                    a, b = left.alias_or_name, right.alias_or_name
                    if a and b and a != b:
                        join_occurrences += 1
                        join_edges.add(tuple(sorted((a, b))))

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
