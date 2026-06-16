-- InferQ demo circuit (sparse)
-- circuit hash: 28cc090ee778683c278907f9d481b6c2d42368eb601b8a82de06241509b058b2
-- Very sparse: a 10-qubit circuit with essentially one active gate. Low entanglement, tiny query, only 2 nonzero amplitudes.
-- qubits: 10 | gates: 1 | two-qubit gates: 0 | nonzero amplitudes: 2
-- SQL CTEs: 11 (contraction: 9) | size: 2396 bytes
-- DuckDB runtime: ~0.004s on a laptop
-- Result columns: one 0/1 column per qubit (basis state) + re, im (complex amplitude).
-- Portable across DuckDB, SQLite and PostgreSQL.

WITH T0(i, re, im) AS (
  VALUES (CAST(0 AS INTEGER), CAST(1.0 AS DOUBLE PRECISION), CAST(0.0 AS DOUBLE PRECISION))
), u_4833539440(i,j, re, im) AS (
  VALUES (CAST(0 AS INTEGER), CAST(0 AS INTEGER), CAST(0.7071067811865475 AS DOUBLE PRECISION), CAST(0.0 AS DOUBLE PRECISION)), (0, 1, 0.7071067811865476, 8.659560562354934e-17), 
  (1, 0, -0.7071067811865476, -8.659560562354934e-17), (1, 1, 0.7071067811865475, 1.7319121124709863e-16)
), K1 AS (
  SELECT u_4833539440.i AS i, SUM(u_4833539440.re * T0.re - u_4833539440.im * T0.im) AS re, SUM(u_4833539440.re * T0.im + u_4833539440.im * T0.re) AS im FROM u_4833539440, T0 WHERE u_4833539440.j=T0.i GROUP BY u_4833539440.i
), K2 AS (
  SELECT T0.i AS i, T1.i AS j, SUM(T0.re * T1.re - T0.im * T1.im) AS re, SUM(T0.re * T1.im + T0.im * T1.re) AS im FROM T0, T0 T1 GROUP BY T0.i, T1.i
), K3 AS (
  SELECT T0.i AS i, T1.i AS j, SUM(T0.re * T1.re - T0.im * T1.im) AS re, SUM(T0.re * T1.im + T0.im * T1.re) AS im FROM T0, T0 T1 GROUP BY T0.i, T1.i
), K4 AS (
  SELECT T0.i AS i, T1.i AS j, SUM(T0.re * T1.re - T0.im * T1.im) AS re, SUM(T0.re * T1.im + T0.im * T1.re) AS im FROM T0, T0 T1 GROUP BY T0.i, T1.i
), K5 AS (
  SELECT T0.i AS i, T1.i AS j, SUM(T0.re * T1.re - T0.im * T1.im) AS re, SUM(T0.re * T1.im + T0.im * T1.re) AS im FROM T0, T0 T1 GROUP BY T0.i, T1.i
), K6 AS (
  SELECT K1.i AS i, T0.i AS j, SUM(K1.re * T0.re - K1.im * T0.im) AS re, SUM(K1.re * T0.im + K1.im * T0.re) AS im FROM K1, T0 GROUP BY K1.i, T0.i
), K7 AS (
  SELECT K3.i AS i, K3.j AS j, K2.i AS k, K2.j AS l, SUM(K3.re * K2.re - K3.im * K2.im) AS re, SUM(K3.re * K2.im + K3.im * K2.re) AS im FROM K3, K2 GROUP BY K3.i, K3.j, K2.i, K2.j
), K8 AS (
  SELECT K5.i AS i, K5.j AS j, K4.i AS k, K4.j AS l, SUM(K5.re * K4.re - K5.im * K4.im) AS re, SUM(K5.re * K4.im + K5.im * K4.re) AS im FROM K5, K4 GROUP BY K5.i, K5.j, K4.i, K4.j
), K9 AS (
  SELECT K7.i AS i, K7.j AS j, K7.k AS k, K7.l AS l, K6.i AS m, K6.j AS n, SUM(K7.re * K6.re - K7.im * K6.im) AS re, SUM(K7.re * K6.im + K7.im * K6.re) AS im FROM K7, K6 GROUP BY K7.i, K7.j, K7.k, K7.l, K6.i, K6.j
) SELECT K9.l AS i, K9.k AS j, K9.j AS k, K9.i AS l, K8.l AS m, K8.k AS n, K8.j AS o, K8.i AS p, K9.n AS q, K9.m AS r, SUM(K9.re * K8.re - K9.im * K8.im) AS re, SUM(K9.re * K8.im + K9.im * K8.re) AS im FROM K9, K8 GROUP BY K9.l, K9.k, K9.j, K9.i, K8.l, K8.k, K8.j, K8.i, K9.n, K9.m ORDER BY i, j, k, l, m, n, o, p, q, r

