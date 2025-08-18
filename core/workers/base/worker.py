from abc import ABC, abstractmethod
from pathlib import Path

class Worker(ABC):
    """
    Abstract base class for workers.
    """

    def __init__(self, inputs: dict | None = None, data_connector: DataConnector | None = None *args, **kwargs):
        """
        Initialize the worker with the given arguments.
        """
        pass

    @abstractmethod
    def run(self, *args, **kwargs):
        """
        Run the worker with the given arguments.
        """
        pass

    @abstractmethod
    def get_output_path(self) -> Path:
        """
        Get the output path for the worker.
        """
        pass

    @abstractmethod
    def get_output(self):
        """
        Get the output of the worker.
        """
        pass