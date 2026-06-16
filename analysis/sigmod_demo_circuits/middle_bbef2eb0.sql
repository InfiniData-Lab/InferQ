-- InferQ demo circuit (middle)
-- circuit hash: bbef2eb030ecffdd8f7e4864e232dc80135b8f0f48add8b7d52b1d15c4cb3483
-- Middle: a 10-qubit circuit with moderate gate count and ~30% two-qubit gates. Produces a fully dense 10-qubit statevector (1024 amplitudes).
-- qubits: 10 | gates: 31 | two-qubit gates: 10 | nonzero amplitudes: 1024
-- SQL CTEs: 45 (contraction: 39) | size: 11519 bytes
-- DuckDB runtime: ~0.016s on a laptop
-- Result columns: one 0/1 column per qubit (basis state) + re, im (complex amplitude).
-- Portable across DuckDB, SQLite and PostgreSQL.

WITH T0(i, re, im) AS (
  VALUES (CAST(0 AS INTEGER), CAST(1.0 AS DOUBLE PRECISION), CAST(0.0 AS DOUBLE PRECISION))
), u_4833179984(i,j, re, im) AS (
  VALUES (CAST(0 AS INTEGER), CAST(0 AS INTEGER), CAST(0.7071067811865475 AS DOUBLE PRECISION), CAST(0.0 AS DOUBLE PRECISION)), (0, 1, 0.7071067811865476, 8.659560562354934e-17), 
  (1, 0, -0.4567213899486843, 0.539819944021469), (1, 1, 0.4567213899486843, -0.5398199440214688)
), u_4833180880(i,j, re, im) AS (
  VALUES (CAST(0 AS INTEGER), CAST(0 AS INTEGER), CAST(0.7071067811865477 AS DOUBLE PRECISION), CAST(0.0 AS DOUBLE PRECISION)), (0, 1, 0.7071067811865475, 8.659560562354932e-17), 
  (1, 0, 0.38431841884797363, -0.5935481049874504), (1, 1, -0.3843184188479738, 0.5935481049874506)
), u_4833986896(i,j, re, im) AS (
  VALUES (CAST(0 AS INTEGER), CAST(0 AS INTEGER), CAST(-0.25872659071876275 AS DOUBLE PRECISION), CAST(0.0 AS DOUBLE PRECISION)), (0, 1, -5.91474151920568e-17, -0.9659505946243037), 
  (1, 0, 5.91474151920568e-17, -0.9659505946243037), (1, 1, -0.25872659071876275, 0.0)
), cx(i,j,k,l, re, im) AS (
  VALUES (CAST(0 AS INTEGER), CAST(0 AS INTEGER), CAST(0 AS INTEGER), CAST(0 AS INTEGER), CAST(1.0 AS DOUBLE PRECISION), CAST(0.0 AS DOUBLE PRECISION)), 
  (0, 1, 1, 1, 1.0, 0.0), 
  (1, 0, 1, 0, 1.0, 0.0), 
  (1, 1, 0, 1, 1.0, 0.0)
), u_4833988304(i,j, re, im) AS (
  VALUES (CAST(0 AS INTEGER), CAST(0 AS INTEGER), CAST(0.7071067811865476 AS DOUBLE PRECISION), CAST(0.0 AS DOUBLE PRECISION)), (0, 1, 0.7071067811865475, -8.659560562354932e-17), 
  (1, 0, 0.7071067811865475, 0.0), (1, 1, -0.7071067811865476, 8.659560562354934e-17)
), K1 AS (
  SELECT u_4833986896.i AS i, SUM(u_4833986896.re * T0.re - u_4833986896.im * T0.im) AS re, SUM(u_4833986896.re * T0.im + u_4833986896.im * T0.re) AS im FROM u_4833986896, T0 WHERE u_4833986896.j=T0.i GROUP BY u_4833986896.i
), K2 AS (
  SELECT u_4833179984.i AS i, SUM(u_4833179984.re * T0.re - u_4833179984.im * T0.im) AS re, SUM(u_4833179984.re * T0.im + u_4833179984.im * T0.re) AS im FROM u_4833179984, T0 WHERE u_4833179984.j=T0.i GROUP BY u_4833179984.i
), K3 AS (
  SELECT u_4833179984.i AS i, SUM(u_4833179984.re * T0.re - u_4833179984.im * T0.im) AS re, SUM(u_4833179984.re * T0.im + u_4833179984.im * T0.re) AS im FROM u_4833179984, T0 WHERE u_4833179984.j=T0.i GROUP BY u_4833179984.i
), K4 AS (
  SELECT u_4833179984.i AS i, cx.i AS j, cx.k AS k, cx.l AS l, SUM(u_4833179984.re * cx.re - u_4833179984.im * cx.im) AS re, SUM(u_4833179984.re * cx.im + u_4833179984.im * cx.re) AS im FROM u_4833179984, cx WHERE u_4833179984.j=cx.j GROUP BY u_4833179984.i, cx.i, cx.k, cx.l
), K5 AS (
  SELECT u_4833986896.i AS i, cx.i AS j, cx.k AS k, cx.l AS l, SUM(u_4833986896.re * cx.re - u_4833986896.im * cx.im) AS re, SUM(u_4833986896.re * cx.im + u_4833986896.im * cx.re) AS im FROM u_4833986896, cx WHERE u_4833986896.j=cx.j GROUP BY u_4833986896.i, cx.i, cx.k, cx.l
), K6 AS (
  SELECT cx.i AS i, cx.j AS j, cx.k AS k, SUM(K2.re * cx.re - K2.im * cx.im) AS re, SUM(K2.re * cx.im + K2.im * cx.re) AS im FROM K2, cx WHERE K2.i=cx.l GROUP BY cx.i, cx.j, cx.k
), K7 AS (
  SELECT K4.i AS i, K4.j AS j, K4.k AS k, SUM(K4.re * K3.re - K4.im * K3.im) AS re, SUM(K4.re * K3.im + K4.im * K3.re) AS im FROM K4, K3 WHERE K4.l=K3.i GROUP BY K4.i, K4.j, K4.k
), K8 AS (
  SELECT u_4833179984.i AS i, SUM(u_4833179984.re * T0.re - u_4833179984.im * T0.im) AS re, SUM(u_4833179984.re * T0.im + u_4833179984.im * T0.re) AS im FROM u_4833179984, T0 WHERE u_4833179984.j=T0.i GROUP BY u_4833179984.i
), K9 AS (
  SELECT cx.i AS i, cx.j AS j, cx.k AS k, u_4833180880.j AS l, SUM(cx.re * u_4833180880.re - cx.im * u_4833180880.im) AS re, SUM(cx.re * u_4833180880.im + cx.im * u_4833180880.re) AS im FROM cx, u_4833180880 WHERE cx.l=u_4833180880.i GROUP BY cx.i, cx.j, cx.k, u_4833180880.j
), K10 AS (
  SELECT K7.i AS i, K7.j AS j, SUM(K7.re * K1.re - K7.im * K1.im) AS re, SUM(K7.re * K1.im + K7.im * K1.re) AS im FROM K7, K1 WHERE K7.k=K1.i GROUP BY K7.i, K7.j
), K11 AS (
  SELECT cx.i AS i, cx.j AS j, cx.k AS k, SUM(K8.re * cx.re - K8.im * cx.im) AS re, SUM(K8.re * cx.im + K8.im * cx.re) AS im FROM K8, cx WHERE K8.i=cx.l GROUP BY cx.i, cx.j, cx.k
), K12 AS (
  SELECT K9.i AS i, K9.j AS j, K9.k AS k, SUM(K9.re * T0.re - K9.im * T0.im) AS re, SUM(K9.re * T0.im + K9.im * T0.re) AS im FROM K9, T0 WHERE K9.l=T0.i GROUP BY K9.i, K9.j, K9.k
), K13 AS (
  SELECT K5.i AS i, K5.j AS j, K5.k AS k, u_4833179984.j AS l, SUM(K5.re * u_4833179984.re - K5.im * u_4833179984.im) AS re, SUM(K5.re * u_4833179984.im + K5.im * u_4833179984.re) AS im FROM K5, u_4833179984 WHERE K5.l=u_4833179984.i GROUP BY K5.i, K5.j, K5.k, u_4833179984.j
), K14 AS (
  SELECT K13.i AS i, K13.j AS j, K13.k AS k, SUM(K13.re * T0.re - K13.im * T0.im) AS re, SUM(K13.re * T0.im + K13.im * T0.re) AS im FROM K13, T0 WHERE K13.l=T0.i GROUP BY K13.i, K13.j, K13.k
), K15 AS (
  SELECT u_4833180880.i AS i, cx.i AS j, cx.k AS k, cx.l AS l, SUM(u_4833180880.re * cx.re - u_4833180880.im * cx.im) AS re, SUM(u_4833180880.re * cx.im + u_4833180880.im * cx.re) AS im FROM u_4833180880, cx WHERE u_4833180880.j=cx.j GROUP BY u_4833180880.i, cx.i, cx.k, cx.l
), K16 AS (
  SELECT u_4833180880.i AS i, SUM(u_4833180880.re * T0.re - u_4833180880.im * T0.im) AS re, SUM(u_4833180880.re * T0.im + u_4833180880.im * T0.re) AS im FROM u_4833180880, T0 WHERE u_4833180880.j=T0.i GROUP BY u_4833180880.i
), K17 AS (
  SELECT cx.i AS i, cx.j AS j, cx.k AS k, u_4833179984.j AS l, SUM(cx.re * u_4833179984.re - cx.im * u_4833179984.im) AS re, SUM(cx.re * u_4833179984.im + cx.im * u_4833179984.re) AS im FROM cx, u_4833179984 WHERE cx.l=u_4833179984.i GROUP BY cx.i, cx.j, cx.k, u_4833179984.j
), K18 AS (
  SELECT K12.i AS i, K12.k AS j, u_4833179984.i AS k, SUM(K12.re * u_4833179984.re - K12.im * u_4833179984.im) AS re, SUM(K12.re * u_4833179984.im + K12.im * u_4833179984.re) AS im FROM K12, u_4833179984 WHERE K12.j=u_4833179984.j GROUP BY K12.i, K12.k, u_4833179984.i
), K19 AS (
  SELECT cx.i AS i, cx.j AS j, cx.k AS k, SUM(K16.re * cx.re - K16.im * cx.im) AS re, SUM(K16.re * cx.im + K16.im * cx.re) AS im FROM K16, cx WHERE K16.i=cx.l GROUP BY cx.i, cx.j, cx.k
), K20 AS (
  SELECT K18.i AS i, K18.k AS j, K10.j AS k, SUM(K18.re * K10.re - K18.im * K10.im) AS re, SUM(K18.re * K10.im + K18.im * K10.re) AS im FROM K18, K10 WHERE K18.j=K10.i GROUP BY K18.i, K18.k, K10.j
), K21 AS (
  SELECT K14.i AS i, K14.j AS j, u_4833986896.j AS k, SUM(K14.re * u_4833986896.re - K14.im * u_4833986896.im) AS re, SUM(K14.re * u_4833986896.im + K14.im * u_4833986896.re) AS im FROM K14, u_4833986896 WHERE K14.k=u_4833986896.i GROUP BY K14.i, K14.j, u_4833986896.j
), K22 AS (
  SELECT K19.i AS i, K19.k AS j, u_4833180880.i AS k, SUM(K19.re * u_4833180880.re - K19.im * u_4833180880.im) AS re, SUM(K19.re * u_4833180880.im + K19.im * u_4833180880.re) AS im FROM K19, u_4833180880 WHERE K19.j=u_4833180880.j GROUP BY K19.i, K19.k, u_4833180880.i
), K23 AS (
  SELECT u_4833180880.i AS i, SUM(u_4833180880.re * T0.re - u_4833180880.im * T0.im) AS re, SUM(u_4833180880.re * T0.im + u_4833180880.im * T0.re) AS im FROM u_4833180880, T0 WHERE u_4833180880.j=T0.i GROUP BY u_4833180880.i
), K24 AS (
  SELECT u_4833180880.i AS i, SUM(u_4833180880.re * T0.re - u_4833180880.im * T0.im) AS re, SUM(u_4833180880.re * T0.im + u_4833180880.im * T0.re) AS im FROM u_4833180880, T0 WHERE u_4833180880.j=T0.i GROUP BY u_4833180880.i
), K25 AS (
  SELECT K17.i AS i, K17.j AS j, K17.k AS k, SUM(K17.re * T0.re - K17.im * T0.im) AS re, SUM(K17.re * T0.im + K17.im * T0.re) AS im FROM K17, T0 WHERE K17.l=T0.i GROUP BY K17.i, K17.j, K17.k
), K26 AS (
  SELECT K22.i AS i, K22.k AS j, u_4833179984.j AS k, SUM(K22.re * u_4833179984.re - K22.im * u_4833179984.im) AS re, SUM(K22.re * u_4833179984.im + K22.im * u_4833179984.re) AS im FROM K22, u_4833179984 WHERE K22.j=u_4833179984.i GROUP BY K22.i, K22.k, u_4833179984.j
), K27 AS (
  SELECT K15.i AS i, K15.j AS j, K15.k AS k, SUM(K24.re * K15.re - K24.im * K15.im) AS re, SUM(K24.re * K15.im + K24.im * K15.re) AS im FROM K24, K15 WHERE K24.i=K15.l GROUP BY K15.i, K15.j, K15.k
), K28 AS (
  SELECT u_4833988304.i AS i, cx.i AS j, cx.k AS k, cx.l AS l, SUM(u_4833988304.re * cx.re - u_4833988304.im * cx.im) AS re, SUM(u_4833988304.re * cx.im + u_4833988304.im * cx.re) AS im FROM u_4833988304, cx WHERE u_4833988304.j=cx.j GROUP BY u_4833988304.i, cx.i, cx.k, cx.l
), K29 AS (
  SELECT cx.i AS i, cx.j AS j, cx.k AS k, SUM(K23.re * cx.re - K23.im * cx.im) AS re, SUM(K23.re * cx.im + K23.im * cx.re) AS im FROM K23, cx WHERE K23.i=cx.l GROUP BY cx.i, cx.j, cx.k
), K30 AS (
  SELECT K11.i AS i, K11.k AS j, u_4833180880.i AS k, SUM(K11.re * u_4833180880.re - K11.im * u_4833180880.im) AS re, SUM(K11.re * u_4833180880.im + K11.im * u_4833180880.re) AS im FROM K11, u_4833180880 WHERE K11.j=u_4833180880.j GROUP BY K11.i, K11.k, u_4833180880.i
), K31 AS (
  SELECT K6.i AS i, K6.k AS j, u_4833986896.i AS k, SUM(K6.re * u_4833986896.re - K6.im * u_4833986896.im) AS re, SUM(K6.re * u_4833986896.im + K6.im * u_4833986896.re) AS im FROM K6, u_4833986896 WHERE K6.j=u_4833986896.j GROUP BY K6.i, K6.k, u_4833986896.i
), K32 AS (
  SELECT K30.i AS i, K30.j AS j, K27.i AS k, K27.j AS l, SUM(K30.re * K27.re - K30.im * K27.im) AS re, SUM(K30.re * K27.im + K30.im * K27.re) AS im FROM K30, K27 WHERE K30.k=K27.k GROUP BY K30.i, K30.j, K27.i, K27.j
), K33 AS (
  SELECT K20.i AS i, K20.j AS j, u_4833988304.i AS k, SUM(K20.re * u_4833988304.re - K20.im * u_4833988304.im) AS re, SUM(K20.re * u_4833988304.im + K20.im * u_4833988304.re) AS im FROM K20, u_4833988304 WHERE K20.k=u_4833988304.j GROUP BY K20.i, K20.j, u_4833988304.i
), K34 AS (
  SELECT K33.i AS i, K33.k AS j, K25.i AS k, K25.j AS l, SUM(K33.re * K25.re - K33.im * K25.im) AS re, SUM(K33.re * K25.im + K33.im * K25.re) AS im FROM K33, K25 WHERE K33.j=K25.k GROUP BY K33.i, K33.k, K25.i, K25.j
), K35 AS (
  SELECT K31.i AS i, K31.j AS j, K29.i AS k, K29.j AS l, SUM(K31.re * K29.re - K31.im * K29.im) AS re, SUM(K31.re * K29.im + K31.im * K29.re) AS im FROM K31, K29 WHERE K31.k=K29.k GROUP BY K31.i, K31.j, K29.i, K29.j
), K36 AS (
  SELECT K28.i AS i, K28.j AS j, K28.l AS k, K21.j AS l, K21.k AS m, SUM(K28.re * K21.re - K28.im * K21.im) AS re, SUM(K28.re * K21.im + K28.im * K21.re) AS im FROM K28, K21 WHERE K28.k=K21.i GROUP BY K28.i, K28.j, K28.l, K21.j, K21.k
), K37 AS (
  SELECT K32.i AS i, K32.k AS j, K32.l AS k, K26.i AS l, K26.k AS m, SUM(K32.re * K26.re - K32.im * K26.im) AS re, SUM(K32.re * K26.im + K32.im * K26.re) AS im FROM K32, K26 WHERE K32.j=K26.j GROUP BY K32.i, K32.k, K32.l, K26.i, K26.k
), K38 AS (
  SELECT K37.i AS i, K37.k AS j, K37.l AS k, K37.m AS l, K35.i AS m, K35.k AS n, K35.l AS o, SUM(K37.re * K35.re - K37.im * K35.im) AS re, SUM(K37.re * K35.im + K37.im * K35.re) AS im FROM K37, K35 WHERE K37.j=K35.j GROUP BY K37.i, K37.k, K37.l, K37.m, K35.i, K35.k, K35.l
), K39 AS (
  SELECT K36.i AS i, K36.j AS j, K36.l AS k, K36.m AS l, K34.i AS m, K34.k AS n, K34.l AS o, SUM(K36.re * K34.re - K36.im * K34.im) AS re, SUM(K36.re * K34.im + K36.im * K34.re) AS im FROM K36, K34 WHERE K36.k=K34.j GROUP BY K36.i, K36.j, K36.l, K36.m, K34.i, K34.k, K34.l
) SELECT K39.m AS i, K39.n AS j, K38.k AS k, K38.i AS l, K38.j AS m, K38.m AS n, K38.n AS o, K39.k AS p, K39.j AS q, K39.i AS r, SUM(K39.re * K38.re - K39.im * K38.im) AS re, SUM(K39.re * K38.im + K39.im * K38.re) AS im FROM K39, K38 WHERE K39.l=K38.o AND K39.o=K38.l GROUP BY K39.m, K39.n, K38.k, K38.i, K38.j, K38.m, K38.n, K39.k, K39.j, K39.i ORDER BY i, j, k, l, m, n, o, p, q, r

