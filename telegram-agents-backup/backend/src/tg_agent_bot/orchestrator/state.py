
from __future__ import annotations

from typing import Any


Workflow = dict[str, Any]
WorkflowMap = dict[str, Workflow]
ChatContext = dict[int, list[dict[str, Any]]]
