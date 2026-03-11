from abc import abstractmethod
from core.util.models import ConnectionParams

import getpass



class DataConnector:
    """
    Wrapper encapsulating connections from json input
    """

    def __init__(self, connections: dict) -> None:
        self.__connections = connections

    @abstractmethod
    def build_db_config_dict(self):
        pass