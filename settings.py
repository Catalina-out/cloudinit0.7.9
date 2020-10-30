# Copyright (C) 2012 Canonical Ltd.
# Copyright (C) 2012 Hewlett-Packard Development Company, L.P.
# Copyright (C) 2012 Yahoo! Inc.
#
# Author: Scott Moser <scott.moser@canonical.com>
# Author: Juerg Haefliger <juerg.haefliger@hp.com>
# Author: Joshua Harlow <harlowja@yahoo-inc.com>
#
# This file is part of cloud-init. See LICENSE file for license information.

# Set and read for determining the cloud config file location
CFG_ENV_NAME = "CLOUD_CFG"

# This is expected to be a yaml formatted file
CLOUD_CONFIG = '/etc/cloud/cloud.cfg'

# What u get if no config is provided
CFG_BUILTIN = {
    'datasource_list': [
        'NoCloud',
        'ConfigDrive',
        'OpenNebula',
        'DigitalOcean',
        'Azure',
        'AltCloud',
        'OVF',
        'MAAS',
        'GCE',
        'OpenStack',
        'Ec2',
        'CloudSigma',
        'CloudStack',
        'SmartOS',
        'Bigstep',
        # At the end to act as a 'catch' when none of the above work...
        'None',
    ],
    'def_log_file': '/var/log/cloud-init.log',
    'def_log_file_mode': 0o600,
    'log_cfgs': [],
    'mount_default_fields': [None, None, 'auto', 'defaults,nofail', '0', '2'],
    'ssh_deletekeys': False,
    'ssh_genkeytypes': [],
    'syslog_fix_perms': [],
    'system_info': {
        'paths': {
            'cloud_dir': '/var/lib/cloud',
            'templates_dir': '/etc/cloud/templates/',
        },
        'distro': 'rhel',
    },
    'vendor_data': {'enabled': True, 'prefix': []},
}

# Valid frequencies of handlers/modules
PER_INSTANCE = "once-per-instance"
PER_ALWAYS = "always"
PER_ONCE = "once"

# Used to sanity check incoming handlers/modules frequencies
FREQUENCIES = [PER_INSTANCE, PER_ALWAYS, PER_ONCE]

# vi: ts=4 expandtab
