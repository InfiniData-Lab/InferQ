"""
SQL Database utilities for quantum circuit metadata (backward compatibility).

This module provides SQL Database functionality for legacy support.
New projects should use table_storage.py instead.
"""

import logging
from pyodbc import Connection
from .azure_connection import sql_safe

# Configure logging
logger = logging.getLogger(__name__)

def create_circuits_table(conn: Connection, feature_dict: dict[str, str]) -> bool:
    """
    Ensure dbo.circuits exists and contains (at least) the columns mentioned in
    feature_list. The primary-key column 'qpy_sha256' CHAR(64) is created
    automatically if missing.
    """
    base_cols = {
        "qpy_sha256": "CHAR(64) NOT NULL PRIMARY KEY",
        "blob_path": "NVARCHAR(260) NULL",  # path or URL to the .qpy
    }

    cursor = conn.cursor()

    # 1A. Create table skeleton if absent
    if_not_exists = """
    IF NOT EXISTS (SELECT 1 FROM sys.tables WHERE name = 'circuits' AND schema_id = SCHEMA_ID('dbo'))
    BEGIN
        CREATE TABLE dbo.circuits (
            qpy_sha256 CHAR(64) NOT NULL PRIMARY KEY,
            blob_path    NVARCHAR(260) NULL
        );
    END;
    """
    cursor.execute(if_not_exists)

    # 1B. Fetch existing columns so we don't re-add them
    cursor.execute("""
        SELECT name
        FROM sys.columns
        WHERE object_id = OBJECT_ID('dbo.circuits');
    """)
    existing_cols = {row[0].lower() for row in cursor.fetchall()}

    # 1C. Add any missing feature columns (default FLOAT NULL)
    for feat, type in feature_dict.items():
        col_name = sql_safe(feat).strip("[]")
        type = type.upper()  # for existence check only
        if col_name.lower() not in existing_cols:
            alter = f"ALTER TABLE dbo.circuits ADD {sql_safe(col_name)} {type} NULL;"
            cursor.execute(alter)

    conn.commit()
    return True

def save_circuit_metadata(conn: Connection, features: dict[str, any]) -> bool:
    """
    Insert or update one row in dbo.circuits. features must include:
        * 'qpy_sha256'  – 64-char hex SHA-256 of the circuit blob
        * any/all feature columns and optional 'blob_path'
    All keys are converted to SQL-safe identifiers; unknown columns will
    raise (→ call create_circuits_table first when you add features).
    """
    if "qpy_sha256" not in features:
        raise ValueError("'features' dict must contain 'qpy_sha256'")

    keys, values = zip(*features.items())  # deterministic order
    columns = ", ".join(sql_safe(k) for k in keys)
    placeholders = ", ".join("?" for _ in keys)

    # First check if the record exists
    cursor = conn.cursor()
    check_query = "SELECT 1 FROM dbo.circuits WHERE qpy_sha256 = ?"
    cursor.execute(check_query, [features["qpy_sha256"]])
    record_exists = cursor.fetchone() is not None

    if record_exists:
        # Update existing record
        set_clauses = ", ".join(f"{sql_safe(k)} = ?" for k in keys if k != "qpy_sha256")
        update_values = [values[i] for i, k in enumerate(keys) if k != "qpy_sha256"]
        update_query = f"UPDATE dbo.circuits SET {set_clauses} WHERE qpy_sha256 = ?"
        update_values.append(features["qpy_sha256"])
        cursor.execute(update_query, update_values)
    else:
        # Insert new record
        insert_query = f"INSERT INTO dbo.circuits ({columns}) VALUES ({placeholders})"
        cursor.execute(insert_query, list(values))

    conn.commit()
    return True