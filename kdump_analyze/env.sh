#!/bin/zsh

KDUMP=/root/agent4kdump/kdump_analyze

LD_LIBRARY_PATH=$KDUMP/libkdumpfile/src/addrxlat/.libs:$LD_LIBRARY_PATH
LD_LIBRARY_PATH=$KDUMP/libkdumpfile/src/kdumpfile/.libs:$LD_LIBRARY_PATH