"""Base interface for all parsers in the Massachusetts Legislature compliance
tracker.
"""

from abc import ABC, abstractmethod
from typing import Optional, Any, Dict
from components.models import BillAtHearing


class ParserInterface(ABC):
    """Base interface that all parsers must implement."""

    def __init__(self, output_controller=None):
        """Initialize parser with optional output controller.

        Args:
            output_controller: OutputController instance for structured output
        """
        self.output = output_controller

    @abstractmethod
    def discover(
        self, base_url: str, row: BillAtHearing
    ) -> Optional[Dict[str, Any]]:
        """Discover potential documents for parsing.

        Args:
            base_url: Base URL for the legislature website
            row: BillAtHearing object containing bill information

        Returns:
            Dictionary with document information if found, None otherwise
        """

    @abstractmethod
    def parse(
        self, base_url: str, candidate: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Parse the discovered document.

        Args:
            base_url: Base URL for the legislature website
            candidate: Dictionary with document information from discover()

        Returns:
            Dictionary with parsed document data
        """

    def _warning(self, message: str, **kwargs):
        """Emit a warning message using the output controller if available.

        Args:
            message: Warning message
            **kwargs: Additional data for the warning
        """
        if self.output:
            self.output.parser_warning(
                self.__class__.__name__, message, **kwargs
            )
        else:
            print(f"Warning: {message}")

    def _debug(self, bill_id: str, message: str, **kwargs):
        """Emit a debug message using the output controller if available.

        Args:
            bill_id: Bill ID for context
            message: Debug message
            **kwargs: Additional data for the debug message
        """
        if self.output:
            self.output.parser_debug(bill_id, message, **kwargs)
        else:
            print(f"DEBUG: {message}")

    def _error(self, message: str, **kwargs):
        """Emit an error message using the output controller if available.

        Args:
            message: Error message
            **kwargs: Additional data for the error
        """
        if self.output:
            self.output.error("parser", "error", message, **kwargs)
        else:
            print(f"Error: {message}")
