import os
import getpass
from typing import Dict, Any, Optional
from functools import partial
from langchain_core.tools import BaseTool
from langchain_core.runnables.config import RunnableConfig

from abc import ABC, abstractmethod
from langfuse.langchain import CallbackHandler
from abc import ABC
from langfuse import Langfuse
import os
from langchain.chat_models import init_chat_model
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))

langfuse = Langfuse(
  secret_key=os.environ['LANGFUSE_SECRET_KEY'],
  public_key=os.environ['LANGFUSE_PUBLIC_KEY'],
  host=os.environ['LANGFUSE_BASE_URL']
)

MAX_RECURSION_DEPTH = 100


def get_model(
    provider_name: str,
    model_name: Optional[str],
    url: Optional[str],
    key: Optional[str],
) -> Any:
    return init_chat_model(
        model=model_name, model_provider=provider_name, api_key=key, base_url=url
    )

