# log_config.py
import logging
from colorama import Fore, Style, init

init(autoreset=True)
# need to change TODO
class ColorFormatter(logging.Formatter):
    def format(self, record):
        msg = super().format(record)
        if record.levelno == logging.INFO:
            return Fore.GREEN + msg + Style.RESET_ALL
        elif record.levelno == logging.ERROR:
            return Fore.RED + msg + Style.RESET_ALL
        elif record.levelno == logging.WARNING:
            return Fore.YELLOW + msg + Style.RESET_ALL
        return msg

def get_logger(name: str, level=logging.INFO):
    logger = logging.getLogger(name)
    logger.setLevel(level)
    
    if not logger.hasHandlers():
        handler = logging.StreamHandler()
        formatter = ColorFormatter("%(levelname)s - %(name)s - %(message)s")
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.propagate = False  

    return logger
