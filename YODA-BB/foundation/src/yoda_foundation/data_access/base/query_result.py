"""
Query result classes for the Agentic AI Component Library Data Access layer.

This module provides standardized result classes for database query operations,
including Row, ResultSet, and QueryResult for consistent handling of query
outputs across all database connectors.

Example:
    ```python
    from yoda_foundation.data_access.base import (
        Row,
        ResultSet,
        QueryResult,
    )

    # Create a result set from raw data
    rows = [
        {"id": 1, "name": "Alice", "email": "alice@example.com"},
        {"id": 2, "name": "Bob", "email": "bob@example.com"},
    ]
    result_set = ResultSet(rows)

    # Access data
    first_user = result_set.first()
    all_users = result_set.all()
    user_count = result_set.count

    # Convert to different formats
    user_dicts = result_set.to_dict()
    user_df = result_set.to_dataframe()

    # Full query result with metadata
    query_result = QueryResult(
        data=result_set,
        affected_rows=0,
        execution_time_ms=15.3,
        metadata={"query_type": "SELECT"},
    )
    ```
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import (
    Any,
    Generic,
    TypeVar,
    overload,
)

from yoda_foundation.exceptions import ValidationError


T = TypeVar("T", bound=dict[str, Any])


class Row:
    """
    Represents a single row from a database query result.

    Provides dictionary-like access with attribute-style access support
    for convenient data retrieval.

    Attributes:
        _data: Internal dictionary holding row data
        _columns: Ordered list of column names

    Example:
        ```python
        row = Row({"id": 1, "name": "Alice", "age": 30})

        # Dictionary-style access
        user_id = row["id"]

        # Attribute-style access
        user_name = row.name

        # Check if column exists
        if "email" in row:
            print(row["email"])

        # Get with default
        email = row.get("email", "N/A")

        # Convert to dict
        data = row.to_dict()
        ```

    Raises:
        KeyError: When accessing non-existent column via [] operator
        AttributeError: When accessing non-existent column via attribute
    """

    __slots__ = ("_columns", "_data")

    def __init__(
        self,
        data: dict[str, Any],
        columns: list[str] | None = None,
    ) -> None:
        """
        Initialize a Row from a dictionary.

        Args:
            data: Dictionary containing row data
            columns: Optional ordered list of column names

        Example:
            ```python
            # Basic usage
            row = Row({"id": 1, "name": "Alice"})

            # With explicit column order
            row = Row(
                {"name": "Alice", "id": 1},
                columns=["id", "name"]
            )
            ```
        """
        self._data: dict[str, Any] = data
        self._columns: list[str] = columns if columns is not None else list(data.keys())

    def __getitem__(self, key: str) -> Any:
        """
        Get value by column name using [] operator.

        Args:
            key: Column name

        Returns:
            Value at the specified column

        Raises:
            KeyError: If column does not exist
        """
        if key not in self._data:
            raise KeyError(f"Column '{key}' not found in row")
        return self._data[key]

    def __getattr__(self, name: str) -> Any:
        """
        Get value by column name using attribute access.

        Args:
            name: Column name

        Returns:
            Value at the specified column

        Raises:
            AttributeError: If column does not exist
        """
        if name.startswith("_"):
            raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'")
        try:
            return self._data[name]
        except KeyError:
            raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'")

    def __contains__(self, key: str) -> bool:
        """Check if column exists in row."""
        return key in self._data

    def __iter__(self) -> Iterator[str]:
        """Iterate over column names in order."""
        return iter(self._columns)

    def __len__(self) -> int:
        """Return number of columns."""
        return len(self._data)

    def __repr__(self) -> str:
        """Return string representation."""
        return f"Row({self._data!r})"

    def __eq__(self, other: object) -> bool:
        """Check equality with another Row or dict."""
        if isinstance(other, Row):
            return self._data == other._data
        if isinstance(other, dict):
            return self._data == other
        return NotImplemented

    def get(self, key: str, default: Any = None) -> Any:
        """
        Get value by column name with optional default.

        Args:
            key: Column name
            default: Default value if column not found

        Returns:
            Value at column or default

        Example:
            ```python
            email = row.get("email", "unknown@example.com")
            ```
        """
        return self._data.get(key, default)

    def keys(self) -> list[str]:
        """
        Return column names in order.

        Returns:
            List of column names
        """
        return self._columns.copy()

    def values(self) -> list[Any]:
        """
        Return values in column order.

        Returns:
            List of values
        """
        return [self._data[col] for col in self._columns]

    def items(self) -> list[tuple[str, Any]]:
        """
        Return column-value pairs in order.

        Returns:
            List of (column, value) tuples
        """
        return [(col, self._data[col]) for col in self._columns]

    def to_dict(self) -> dict[str, Any]:
        """
        Convert row to dictionary.

        Returns:
            Dictionary copy of the row data

        Example:
            ```python
            row_dict = row.to_dict()
            json_str = json.dumps(row_dict)
            ```
        """
        return self._data.copy()

    @property
    def columns(self) -> list[str]:
        """Return ordered list of column names."""
        return self._columns.copy()


class ResultSet(Generic[T]):
    """
    Represents a collection of rows from a database query.

    Provides iteration, indexing, and conversion methods for working
    with query results. Supports lazy iteration and batch processing.

    Attributes:
        _rows: Internal list of Row objects
        _columns: Ordered list of column names (from first row)

    Example:
        ```python
        # Create from list of dicts
        data = [
            {"id": 1, "name": "Alice"},
            {"id": 2, "name": "Bob"},
        ]
        result_set = ResultSet(data)

        # Iteration
        for row in result_set:
            print(row.name)

        # Indexing
        first = result_set[0]
        last_two = result_set[-2:]

        # Properties
        print(f"Count: {result_set.count}")
        print(f"Empty: {result_set.is_empty}")

        # Access methods
        first_row = result_set.first()
        all_rows = result_set.all()

        # Conversion
        dict_list = result_set.to_dict()
        dataframe = result_set.to_dataframe()
        ```

    Raises:
        IndexError: When accessing out-of-range index
    """

    __slots__ = ("_columns", "_raw_data", "_rows")

    def __init__(
        self,
        rows: Sequence[dict[str, Any]] | None = None,
        columns: list[str] | None = None,
    ) -> None:
        """
        Initialize ResultSet from a sequence of dictionaries.

        Args:
            rows: Sequence of dictionaries representing rows
            columns: Optional column ordering (inferred from first row if not provided)

        Example:
            ```python
            # From query results
            raw_results = await conn.fetch_all(query)
            result_set = ResultSet(raw_results)

            # With explicit columns
            result_set = ResultSet(
                raw_results,
                columns=["id", "name", "created_at"]
            )
            ```
        """
        self._raw_data: list[dict[str, Any]] = list(rows) if rows else []

        # Determine columns from first row if not provided
        if columns is not None:
            self._columns: list[str] = columns
        elif self._raw_data:
            self._columns = list(self._raw_data[0].keys())
        else:
            self._columns = []

        # Create Row objects
        self._rows: list[Row] = [Row(data, columns=self._columns) for data in self._raw_data]

    @overload
    def __getitem__(self, index: int) -> Row: ...

    @overload
    def __getitem__(self, index: slice) -> list[Row]: ...

    def __getitem__(self, index: int | slice) -> Row | list[Row]:
        """
        Get row(s) by index or slice.

        Args:
            index: Integer index or slice

        Returns:
            Single Row or list of Rows

        Raises:
            IndexError: If index is out of range
        """
        return self._rows[index]

    def __iter__(self) -> Iterator[Row]:
        """Iterate over rows."""
        return iter(self._rows)

    def __len__(self) -> int:
        """Return number of rows."""
        return len(self._rows)

    def __bool__(self) -> bool:
        """Return True if result set is not empty."""
        return len(self._rows) > 0

    def __repr__(self) -> str:
        """Return string representation."""
        return f"ResultSet(count={len(self._rows)}, columns={self._columns})"

    @property
    def count(self) -> int:
        """
        Return the number of rows in the result set.

        Returns:
            Number of rows

        Example:
            ```python
            if result_set.count > 0:
                process_results(result_set)
            ```
        """
        return len(self._rows)

    @property
    def is_empty(self) -> bool:
        """
        Check if the result set is empty.

        Returns:
            True if no rows, False otherwise
        """
        return len(self._rows) == 0

    @property
    def columns(self) -> list[str]:
        """
        Return ordered list of column names.

        Returns:
            List of column names
        """
        return self._columns.copy()

    def first(self) -> Row | None:
        """
        Return the first row, or None if empty.

        Returns:
            First Row or None

        Example:
            ```python
            user = result_set.first()
            if user:
                print(f"Found user: {user.name}")
            ```
        """
        if self._rows:
            return self._rows[0]
        return None

    def first_or_raise(self, message: str = "No results found") -> Row:
        """
        Return the first row, or raise if empty.

        Args:
            message: Error message if no results

        Returns:
            First Row

        Raises:
            ValidationError: If result set is empty

        Example:
            ```python
            user = result_set.first_or_raise("User not found")
            ```
        """
        if not self._rows:
            raise ValidationError(
                message=message,
                user_message="The requested data was not found.",
                suggestions=["Verify the query parameters", "Check if the record exists"],
            )
        return self._rows[0]

    def last(self) -> Row | None:
        """
        Return the last row, or None if empty.

        Returns:
            Last Row or None
        """
        if self._rows:
            return self._rows[-1]
        return None

    def all(self) -> list[Row]:
        """
        Return all rows as a list.

        Returns:
            List of all Row objects

        Example:
            ```python
            for row in result_set.all():
                process_row(row)
            ```
        """
        return self._rows.copy()

    def to_dict(self) -> list[dict[str, Any]]:
        """
        Convert result set to list of dictionaries.

        Returns:
            List of dictionaries, one per row

        Example:
            ```python
            data = result_set.to_dict()
            json_response = json.dumps(data)
            ```
        """
        return [row.to_dict() for row in self._rows]

    def to_dataframe(self) -> Any:
        """
        Convert result set to pandas DataFrame.

        Returns:
            pandas DataFrame

        Raises:
            ImportError: If pandas is not installed

        Example:
            ```python
            df = result_set.to_dataframe()
            df.to_csv("output.csv")

            # Analysis with pandas
            avg_age = df["age"].mean()
            ```

        Note:
            Requires pandas to be installed. Install with:
            pip install pandas
        """
        try:
            import pandas as pd

            if not self._rows:
                return pd.DataFrame(columns=self._columns)

            return pd.DataFrame(self._raw_data, columns=self._columns)

        except ImportError as e:
            raise ImportError(
                "pandas is required for DataFrame conversion. Install with: pip install pandas"
            ) from e

    def column_values(self, column: str) -> list[Any]:
        """
        Extract all values for a specific column.

        Args:
            column: Column name

        Returns:
            List of values for the column

        Raises:
            KeyError: If column does not exist

        Example:
            ```python
            user_ids = result_set.column_values("id")
            emails = result_set.column_values("email")
            ```
        """
        if self._rows and column not in self._rows[0]:
            raise KeyError(f"Column '{column}' not found in result set")
        return [row.get(column) for row in self._rows]

    def filter(
        self,
        predicate: Any,  # Callable[[Row], bool] - using Any to avoid import issues
    ) -> ResultSet[T]:
        """
        Filter rows based on a predicate function.

        Args:
            predicate: Function that takes a Row and returns bool

        Returns:
            New ResultSet with filtered rows

        Example:
            ```python
            # Filter active users
            active = result_set.filter(lambda row: row.get("active", False))

            # Filter by age
            adults = result_set.filter(lambda row: row.get("age", 0) >= 18)
            ```
        """
        filtered_data = [row.to_dict() for row in self._rows if predicate(row)]
        return ResultSet(filtered_data, columns=self._columns)

    def map(
        self,
        transform: Any,  # Callable[[Row], Dict[str, Any]]
    ) -> ResultSet[T]:
        """
        Transform each row using a mapping function.

        Args:
            transform: Function that takes a Row and returns a dict

        Returns:
            New ResultSet with transformed rows

        Example:
            ```python
            # Add computed field
            def add_full_name(row):
                data = row.to_dict()
                data["full_name"] = f"{row.get('first_name')} {row.get('last_name')}"
                return data

            enhanced = result_set.map(add_full_name)
            ```
        """
        transformed_data = [transform(row) for row in self._rows]
        return ResultSet(transformed_data)

    def group_by(self, column: str) -> dict[Any, ResultSet[T]]:
        """
        Group rows by a column value.

        Args:
            column: Column to group by

        Returns:
            Dictionary mapping column values to ResultSets

        Example:
            ```python
            # Group users by department
            by_dept = result_set.group_by("department")
            for dept, users in by_dept.items():
                print(f"{dept}: {users.count} users")
            ```
        """
        groups: dict[Any, list[dict[str, Any]]] = {}
        for row in self._rows:
            key = row.get(column)
            if key not in groups:
                groups[key] = []
            groups[key].append(row.to_dict())

        return {key: ResultSet(rows, columns=self._columns) for key, rows in groups.items()}

    def unique(self, column: str) -> list[Any]:
        """
        Get unique values for a column.

        Args:
            column: Column name

        Returns:
            List of unique values (preserves order of first occurrence)

        Example:
            ```python
            departments = result_set.unique("department")
            ```
        """
        seen: set[Any] = set()
        result: list[Any] = []
        for row in self._rows:
            value = row.get(column)
            if value not in seen:
                seen.add(value)
                result.append(value)
        return result


@dataclass
class QueryResult:
    """
    Complete result of a database query including data and metadata.

    Encapsulates the result set along with execution metrics and
    additional metadata from the query operation.

    Attributes:
        data: ResultSet containing the query results
        affected_rows: Number of rows affected (for INSERT/UPDATE/DELETE)
        execution_time_ms: Query execution time in milliseconds
        metadata: Additional query metadata
        query_id: Unique identifier for the query execution
        timestamp: When the query was executed

    Example:
        ```python
        # Create from connector result
        result = QueryResult(
            data=ResultSet(raw_rows),
            affected_rows=0,
            execution_time_ms=12.5,
            metadata={
                "query_type": "SELECT",
                "table": "users",
                "cached": False,
            },
        )

        # Access data
        for row in result.data:
            print(row.name)

        # Check performance
        if result.execution_time_ms > 1000:
            logger.warning(f"Slow query: {result.query_id}")

        # Get summary
        summary = result.to_dict()
        ```

    Raises:
        ValidationError: If data is not a valid ResultSet
    """

    data: ResultSet[Any]
    affected_rows: int = 0
    execution_time_ms: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)
    query_id: str | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        """Validate and set defaults after initialization."""
        import uuid

        if self.query_id is None:
            self.query_id = uuid.uuid4().hex[:12]

    @property
    def row_count(self) -> int:
        """
        Return number of rows in the result set.

        Returns:
            Number of rows
        """
        return self.data.count

    @property
    def is_empty(self) -> bool:
        """
        Check if result set is empty.

        Returns:
            True if no rows returned
        """
        return self.data.is_empty

    @property
    def columns(self) -> list[str]:
        """
        Return column names from result set.

        Returns:
            List of column names
        """
        return self.data.columns

    def to_dict(self) -> dict[str, Any]:
        """
        Convert query result to dictionary for serialization.

        Returns:
            Dictionary with all result data and metadata

        Example:
            ```python
            result_dict = query_result.to_dict()
            json_response = json.dumps(result_dict)
            ```
        """
        return {
            "query_id": self.query_id,
            "row_count": self.row_count,
            "affected_rows": self.affected_rows,
            "execution_time_ms": self.execution_time_ms,
            "timestamp": self.timestamp.isoformat(),
            "columns": self.columns,
            "data": self.data.to_dict(),
            "metadata": self.metadata,
        }

    def to_summary_dict(self) -> dict[str, Any]:
        """
        Convert to summary dictionary without row data.

        Useful for logging and metrics without including potentially
        large or sensitive row data.

        Returns:
            Dictionary with summary information

        Example:
            ```python
            logger.info(
                "Query completed",
                extra=query_result.to_summary_dict()
            )
            ```
        """
        return {
            "query_id": self.query_id,
            "row_count": self.row_count,
            "affected_rows": self.affected_rows,
            "execution_time_ms": self.execution_time_ms,
            "timestamp": self.timestamp.isoformat(),
            "columns": self.columns,
            "metadata": self.metadata,
        }

    @classmethod
    def empty(
        cls,
        columns: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> QueryResult:
        """
        Create an empty query result.

        Args:
            columns: Optional column names
            metadata: Optional metadata

        Returns:
            Empty QueryResult

        Example:
            ```python
            # Return empty result when no data found
            if not rows:
                return QueryResult.empty(columns=["id", "name"])
            ```
        """
        return cls(
            data=ResultSet([], columns=columns or []),
            affected_rows=0,
            execution_time_ms=0.0,
            metadata=metadata or {},
        )

    @classmethod
    def from_rows(
        cls,
        rows: list[dict[str, Any]],
        execution_time_ms: float = 0.0,
        metadata: dict[str, Any] | None = None,
    ) -> QueryResult:
        """
        Create query result from a list of row dictionaries.

        Args:
            rows: List of dictionaries representing rows
            execution_time_ms: Query execution time
            metadata: Optional query metadata

        Returns:
            QueryResult with the provided data

        Example:
            ```python
            rows = [{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}]
            result = QueryResult.from_rows(
                rows,
                execution_time_ms=15.3,
                metadata={"query_type": "SELECT"},
            )
            ```
        """
        return cls(
            data=ResultSet(rows),
            affected_rows=0,
            execution_time_ms=execution_time_ms,
            metadata=metadata or {},
        )

    @classmethod
    def from_affected_rows(
        cls,
        affected_rows: int,
        execution_time_ms: float = 0.0,
        metadata: dict[str, Any] | None = None,
    ) -> QueryResult:
        """
        Create query result for write operations.

        Args:
            affected_rows: Number of rows affected
            execution_time_ms: Query execution time
            metadata: Optional query metadata

        Returns:
            QueryResult for write operation

        Example:
            ```python
            # After INSERT/UPDATE/DELETE
            result = QueryResult.from_affected_rows(
                affected_rows=5,
                execution_time_ms=23.1,
                metadata={"operation": "UPDATE", "table": "users"},
            )
            ```
        """
        return cls(
            data=ResultSet([]),
            affected_rows=affected_rows,
            execution_time_ms=execution_time_ms,
            metadata=metadata or {},
        )
