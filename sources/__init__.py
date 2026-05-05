"""Source transformer registry and imports."""

from .base import BaseSource
from .benevity import BenevitySource
from .cybergrants import CyberGrantsSource
from .yourcause import YourCauseSource
from .bright_funds import BrightFundsSource
from .fidelity import FidelitySource

SOURCE_REGISTRY = {
    "Benevity": BenevitySource,
    "CyberGrants": CyberGrantsSource,
    "YourCause": YourCauseSource,
    "Bright Funds": BrightFundsSource,
    "Fidelity Marketplace Giving": FidelitySource,
}
