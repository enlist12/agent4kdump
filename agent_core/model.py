import os
import getpass
from typing import Dict, Any, Optional
from functools import partial
from langchain_openai import ChatOpenAI
from langchain_ollama import ChatOllama
from langchain_deepseek import ChatDeepSeek
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_anthropic import ChatAnthropic
from langchain_core.tools import BaseTool
from langchain_core.runnables.config import RunnableConfig

from abc import ABC, abstractmethod
from langfuse.langchain import CallbackHandler
from abc import ABC
from langfuse import Langfuse
import os
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))

langfuse = Langfuse(
  secret_key=os.environ['LANGFUSE_SECRET_KEY'],
  public_key=os.environ['LANGFUSE_PUBLIC_KEY'],
  host=os.environ['LANGFUSE_BASE_URL']
)

MAX_RECURSION_DEPTH = 100


SUPPORTED_MODELS = {
    "openai": {
        "name": "OpenAI",
        "default_model": "gpt-4o",
        "key_env_name": "OPENAI_API_KEY",
        "constructor": partial(ChatOpenAI, temperature=0, verbose=True),
    },
    "deepseek": {
        "name": "DeepSeek",
        "default_model": "deepseek-chat",
        "key_env_name": "DEEPSEEK_API_KEY",
        "constructor": partial(ChatDeepSeek, temperature=0, verbose=True),
    },
    "qwen": {
        "name": "Qwen",
        "default_model": "modelscope.cn/Qwen/Qwen2.5-32B-Instruct-GGUF:Q8_0",
        "key_env_name": "OLLAMA_API_KEY",
        "constructor": partial(ChatOllama, temperature=0, verbose=True),
    },
    "gemini": {
        "name": "Gemini",                                     
        "default_model": "gemini-2.5-preview-05-06",
        "key_env_name": "GOOGLE_API_KEY",
        "constructor": partial(ChatGoogleGenerativeAI, temperature=0, verbose=True),
    },
    "claude": {
        "name": "Claude",
        "default_model": "claude-4-5-sonnet-202509029",
        "key_env_name": "ANTHROPIC_API_KEY",
        "constructor": partial(ChatAnthropic, temperature=0, verbose=True),
    },
}

def get_model(
        provider_name: Optional[str]=None,
        model_name: Optional[str]=None,
        url: Optional[str]=None,
        key: Optional[str]=None) -> Any:
    
    # Load from environment if not provided
    if provider_name is None:
        provider_name = os.environ.get("LLM_PROVIDER", "openai")
    
    if model_name is None:
        model_name = os.environ.get("LLM_MODEL_NAME")
        
    if url is None:
        url = os.environ.get("LLM_BASE_URL")

    try:
        provider = SUPPORTED_MODELS[provider_name]
    except KeyError:
        raise ValueError(f"Unsupported model provider: {provider_name}")

    if not provider["key_env_name"] in os.environ.keys():
        if key is not None:
            os.environ[provider["key_env_name"]] = key
        else:
            # Try to get from generic env var if specific one is missing?
            # Or just prompt user.
            api_key = getpass.getpass(prompt=f"Please enter your {provider['name']} API key: ")
            os.environ[provider["key_env_name"]] = api_key

    if model_name is None:
        model_name = provider["default_model"]

    if url is not None:
        return provider["constructor"](base_url=url, model=model_name)
    else:
        return provider["constructor"](model=model_name)

