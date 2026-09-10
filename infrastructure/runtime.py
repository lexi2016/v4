from dataclasses import dataclass
from ipaddress import ip_address


@dataclass(frozen=True)
class ServerConfig:
    host: str = "127.0.0.1"
    port: int = 8872

    def __post_init__(self) -> None:
        try:
            is_loopback = ip_address(self.host).is_loopback
        except ValueError as error:
            raise ValueError("server host must be a loopback address") from error
        if not is_loopback:
            raise ValueError("server host must be a loopback address")
        if not 1 <= self.port <= 65535:
            raise ValueError("server port must be between 1 and 65535")
