from devtools import debug

from netspy.clients import CoreNLPClient


def test_corenlp_client() -> None:
    client = CoreNLPClient(port=5555)

    debug(client.port)

    assert client.port == 5555
