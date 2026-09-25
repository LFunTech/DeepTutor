"""ASGI entrypoint for enterprise Kubernetes runtime deployments.

The protected runtime image keeps the upstream-neutral ``deeptutor.api.main``
available for ordinary installs, while enterprise deployments mount a
deployment contract at ``DEEPTUTOR_POSTGRES_CONFIG``.  Uvicorn imports this
module only on that enterprise path so EduPlus2 and the scoped enterprise
routers are composed by the extension package instead of by core code.
"""

from __future__ import annotations

import os

from .bootstrap import create_application
from .configuration import DeploymentConfig

CONFIG_ENV = "DEEPTUTOR_POSTGRES_CONFIG"
DEFAULT_CONFIG_PATH = "/etc/deeptutor/deployment.json"


def _config_path() -> str:
    return os.environ.get(CONFIG_ENV, "").strip() or DEFAULT_CONFIG_PATH


app = create_application(DeploymentConfig.from_file(_config_path()))
