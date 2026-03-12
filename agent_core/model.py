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
from dotenv import load_dotenv,find_dotenv

load_dotenv(find_dotenv())

langfuse = Langfuse(
  secret_key=os.environ['LANGFUSE_SECRET_KEY'],
  public_key=os.environ['LANGFUSE_PUBLIC_KEY'],
  host=os.environ['LANGFUSE_HOST']
)

model_name = os.environ.get("MODEL_NAME", "gpt-5-chat-latest")
provider_name = os.environ.get("MODEL_PROVIDER", "openai")
key = os.environ.get("API_KEY", None)
url = os.environ.get("LLM_BASE_URL", None)

MAX_RECURSION_DEPTH = 100


def get_model() -> Any:
    return init_chat_model(
        model=model_name, model_provider=provider_name, api_key=key, base_url=url
    )

