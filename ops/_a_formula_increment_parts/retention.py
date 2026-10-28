"""ops.a_formula_increment: retention (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __retention_hash_table_body(_v4_scope, /, frame, columns):
    """Build a compact sorted key/row-hash table for large seed frames.

    The seeds are multi-gigabyte parquet inputs.  A Python dict of every cell
    would multiply their memory footprint, so retention is checked with
    pandas' stable row hash and a three-column key table instead.
    """

    selected = _v4_global(_v4_scope, 'list')(columns)
    missing = [column for column in selected if column not in frame.columns]
    if missing:
        raise _v4_global(_v4_scope, 'AuthorityError')(f"logical row digest missing columns: {','.join(missing)}")
    row_hashes = _v4_global(_v4_scope, 'pd').util.hash_pandas_object(
        frame.loc[:, selected],
        index=False,
        categorize=False,
    ).to_numpy(dtype="uint64", copy=False)
    table = frame.loc[:, _v4_global(_v4_scope, 'list')(_v4_global(_v4_scope, 'KEY_COLUMNS'))].copy()
    table["_retention_hash"] = _v4_global(_v4_scope, 'pd').array(row_hashes, dtype="UInt64")
    return table.sort_values(_v4_global(_v4_scope, 'list')(_v4_global(_v4_scope, 'KEY_COLUMNS')), kind="mergesort").reset_index(drop=True)


def __align_retention_hash_frames_body(_v4_scope, /, current, combined, columns):
    """Normalize only dtype-promoted columns before hashing two frames.

    ``pd.concat`` may promote a historical integer column to float or a
    string extension column to object when the new increment is appended.  A
    value-preserving common dtype prevents that representation change from
    looking like a historical edit while still retaining changed numeric or
    textual values for comparison.
    """

    left = current.copy(deep=False)
    right = combined.copy(deep=False)
    for column in columns:
        left_dtype = current[column].dtype
        right_dtype = combined[column].dtype
        if left_dtype == right_dtype:
            continue
        left_numeric = _v4_global(_v4_scope, 'pd').api.types.is_numeric_dtype(left_dtype)
        right_numeric = _v4_global(_v4_scope, 'pd').api.types.is_numeric_dtype(right_dtype)
        if left_numeric and right_numeric:
            left[column] = _v4_global(_v4_scope, 'pd').to_numeric(current[column], errors="coerce").astype("float64")
            right[column] = _v4_global(_v4_scope, 'pd').to_numeric(combined[column], errors="coerce").astype("float64")
            continue
        left_datetime = _v4_global(_v4_scope, 'pd').api.types.is_datetime64_any_dtype(left_dtype)
        right_datetime = _v4_global(_v4_scope, 'pd').api.types.is_datetime64_any_dtype(right_dtype)
        if left_datetime and right_datetime:
            left[column] = _v4_global(_v4_scope, 'pd').to_datetime(current[column], errors="coerce")
            right[column] = _v4_global(_v4_scope, 'pd').to_datetime(combined[column], errors="coerce")
            continue
        # String/object columns are compared by their textual values, with
        # all pandas missing sentinels represented by the same nullable value.
        left[column] = current[column].astype("string")
        right[column] = combined[column].astype("string")
    return left, right
