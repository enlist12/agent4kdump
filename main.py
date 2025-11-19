import argparse
import yaml  
from pathlib import Path
from log import *

main_log = get_logger("Main")

main_log.info("Starting kdump analysis tool...")

arg = argparse.ArgumentParser()
arg.add_argument('--config',type=str,required=True,help='the config file path')
args = arg.parse_args()

config_path = Path(args.config)
if not config_path.exists():
    raise FileNotFoundError(f"Config file {config_path} does not exist.")

with open(config_path, 'r') as file:
        config = yaml.safe_load(file)
        
linux = config.get('linux_path','./linux')
gdb = config.get('gdb_path','gdb')
vmcore = config.get('vmcore','./vmcore')
gdbserver = config.get('gdbserver','./gdbserver')
syzbotData = config.get('syzbot_data','./syzbot_data')

"""
Add comfirm code later
"""