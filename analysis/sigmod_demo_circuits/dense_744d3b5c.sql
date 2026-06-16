-- InferQ demo circuit (dense)
-- circuit hash: 744d3b5c1982008dc9f7cb547f8823f1e3ae1938bce989245ae61a0052b2b18e
-- Dense: an 11-qubit circuit with the most gates and ~38% two-qubit gates. Largest query and fully dense 11-qubit statevector (2048 amplitudes).
-- qubits: 11 | gates: 61 | two-qubit gates: 23 | nonzero amplitudes: 2048
-- SQL CTEs: 76 (contraction: 70) | size: 19513 bytes
-- DuckDB runtime: ~0.166s on a laptop
-- Result columns: one 0/1 column per qubit (basis state) + re, im (complex amplitude).
-- Portable across DuckDB, SQLite and PostgreSQL.

WITH T0(i, re, im) AS (
  VALUES (CAST(0 AS INTEGER), CAST(1.0 AS DOUBLE PRECISION), CAST(0.0 AS DOUBLE PRECISION))
), u_4833180880(i,j, re, im) AS (
  VALUES (CAST(0 AS INTEGER), CAST(0 AS INTEGER), CAST(0.7071067811865474 AS DOUBLE PRECISION), CAST(0.0 AS DOUBLE PRECISION)), (0, 1, 0.7071067811865477, 1.9707065560440798e-15), 
  (1, 0, -0.7070231147624026, 0.010877278688651973), (1, 1, 0.7070231147624023, -0.010877278688649997)
), u_4833588688(i,j, re, im) AS (
  VALUES (CAST(0 AS INTEGER), CAST(0 AS INTEGER), CAST(0.7071067811865478 AS DOUBLE PRECISION), CAST(0.0 AS DOUBLE PRECISION)), (0, 1, 0.7071067811865472, 8.659560562354929e-17), 
  (1, 0, 0.33386096498900897, -0.6233272463614978), (1, 1, -0.3338609649890093, 0.6233272463614982)
), cx(i,j,k,l, re, im) AS (
  VALUES (CAST(0 AS INTEGER), CAST(0 AS INTEGER), CAST(0 AS INTEGER), CAST(0 AS INTEGER), CAST(1.0 AS DOUBLE PRECISION), CAST(0.0 AS DOUBLE PRECISION)), 
  (0, 1, 1, 1, 1.0, 0.0), 
  (1, 0, 1, 0, 1.0, 0.0), 
  (1, 1, 0, 1, 1.0, 0.0)
), u_4833987920(i,j, re, im) AS (
  VALUES (CAST(0 AS INTEGER), CAST(0 AS INTEGER), CAST(0.7312703432788029 AS DOUBLE PRECISION), CAST(0.0 AS DOUBLE PRECISION)), (0, 1, 0.6472316002659714, 0.21525552410577417), 
  (1, 0, 0.06566269915378266, 0.6789198001095134), (1, 1, 0.16290498093648453, -0.712894299419754)
), x(i,j, re, im) AS (
  VALUES (CAST(0 AS INTEGER), CAST(1 AS INTEGER), CAST(1.0 AS DOUBLE PRECISION), CAST(0.0 AS DOUBLE PRECISION)), 
  (1, 0, 1.0, 0.0)
), K1 AS (
  SELECT cx.i AS i, cx.j AS j, cx.l AS k, u_4833180880.j AS l, SUM(cx.re * u_4833180880.re - cx.im * u_4833180880.im) AS re, SUM(cx.re * u_4833180880.im + cx.im * u_4833180880.re) AS im FROM cx, u_4833180880 WHERE cx.k=u_4833180880.i GROUP BY cx.i, cx.j, cx.l, u_4833180880.j
), K2 AS (
  SELECT cx.i AS i, cx.j AS j, cx.l AS k, u_4833588688.j AS l, SUM(cx.re * u_4833588688.re - cx.im * u_4833588688.im) AS re, SUM(cx.re * u_4833588688.im + cx.im * u_4833588688.re) AS im FROM cx, u_4833588688 WHERE cx.k=u_4833588688.i GROUP BY cx.i, cx.j, cx.l, u_4833588688.j
), K3 AS (
  SELECT u_4833588688.i AS i, SUM(u_4833588688.re * T0.re - u_4833588688.im * T0.im) AS re, SUM(u_4833588688.re * T0.im + u_4833588688.im * T0.re) AS im FROM u_4833588688, T0 WHERE u_4833588688.j=T0.i GROUP BY u_4833588688.i
), K4 AS (
  SELECT cx.i AS i, cx.j AS j, cx.k AS k, u_4833588688.j AS l, SUM(cx.re * u_4833588688.re - cx.im * u_4833588688.im) AS re, SUM(cx.re * u_4833588688.im + cx.im * u_4833588688.re) AS im FROM cx, u_4833588688 WHERE cx.l=u_4833588688.i GROUP BY cx.i, cx.j, cx.k, u_4833588688.j
), K5 AS (
  SELECT cx.i AS i, cx.j AS j, cx.k AS k, SUM(K3.re * cx.re - K3.im * cx.im) AS re, SUM(K3.re * cx.im + K3.im * cx.re) AS im FROM K3, cx WHERE K3.i=cx.l GROUP BY cx.i, cx.j, cx.k
), K6 AS (
  SELECT K1.i AS i, K1.j AS j, K1.k AS k, SUM(K1.re * T0.re - K1.im * T0.im) AS re, SUM(K1.re * T0.im + K1.im * T0.re) AS im FROM K1, T0 WHERE K1.l=T0.i GROUP BY K1.i, K1.j, K1.k
), K7 AS (
  SELECT cx.i AS i, cx.j AS j, cx.k AS k, u_4833987920.j AS l, SUM(cx.re * u_4833987920.re - cx.im * u_4833987920.im) AS re, SUM(cx.re * u_4833987920.im + cx.im * u_4833987920.re) AS im FROM cx, u_4833987920 WHERE cx.l=u_4833987920.i GROUP BY cx.i, cx.j, cx.k, u_4833987920.j
), K8 AS (
  SELECT u_4833588688.i AS i, T1.j AS j, SUM(u_4833588688.re * T1.re - u_4833588688.im * T1.im) AS re, SUM(u_4833588688.re * T1.im + u_4833588688.im * T1.re) AS im FROM u_4833588688, u_4833588688 T1 WHERE u_4833588688.j=T1.i GROUP BY u_4833588688.i, T1.j
), K9 AS (
  SELECT K6.i AS i, K6.k AS j, u_4833588688.i AS k, SUM(K6.re * u_4833588688.re - K6.im * u_4833588688.im) AS re, SUM(K6.re * u_4833588688.im + K6.im * u_4833588688.re) AS im FROM K6, u_4833588688 WHERE K6.j=u_4833588688.j GROUP BY K6.i, K6.k, u_4833588688.i
), K10 AS (
  SELECT u_4833180880.i AS i, SUM(u_4833180880.re * T0.re - u_4833180880.im * T0.im) AS re, SUM(u_4833180880.re * T0.im + u_4833180880.im * T0.re) AS im FROM u_4833180880, T0 WHERE u_4833180880.j=T0.i GROUP BY u_4833180880.i
), K11 AS (
  SELECT K9.j AS i, K9.k AS j, u_4833180880.i AS k, SUM(K9.re * u_4833180880.re - K9.im * u_4833180880.im) AS re, SUM(K9.re * u_4833180880.im + K9.im * u_4833180880.re) AS im FROM K9, u_4833180880 WHERE K9.i=u_4833180880.j GROUP BY K9.j, K9.k, u_4833180880.i
), K12 AS (
  SELECT K11.j AS i, K11.k AS j, SUM(K11.re * K10.re - K11.im * K10.im) AS re, SUM(K11.re * K10.im + K11.im * K10.re) AS im FROM K11, K10 WHERE K11.i=K10.i GROUP BY K11.j, K11.k
), K13 AS (
  SELECT u_4833588688.i AS i, T1.j AS j, SUM(u_4833588688.re * T1.re - u_4833588688.im * T1.im) AS re, SUM(u_4833588688.re * T1.im + u_4833588688.im * T1.re) AS im FROM u_4833588688, u_4833588688 T1 WHERE u_4833588688.j=T1.i GROUP BY u_4833588688.i, T1.j
), K14 AS (
  SELECT cx.i AS i, cx.j AS j, SUM(K12.re * cx.re - K12.im * cx.im) AS re, SUM(K12.re * cx.im + K12.im * cx.re) AS im FROM K12, cx WHERE K12.i=cx.l AND K12.j=cx.k GROUP BY cx.i, cx.j
), K15 AS (
  SELECT K8.j AS i, cx.i AS j, cx.j AS k, cx.k AS l, SUM(K8.re * cx.re - K8.im * cx.im) AS re, SUM(K8.re * cx.im + K8.im * cx.re) AS im FROM K8, cx WHERE K8.i=cx.l GROUP BY K8.j, cx.i, cx.j, cx.k
), K16 AS (
  SELECT K2.i AS i, K2.j AS j, K2.l AS k, u_4833588688.j AS l, SUM(K2.re * u_4833588688.re - K2.im * u_4833588688.im) AS re, SUM(K2.re * u_4833588688.im + K2.im * u_4833588688.re) AS im FROM K2, u_4833588688 WHERE K2.k=u_4833588688.i GROUP BY K2.i, K2.j, K2.l, u_4833588688.j
), K17 AS (
  SELECT K16.i AS i, K16.j AS j, K16.k AS k, SUM(K16.re * T0.re - K16.im * T0.im) AS re, SUM(K16.re * T0.im + K16.im * T0.re) AS im FROM K16, T0 WHERE K16.l=T0.i GROUP BY K16.i, K16.j, K16.k
), K18 AS (
  SELECT u_4833588688.i AS i, cx.i AS j, cx.k AS k, cx.l AS l, SUM(u_4833588688.re * cx.re - u_4833588688.im * cx.im) AS re, SUM(u_4833588688.re * cx.im + u_4833588688.im * cx.re) AS im FROM u_4833588688, cx WHERE u_4833588688.j=cx.j GROUP BY u_4833588688.i, cx.i, cx.k, cx.l
), K19 AS (
  SELECT K7.i AS i, K7.j AS j, K7.k AS k, SUM(K7.re * T0.re - K7.im * T0.im) AS re, SUM(K7.re * T0.im + K7.im * T0.re) AS im FROM K7, T0 WHERE K7.l=T0.i GROUP BY K7.i, K7.j, K7.k
), K20 AS (
  SELECT u_4833588688.i AS i, cx.i AS j, cx.k AS k, cx.l AS l, SUM(u_4833588688.re * cx.re - u_4833588688.im * cx.im) AS re, SUM(u_4833588688.re * cx.im + u_4833588688.im * cx.re) AS im FROM u_4833588688, cx WHERE u_4833588688.j=cx.j GROUP BY u_4833588688.i, cx.i, cx.k, cx.l
), K21 AS (
  SELECT K19.i AS i, K19.j AS j, u_4833588688.j AS k, SUM(K19.re * u_4833588688.re - K19.im * u_4833588688.im) AS re, SUM(K19.re * u_4833588688.im + K19.im * u_4833588688.re) AS im FROM K19, u_4833588688 WHERE K19.k=u_4833588688.i GROUP BY K19.i, K19.j, u_4833588688.j
), K22 AS (
  SELECT u_4833987920.i AS i, SUM(u_4833987920.re * T0.re - u_4833987920.im * T0.im) AS re, SUM(u_4833987920.re * T0.im + u_4833987920.im * T0.re) AS im FROM u_4833987920, T0 WHERE u_4833987920.j=T0.i GROUP BY u_4833987920.i
), K23 AS (
  SELECT K13.j AS i, cx.i AS j, cx.j AS k, cx.k AS l, SUM(K13.re * cx.re - K13.im * cx.im) AS re, SUM(K13.re * cx.im + K13.im * cx.re) AS im FROM K13, cx WHERE K13.i=cx.l GROUP BY K13.j, cx.i, cx.j, cx.k
), K24 AS (
  SELECT cx.i AS i, cx.j AS j, cx.k AS k, u_4833180880.j AS l, SUM(cx.re * u_4833180880.re - cx.im * u_4833180880.im) AS re, SUM(cx.re * u_4833180880.im + cx.im * u_4833180880.re) AS im FROM cx, u_4833180880 WHERE cx.l=u_4833180880.i GROUP BY cx.i, cx.j, cx.k, u_4833180880.j
), K25 AS (
  SELECT cx.i AS i, cx.j AS j, cx.l AS k, x.j AS l, SUM(cx.re * x.re - cx.im * x.im) AS re, SUM(cx.re * x.im + cx.im * x.re) AS im FROM cx, x WHERE cx.k=x.i GROUP BY cx.i, cx.j, cx.l, x.j
), K26 AS (
  SELECT K25.i AS i, K25.j AS j, K25.k AS k, SUM(K25.re * T0.re - K25.im * T0.im) AS re, SUM(K25.re * T0.im + K25.im * T0.re) AS im FROM K25, T0 WHERE K25.l=T0.i GROUP BY K25.i, K25.j, K25.k
), K27 AS (
  SELECT u_4833588688.i AS i, SUM(u_4833588688.re * T0.re - u_4833588688.im * T0.im) AS re, SUM(u_4833588688.re * T0.im + u_4833588688.im * T0.re) AS im FROM u_4833588688, T0 WHERE u_4833588688.j=T0.i GROUP BY u_4833588688.i
), K28 AS (
  SELECT cx.i AS i, cx.j AS j, cx.k AS k, SUM(K22.re * cx.re - K22.im * cx.im) AS re, SUM(K22.re * cx.im + K22.im * cx.re) AS im FROM K22, cx WHERE K22.i=cx.l GROUP BY cx.i, cx.j, cx.k
), K29 AS (
  SELECT K23.i AS i, K23.j AS j, K23.k AS k, u_4833588688.j AS l, SUM(K23.re * u_4833588688.re - K23.im * u_4833588688.im) AS re, SUM(K23.re * u_4833588688.im + K23.im * u_4833588688.re) AS im FROM K23, u_4833588688 WHERE K23.l=u_4833588688.i GROUP BY K23.i, K23.j, K23.k, u_4833588688.j
), K30 AS (
  SELECT u_4833987920.i AS i, SUM(u_4833987920.re * T0.re - u_4833987920.im * T0.im) AS re, SUM(u_4833987920.re * T0.im + u_4833987920.im * T0.re) AS im FROM u_4833987920, T0 WHERE u_4833987920.j=T0.i GROUP BY u_4833987920.i
), K31 AS (
  SELECT K24.i AS i, K24.j AS j, K24.l AS k, SUM(K27.re * K24.re - K27.im * K24.im) AS re, SUM(K27.re * K24.im + K27.im * K24.re) AS im FROM K27, K24 WHERE K27.i=K24.k GROUP BY K24.i, K24.j, K24.l
), K32 AS (
  SELECT cx.i AS i, cx.j AS j, cx.k AS k, SUM(K30.re * cx.re - K30.im * cx.im) AS re, SUM(K30.re * cx.im + K30.im * cx.re) AS im FROM K30, cx WHERE K30.i=cx.l GROUP BY cx.i, cx.j, cx.k
), K33 AS (
  SELECT K21.i AS i, K21.k AS j, u_4833588688.i AS k, SUM(K21.re * u_4833588688.re - K21.im * u_4833588688.im) AS re, SUM(K21.re * u_4833588688.im + K21.im * u_4833588688.re) AS im FROM K21, u_4833588688 WHERE K21.j=u_4833588688.j GROUP BY K21.i, K21.k, u_4833588688.i
), K34 AS (
  SELECT K31.j AS i, K31.k AS j, u_4833180880.i AS k, SUM(K31.re * u_4833180880.re - K31.im * u_4833180880.im) AS re, SUM(K31.re * u_4833180880.im + K31.im * u_4833180880.re) AS im FROM K31, u_4833180880 WHERE K31.i=u_4833180880.j GROUP BY K31.j, K31.k, u_4833180880.i
), K35 AS (
  SELECT K26.i AS i, K26.j AS j, u_4833987920.j AS k, SUM(K26.re * u_4833987920.re - K26.im * u_4833987920.im) AS re, SUM(K26.re * u_4833987920.im + K26.im * u_4833987920.re) AS im FROM K26, u_4833987920 WHERE K26.k=u_4833987920.i GROUP BY K26.i, K26.j, u_4833987920.j
), K36 AS (
  SELECT cx.i AS i, cx.j AS j, cx.k AS k, u_4833180880.j AS l, SUM(cx.re * u_4833180880.re - cx.im * u_4833180880.im) AS re, SUM(cx.re * u_4833180880.im + cx.im * u_4833180880.re) AS im FROM cx, u_4833180880 WHERE cx.l=u_4833180880.i GROUP BY cx.i, cx.j, cx.k, u_4833180880.j
), K37 AS (
  SELECT K5.i AS i, K5.j AS j, u_4833588688.j AS k, SUM(K5.re * u_4833588688.re - K5.im * u_4833588688.im) AS re, SUM(K5.re * u_4833588688.im + K5.im * u_4833588688.re) AS im FROM K5, u_4833588688 WHERE K5.k=u_4833588688.i GROUP BY K5.i, K5.j, u_4833588688.j
), K38 AS (
  SELECT K36.i AS i, K36.j AS j, K4.k AS k, K4.l AS l, SUM(K36.re * K4.re - K36.im * K4.im) AS re, SUM(K36.re * K4.im + K36.im * K4.re) AS im FROM K36, K4 WHERE K36.k=K4.i AND K36.l=K4.j GROUP BY K36.i, K36.j, K4.k, K4.l
), K39 AS (
  SELECT K35.i AS i, K35.j AS j, SUM(K35.re * T0.re - K35.im * T0.im) AS re, SUM(K35.re * T0.im + K35.im * T0.re) AS im FROM K35, T0 WHERE K35.k=T0.i GROUP BY K35.i, K35.j
), K40 AS (
  SELECT K32.i AS i, K32.j AS j, u_4833588688.j AS k, SUM(K32.re * u_4833588688.re - K32.im * u_4833588688.im) AS re, SUM(K32.re * u_4833588688.im + K32.im * u_4833588688.re) AS im FROM K32, u_4833588688 WHERE K32.k=u_4833588688.i GROUP BY K32.i, K32.j, u_4833588688.j
), K41 AS (
  SELECT u_4833987920.i AS i, u_4833180880.j AS j, SUM(u_4833987920.re * u_4833180880.re - u_4833987920.im * u_4833180880.im) AS re, SUM(u_4833987920.re * u_4833180880.im + u_4833987920.im * u_4833180880.re) AS im FROM u_4833987920, u_4833180880 WHERE u_4833987920.j=u_4833180880.i GROUP BY u_4833987920.i, u_4833180880.j
), K42 AS (
  SELECT K41.j AS i, K20.i AS j, K20.j AS k, K20.k AS l, SUM(K41.re * K20.re - K41.im * K20.im) AS re, SUM(K41.re * K20.im + K41.im * K20.re) AS im FROM K41, K20 WHERE K41.i=K20.l GROUP BY K41.j, K20.i, K20.j, K20.k
), K43 AS (
  SELECT K38.i AS i, K38.j AS j, K38.l AS k, u_4833180880.j AS l, SUM(K38.re * u_4833180880.re - K38.im * u_4833180880.im) AS re, SUM(K38.re * u_4833180880.im + K38.im * u_4833180880.re) AS im FROM K38, u_4833180880 WHERE K38.k=u_4833180880.i GROUP BY K38.i, K38.j, K38.l, u_4833180880.j
), K44 AS (
  SELECT K15.i AS i, K15.j AS j, K15.l AS k, u_4833588688.i AS l, SUM(K15.re * u_4833588688.re - K15.im * u_4833588688.im) AS re, SUM(K15.re * u_4833588688.im + K15.im * u_4833588688.re) AS im FROM K15, u_4833588688 WHERE K15.k=u_4833588688.j GROUP BY K15.i, K15.j, K15.l, u_4833588688.i
), K45 AS (
  SELECT K39.i AS i, K37.i AS j, K37.j AS k, SUM(K39.re * K37.re - K39.im * K37.im) AS re, SUM(K39.re * K37.im + K39.im * K37.re) AS im FROM K39, K37 WHERE K39.j=K37.k GROUP BY K39.i, K37.i, K37.j
), K46 AS (
  SELECT K45.k AS i, cx.i AS j, cx.j AS k, SUM(K45.re * cx.re - K45.im * cx.im) AS re, SUM(K45.re * cx.im + K45.im * cx.re) AS im FROM K45, cx WHERE K45.i=cx.l AND K45.j=cx.k GROUP BY K45.k, cx.i, cx.j
), K47 AS (
  SELECT K43.i AS i, K43.j AS j, K43.l AS k, K14.j AS l, SUM(K43.re * K14.re - K43.im * K14.im) AS re, SUM(K43.re * K14.im + K43.im * K14.re) AS im FROM K43, K14 WHERE K43.k=K14.i GROUP BY K43.i, K43.j, K43.l, K14.j
), K48 AS (
  SELECT K34.j AS i, K34.k AS j, u_4833987920.i AS k, SUM(K34.re * u_4833987920.re - K34.im * u_4833987920.im) AS re, SUM(K34.re * u_4833987920.im + K34.im * u_4833987920.re) AS im FROM K34, u_4833987920 WHERE K34.i=u_4833987920.j GROUP BY K34.j, K34.k, u_4833987920.i
), K49 AS (
  SELECT K48.i AS i, cx.i AS j, cx.j AS k, SUM(K48.re * cx.re - K48.im * cx.im) AS re, SUM(K48.re * cx.im + K48.im * cx.re) AS im FROM K48, cx WHERE K48.j=cx.k AND K48.k=cx.l GROUP BY K48.i, cx.i, cx.j
), K50 AS (
  SELECT K29.i AS i, K29.j AS j, K29.l AS k, u_4833588688.i AS l, SUM(K29.re * u_4833588688.re - K29.im * u_4833588688.im) AS re, SUM(K29.re * u_4833588688.im + K29.im * u_4833588688.re) AS im FROM K29, u_4833588688 WHERE K29.k=u_4833588688.j GROUP BY K29.i, K29.j, K29.l, u_4833588688.i
), K51 AS (
  SELECT K18.i AS i, K18.j AS j, K18.k AS k, u_4833588688.j AS l, SUM(K18.re * u_4833588688.re - K18.im * u_4833588688.im) AS re, SUM(K18.re * u_4833588688.im + K18.im * u_4833588688.re) AS im FROM K18, u_4833588688 WHERE K18.l=u_4833588688.i GROUP BY K18.i, K18.j, K18.k, u_4833588688.j
), K52 AS (
  SELECT K33.i AS i, K33.k AS j, K17.i AS k, K17.k AS l, SUM(K33.re * K17.re - K33.im * K17.im) AS re, SUM(K33.re * K17.im + K33.im * K17.re) AS im FROM K33, K17 WHERE K33.j=K17.j GROUP BY K33.i, K33.k, K17.i, K17.k
), K53 AS (
  SELECT K46.j AS i, K46.k AS j, K40.i AS k, K40.j AS l, SUM(K46.re * K40.re - K46.im * K40.im) AS re, SUM(K46.re * K40.im + K46.im * K40.re) AS im FROM K46, K40 WHERE K46.i=K40.k GROUP BY K46.j, K46.k, K40.i, K40.j
), K54 AS (
  SELECT K51.i AS i, K51.j AS j, K51.k AS k, SUM(K51.re * T0.re - K51.im * T0.im) AS re, SUM(K51.re * T0.im + K51.im * T0.re) AS im FROM K51, T0 WHERE K51.l=T0.i GROUP BY K51.i, K51.j, K51.k
), K55 AS (
  SELECT K28.j AS i, K28.k AS j, cx.i AS k, cx.j AS l, cx.l AS m, SUM(K28.re * cx.re - K28.im * cx.im) AS re, SUM(K28.re * cx.im + K28.im * cx.re) AS im FROM K28, cx WHERE K28.i=cx.k GROUP BY K28.j, K28.k, cx.i, cx.j, cx.l
), K56 AS (
  SELECT K49.k AS i, K47.i AS j, K47.j AS k, SUM(K49.re * K47.re - K49.im * K47.im) AS re, SUM(K49.re * K47.im + K49.im * K47.re) AS im FROM K49, K47 WHERE K49.i=K47.l AND K49.j=K47.k GROUP BY K49.k, K47.i, K47.j
), K57 AS (
  SELECT K53.j AS i, K53.l AS j, cx.i AS k, cx.j AS l, SUM(K53.re * cx.re - K53.im * cx.im) AS re, SUM(K53.re * cx.im + K53.im * cx.re) AS im FROM K53, cx WHERE K53.i=cx.l AND K53.k=cx.k GROUP BY K53.j, K53.l, cx.i, cx.j
), K58 AS (
  SELECT K56.i AS i, K56.j AS j, K44.j AS k, K44.k AS l, K44.l AS m, SUM(K56.re * K44.re - K56.im * K44.im) AS re, SUM(K56.re * K44.im + K56.im * K44.re) AS im FROM K56, K44 WHERE K56.k=K44.i GROUP BY K56.i, K56.j, K44.j, K44.k, K44.l
), K59 AS (
  SELECT K58.i AS i, K58.k AS j, K58.m AS k, K42.k AS l, K42.l AS m, SUM(K58.re * K42.re - K58.im * K42.im) AS re, SUM(K58.re * K42.im + K58.im * K42.re) AS im FROM K58, K42 WHERE K58.j=K42.i AND K58.l=K42.j GROUP BY K58.i, K58.k, K58.m, K42.k, K42.l
), K60 AS (
  SELECT K59.j AS i, K59.k AS j, K59.l AS k, K50.j AS l, K50.k AS m, SUM(K59.re * K50.re - K59.im * K50.im) AS re, SUM(K59.re * K50.im + K59.im * K50.re) AS im FROM K59, K50 WHERE K59.i=K50.i AND K59.m=K50.l GROUP BY K59.j, K59.k, K59.l, K50.j, K50.k
), K61 AS (
  SELECT K54.i AS i, K54.k AS j, cx.i AS k, cx.j AS l, cx.l AS m, SUM(K54.re * cx.re - K54.im * cx.im) AS re, SUM(K54.re * cx.im + K54.im * cx.re) AS im FROM K54, cx WHERE K54.j=cx.k GROUP BY K54.i, K54.k, cx.i, cx.j, cx.l
), K62 AS (
  SELECT K61.j AS i, K61.l AS j, K61.m AS k, K55.i AS l, K55.k AS m, K55.l AS n, SUM(K61.re * K55.re - K61.im * K55.im) AS re, SUM(K61.re * K55.im + K61.im * K55.re) AS im FROM K61, K55 WHERE K61.i=K55.j AND K61.k=K55.m GROUP BY K61.j, K61.l, K61.m, K55.i, K55.k, K55.l
), K63 AS (
  SELECT cx.i AS i, cx.j AS j, cx.k AS k, T1.j AS l, T1.k AS m, T1.l AS n, SUM(cx.re * T1.re - cx.im * T1.im) AS re, SUM(cx.re * T1.im + cx.im * T1.re) AS im FROM cx, cx T1 WHERE cx.l=T1.i GROUP BY cx.i, cx.j, cx.k, T1.j, T1.k, T1.l
), K64 AS (
  SELECT K52.j AS i, K52.k AS j, K52.l AS k, cx.i AS l, cx.j AS m, cx.l AS n, SUM(K52.re * cx.re - K52.im * cx.im) AS re, SUM(K52.re * cx.im + K52.im * cx.re) AS im FROM K52, cx WHERE K52.i=cx.k GROUP BY K52.j, K52.k, K52.l, cx.i, cx.j, cx.l
), K65 AS (
  SELECT K64.i AS i, K64.k AS j, K64.l AS k, K64.m AS l, cx.j AS m, cx.l AS n, SUM(K64.re * cx.re - K64.im * cx.im) AS re, SUM(K64.re * cx.im + K64.im * cx.re) AS im FROM K64, cx WHERE K64.j=cx.k AND K64.n=cx.i GROUP BY K64.i, K64.k, K64.l, K64.m, cx.j, cx.l
), K66 AS (
  SELECT K65.i AS i, K65.k AS j, K65.l AS k, K65.m AS l, K57.i AS m, K57.l AS n, SUM(K65.re * K57.re - K65.im * K57.im) AS re, SUM(K65.re * K57.im + K65.im * K57.re) AS im FROM K65, K57 WHERE K65.j=K57.j AND K65.n=K57.k GROUP BY K65.i, K65.k, K65.l, K65.m, K57.i, K57.l
), K67 AS (
  SELECT K63.i AS i, K63.j AS j, K63.l AS k, K63.n AS l, K60.k AS m, K60.l AS n, K60.m AS o, SUM(K63.re * K60.re - K63.im * K60.im) AS re, SUM(K63.re * K60.im + K63.im * K60.re) AS im FROM K63, K60 WHERE K63.k=K60.j AND K63.m=K60.i GROUP BY K63.i, K63.j, K63.l, K63.n, K60.k, K60.l, K60.m
), K68 AS (
  SELECT K67.i AS i, K67.j AS j, K67.k AS k, K67.n AS l, K67.o AS m, cx.j AS n, cx.l AS o, SUM(K67.re * cx.re - K67.im * cx.im) AS re, SUM(K67.re * cx.im + K67.im * cx.re) AS im FROM K67, cx WHERE K67.l=cx.i AND K67.m=cx.k GROUP BY K67.i, K67.j, K67.k, K67.n, K67.o, cx.j, cx.l
), K69 AS (
  SELECT K68.i AS i, K68.j AS j, K68.k AS k, K68.m AS l, K68.n AS m, cx.j AS n, cx.l AS o, SUM(K68.re * cx.re - K68.im * cx.im) AS re, SUM(K68.re * cx.im + K68.im * cx.re) AS im FROM K68, cx WHERE K68.l=cx.k AND K68.o=cx.i GROUP BY K68.i, K68.j, K68.k, K68.m, K68.n, cx.j, cx.l
), K70 AS (
  SELECT K66.k AS i, K66.l AS j, K66.m AS k, K66.n AS l, K62.j AS m, K62.l AS n, K62.m AS o, K62.n AS p, SUM(K66.re * K62.re - K66.im * K62.im) AS re, SUM(K66.re * K62.im + K66.im * K62.re) AS im FROM K66, K62 WHERE K66.i=K62.i AND K66.j=K62.k GROUP BY K66.k, K66.l, K66.m, K66.n, K62.j, K62.l, K62.m, K62.n
) SELECT K69.i AS i, K69.j AS j, K69.k AS k, K69.m AS l, K69.n AS m, K70.p AS n, K70.m AS o, K70.i AS p, K70.j AS q, K70.l AS r, K70.k AS s, SUM(K70.re * K69.re - K70.im * K69.im) AS re, SUM(K70.re * K69.im + K70.im * K69.re) AS im FROM K70, K69 WHERE K70.n=K69.l AND K70.o=K69.o GROUP BY K69.i, K69.j, K69.k, K69.m, K69.n, K70.p, K70.m, K70.i, K70.j, K70.l, K70.k ORDER BY i, j, k, l, m, n, o, p, q, r, s

