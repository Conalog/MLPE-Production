from abc import ABC, abstractmethod
from typing import Any

class TestCase(ABC):
    """
    Base class for all test cases.
    Implementations should define the `run` method.
    """
    @abstractmethod
    def run(self, args: dict[str, Any]) -> dict[str, Any]:
        """
        Execute the test case.
        Args:
            args: A dictionary containing necessary data for the test.
        Returns:
            A dictionary with 'code' (int) and 'log' (str).
        """
        pass
