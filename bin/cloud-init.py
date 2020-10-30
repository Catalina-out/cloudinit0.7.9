#!/usr/bin/python
# EASY-INSTALL-ENTRY-SCRIPT: 'cloud-init==0.7.9','console_scripts','cloud-init'
__requires__ = 'cloud-init==0.7.9'
import sys
from pkg_resources import load_entry_point

if __name__ == '__main__':
    sys.exit(
        load_entry_point('cloud-init==0.7.9', 'console_scripts', 'cloud-init')()
    )
