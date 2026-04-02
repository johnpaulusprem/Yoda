"""
Data access exceptions for the Agentic AI Component Library.

This module defines exceptions for database and document connector operations,
including connection failures, query errors, and data access violations.

Example:
    ```python
    from yoda_foundation.exceptions import (
        DatabaseConnectionError,
        QueryExecutionError,
        DocumentNotFoundError,
    )

    try:
        result = await connector.execute(query, security_context)
    except DatabaseConnectionError as e:
        logger.error(f"Database connection failed: {e.error_id}")
        raise
    ```
"""

from __future__ import annotations

from typing import Any

from yoda_foundation.exceptions.base import (
    AgenticBaseException,
    ErrorCategory,
    ErrorSeverity,
)


class DataAccessError(AgenticBaseException):
    """
    Base exception for all data access operations.

    Attributes:
        connector_type: Type of connector (sql, nosql, graph, document)
        operation: Operation being performed (connect, query, read, write)

    Example:
        ```python
        raise DataAccessError(
            message="Data access failed",
            connector_type="sql",
            operation="query",
        )
        ```
    """

    def __init__(
        self,
        message: str,
        *,
        connector_type: str | None = None,
        operation: str | None = None,
        cause: Exception | None = None,
        **kwargs: Any,
    ) -> None:
        """
        Initialize data access error.

        Args:
            message: Error description
            connector_type: Type of connector
            operation: Operation being performed
            cause: Original exception
            **kwargs: Additional error parameters
        """
        details = kwargs.pop("details", {})
        details["connector_type"] = connector_type
        details["operation"] = operation

        super().__init__(
            message=message,
            category=ErrorCategory.RESOURCE,
            severity=kwargs.pop("severity", ErrorSeverity.MEDIUM),
            retryable=kwargs.pop("retryable", False),
            cause=cause,
            details=details,
            **kwargs,
        )
        self.connector_type = connector_type
        self.operation = operation


class DatabaseConnectionError(DataAccessError):
    """
    Database connection failed.

    Raised when unable to establish or maintain a database connection.

    Attributes:
        host: Database host
        port: Database port
        database: Database name

    Example:
        ```python
        raise DatabaseConnectionError(
            message="Failed to connect to PostgreSQL",
            host="localhost",
            port=5432,
            database="mydb",
        )
        ```
    """

    def __init__(
        self,
        message: str,
        *,
        host: str | None = None,
        port: int | None = None,
        database: str | None = None,
        connector_type: str = "database",
        cause: Exception | None = None,
        **kwargs: Any,
    ) -> None:
        """
        Initialize database connection error.

        Args:
            message: Error description
            host: Database host
            port: Database port
            database: Database name
            connector_type: Type of database
            cause: Original exception
            **kwargs: Additional error parameters
        """
        details = kwargs.pop("details", {})
        details.update(
            {
                "host": host,
                "port": port,
                "database": database,
            }
        )

        super().__init__(
            message=message,
            connector_type=connector_type,
            operation="connect",
            severity=ErrorSeverity.HIGH,
            retryable=True,
            user_message="Unable to connect to database. Please try again.",
            suggestions=[
                "Check database host and port are correct",
                "Verify network connectivity",
                "Ensure database is running",
                "Check credentials are valid",
            ],
            cause=cause,
            details=details,
            **kwargs,
        )
        self.host = host
        self.port = port
        self.database = database


class QueryExecutionError(DataAccessError):
    """
    Query execution failed.

    Raised when a database query fails to execute.

    Attributes:
        query: The query that failed (sanitized)
        error_code: Database-specific error code

    Example:
        ```python
        raise QueryExecutionError(
            message="Syntax error in SQL query",
            query="SELECT * FROM users WHERE...",
            error_code="42601",
        )
        ```
    """

    def __init__(
        self,
        message: str,
        *,
        query: str | None = None,
        error_code: str | None = None,
        connector_type: str = "database",
        cause: Exception | None = None,
        **kwargs: Any,
    ) -> None:
        """
        Initialize query execution error.

        Args:
            message: Error description
            query: Query that failed (will be sanitized)
            error_code: Database error code
            connector_type: Type of database
            cause: Original exception
            **kwargs: Additional error parameters
        """
        details = kwargs.pop("details", {})
        details.update(
            {
                "query_preview": query[:200] if query else None,
                "error_code": error_code,
            }
        )

        super().__init__(
            message=message,
            connector_type=connector_type,
            operation="query",
            severity=ErrorSeverity.MEDIUM,
            retryable=False,
            user_message="Query execution failed. Please check your query.",
            suggestions=[
                "Verify query syntax",
                "Check table and column names",
                "Ensure proper permissions",
            ],
            cause=cause,
            details=details,
            **kwargs,
        )
        self.query = query
        self.error_code = error_code


class TransactionError(DataAccessError):
    """
    Database transaction failed.

    Raised when a transaction fails to commit or rollback.

    Example:
        ```python
        raise TransactionError(
            message="Transaction deadlock detected",
            transaction_id="tx_123",
        )
        ```
    """

    def __init__(
        self,
        message: str,
        *,
        transaction_id: str | None = None,
        connector_type: str = "database",
        cause: Exception | None = None,
        **kwargs: Any,
    ) -> None:
        """
        Initialize transaction error.

        Args:
            message: Error description
            transaction_id: Transaction identifier
            connector_type: Type of database
            cause: Original exception
            **kwargs: Additional error parameters
        """
        details = kwargs.pop("details", {})
        details["transaction_id"] = transaction_id

        super().__init__(
            message=message,
            connector_type=connector_type,
            operation="transaction",
            severity=ErrorSeverity.HIGH,
            retryable=True,
            user_message="Transaction failed. Please retry the operation.",
            suggestions=[
                "Retry the transaction",
                "Check for conflicting operations",
            ],
            cause=cause,
            details=details,
            **kwargs,
        )
        self.transaction_id = transaction_id


class ConnectionPoolError(DataAccessError):
    """
    Connection pool error.

    Raised when connection pool is exhausted or misconfigured.

    Example:
        ```python
        raise ConnectionPoolError(
            message="Connection pool exhausted",
            pool_size=10,
            active_connections=10,
        )
        ```
    """

    def __init__(
        self,
        message: str,
        *,
        pool_size: int | None = None,
        active_connections: int | None = None,
        connector_type: str = "database",
        cause: Exception | None = None,
        **kwargs: Any,
    ) -> None:
        """
        Initialize connection pool error.

        Args:
            message: Error description
            pool_size: Maximum pool size
            active_connections: Current active connections
            connector_type: Type of database
            cause: Original exception
            **kwargs: Additional error parameters
        """
        details = kwargs.pop("details", {})
        details.update(
            {
                "pool_size": pool_size,
                "active_connections": active_connections,
            }
        )

        super().__init__(
            message=message,
            connector_type=connector_type,
            operation="pool",
            severity=ErrorSeverity.HIGH,
            retryable=True,
            user_message="Database connection pool exhausted. Please try again.",
            suggestions=[
                "Retry after a short delay",
                "Increase connection pool size",
                "Check for connection leaks",
            ],
            cause=cause,
            details=details,
            **kwargs,
        )
        self.pool_size = pool_size
        self.active_connections = active_connections


class DocumentNotFoundError(DataAccessError):
    """
    Document not found in document store.

    Raised when a requested document does not exist.

    Attributes:
        document_id: Document identifier
        document_path: Document path

    Example:
        ```python
        raise DocumentNotFoundError(
            message="Document not found",
            document_id="doc_123",
            document_path="/folder/file.pdf",
        )
        ```
    """

    def __init__(
        self,
        message: str,
        *,
        document_id: str | None = None,
        document_path: str | None = None,
        connector_type: str = "document",
        cause: Exception | None = None,
        **kwargs: Any,
    ) -> None:
        """
        Initialize document not found error.

        Args:
            message: Error description
            document_id: Document identifier
            document_path: Document path
            connector_type: Type of document store
            cause: Original exception
            **kwargs: Additional error parameters
        """
        details = kwargs.pop("details", {})
        details.update(
            {
                "document_id": document_id,
                "document_path": document_path,
            }
        )

        super().__init__(
            message=message,
            connector_type=connector_type,
            operation="read",
            severity=ErrorSeverity.MEDIUM,
            retryable=False,
            user_message="Document not found.",
            suggestions=[
                "Verify document ID or path",
                "Check document still exists",
                "Verify access permissions",
            ],
            cause=cause,
            details=details,
            **kwargs,
        )
        self.document_id = document_id
        self.document_path = document_path


class DocumentAccessError(DataAccessError):
    """
    Document access failed.

    Raised when unable to read, write, or delete a document.

    Attributes:
        document_id: Document identifier
        access_type: Type of access attempted (read, write, delete)

    Example:
        ```python
        raise DocumentAccessError(
            message="Permission denied to access document",
            document_id="doc_123",
            access_type="write",
        )
        ```
    """

    def __init__(
        self,
        message: str,
        *,
        document_id: str | None = None,
        access_type: str | None = None,
        connector_type: str = "document",
        cause: Exception | None = None,
        **kwargs: Any,
    ) -> None:
        """
        Initialize document access error.

        Args:
            message: Error description
            document_id: Document identifier
            access_type: Type of access (read, write, delete)
            connector_type: Type of document store
            cause: Original exception
            **kwargs: Additional error parameters
        """
        details = kwargs.pop("details", {})
        details.update(
            {
                "document_id": document_id,
                "access_type": access_type,
            }
        )

        super().__init__(
            message=message,
            connector_type=connector_type,
            operation=access_type or "access",
            severity=ErrorSeverity.MEDIUM,
            retryable=False,
            user_message="Unable to access document.",
            suggestions=[
                "Verify you have permission to access this document",
                "Check document is not locked",
                "Contact administrator for access",
            ],
            cause=cause,
            details=details,
            **kwargs,
        )
        self.document_id = document_id
        self.access_type = access_type


class GraphTraversalError(DataAccessError):
    """
    Graph traversal failed.

    Raised when graph traversal or query execution fails.

    Attributes:
        query: Graph query (Cypher, Gremlin, etc.)
        query_type: Type of query language

    Example:
        ```python
        raise GraphTraversalError(
            message="Cypher query failed",
            query="MATCH (n:User) RETURN n",
            query_type="cypher",
        )
        ```
    """

    def __init__(
        self,
        message: str,
        *,
        query: str | None = None,
        query_type: str | None = None,
        connector_type: str = "graph",
        cause: Exception | None = None,
        **kwargs: Any,
    ) -> None:
        """
        Initialize graph traversal error.

        Args:
            message: Error description
            query: Graph query that failed
            query_type: Query language (cypher, gremlin)
            connector_type: Type of graph database
            cause: Original exception
            **kwargs: Additional error parameters
        """
        details = kwargs.pop("details", {})
        details.update(
            {
                "query_preview": query[:200] if query else None,
                "query_type": query_type,
            }
        )

        super().__init__(
            message=message,
            connector_type=connector_type,
            operation="traverse",
            severity=ErrorSeverity.MEDIUM,
            retryable=False,
            user_message="Graph query failed. Please check your query.",
            suggestions=[
                "Verify query syntax",
                "Check node and relationship names",
                "Ensure proper graph schema",
            ],
            cause=cause,
            details=details,
            **kwargs,
        )
        self.query = query
        self.query_type = query_type


class NoSQLError(DataAccessError):
    """
    NoSQL operation failed.

    Raised when NoSQL database operation fails.

    Attributes:
        collection: Collection/table name
        operation_type: Operation type (find, insert, update, delete)

    Example:
        ```python
        raise NoSQLError(
            message="Failed to insert document",
            collection="users",
            operation_type="insert",
        )
        ```
    """

    def __init__(
        self,
        message: str,
        *,
        collection: str | None = None,
        operation_type: str | None = None,
        connector_type: str = "nosql",
        cause: Exception | None = None,
        **kwargs: Any,
    ) -> None:
        """
        Initialize NoSQL error.

        Args:
            message: Error description
            collection: Collection name
            operation_type: Type of operation
            connector_type: Type of NoSQL database
            cause: Original exception
            **kwargs: Additional error parameters
        """
        details = kwargs.pop("details", {})
        details.update(
            {
                "collection": collection,
                "operation_type": operation_type,
            }
        )

        super().__init__(
            message=message,
            connector_type=connector_type,
            operation=operation_type or "query",
            severity=ErrorSeverity.MEDIUM,
            retryable=kwargs.pop("retryable", True),
            user_message="Database operation failed. Please try again.",
            suggestions=[
                "Verify collection exists",
                "Check document structure",
                "Retry the operation",
            ],
            cause=cause,
            details=details,
            **kwargs,
        )
        self.collection = collection
        self.operation_type = operation_type
