from typing import Optional


class PyTonLibException(Exception):
    """Base class for exceptions in the PyTONLib library."""

    message = "An error occurred in the PyTONLib library"

    def __init__(self, message: Optional[str] = None):
        super().__init__(message or self.message)


class SmartContractIsNotJettonOrNft(PyTonLibException):
    """Raised when the smart contract is not a Jetton or NFT."""

    message = "Smart contract is not a Jetton or NFT"
