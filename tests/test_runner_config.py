import pytest

from infrastructure.runtime import ServerConfig


def test_default_server_configuration_uses_loopback_and_port_8872() -> None:
    assert ServerConfig() == ServerConfig(host="127.0.0.1", port=8872)


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.8", "example.test"])
def test_non_loopback_runner_configuration_is_rejected(host: str) -> None:
    with pytest.raises(ValueError, match="loopback"):
        ServerConfig(host=host)
