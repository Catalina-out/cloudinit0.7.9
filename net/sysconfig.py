# This file is part of cloud-init. See LICENSE file for license information.

import os
import re

import six

from cloudinit.distros.parsers import resolv_conf
from cloudinit import util

from . import renderer


def _subnet_is_ipv6(subnet):
    """Common helper for checking network_state subnets for ipv6."""
    # 'static6' or 'dhcp6'
    if subnet['type'].endswith('6'):
        # This is a request for DHCPv6.
        return True
    elif subnet['type'] == 'static' and ":" in subnet['address']:
        return True
    return False


def _make_header(sep='#'):
    lines = [
        "Created by cloud-init on instance boot automatically, do not edit.",
        "",
    ]
    for i in range(0, len(lines)):
        if lines[i]:
            lines[i] = sep + " " + lines[i]
        else:
            lines[i] = sep
    return "\n".join(lines)


def _is_default_route(route):
    if route['network'] == '::' and route['netmask'] == 0:
        return True
    if route['network'] == '0.0.0.0' and route['netmask'] == '0.0.0.0':
        return True
    return False


def _quote_value(value):
    if re.search(r"\s", value):
        # This doesn't handle complex cases...
        if value.startswith('"') and value.endswith('"'):
            return value
        else:
            return '"%s"' % value
    else:
        return value


class ConfigMap(object):
    """Sysconfig like dictionary object."""

    # Why does redhat prefer yes/no to true/false??
    _bool_map = {
        True: 'yes',
        False: 'no',
    }

    def __init__(self):
        self._conf = {}

    def __setitem__(self, key, value):
        self._conf[key] = value

    def __getitem__(self, key):
        return self._conf[key]

    def drop(self, key):
        self._conf.pop(key, None)

    def __len__(self):
        return len(self._conf)

    def to_string(self):
        buf = six.StringIO()
        buf.write(_make_header())
        if self._conf:
            buf.write("\n")
        for key in sorted(self._conf.keys()):
            value = self._conf[key]
            if isinstance(value, bool):
                value = self._bool_map[value]
            if not isinstance(value, six.string_types):
                value = str(value)
            buf.write("%s=%s\n" % (key, _quote_value(value)))
        return buf.getvalue()


class Route(ConfigMap):
    """Represents a route configuration."""

    route_fn_tpl_ipv4 = '%(base)s/network-scripts/route-%(name)s'
    route_fn_tpl_ipv6 = '%(base)s/network-scripts/route6-%(name)s'

    def __init__(self, route_name, base_sysconf_dir):
        super(Route, self).__init__()
        self.last_idx = 1
        self.has_set_default_ipv4 = False
        self.has_set_default_ipv6 = False
        self._route_name = route_name
        self._base_sysconf_dir = base_sysconf_dir

    def copy(self):
        r = Route(self._route_name, self._base_sysconf_dir)
        r._conf = self._conf.copy()
        r.last_idx = self.last_idx
        r.has_set_default_ipv4 = self.has_set_default_ipv4
        r.has_set_default_ipv6 = self.has_set_default_ipv6
        return r

    @property
    def path_ipv4(self):
        return self.route_fn_tpl_ipv4 % ({'base': self._base_sysconf_dir,
                                          'name': self._route_name})

    @property
    def path_ipv6(self):
        return self.route_fn_tpl_ipv6 % ({'base': self._base_sysconf_dir,
                                          'name': self._route_name})

    def is_ipv6_route(self, address):
        return ':' in address

    def to_string(self, proto="ipv4"):
        # only accept ipv4 and ipv6
        if proto not in ['ipv4', 'ipv6']:
            raise ValueError("Unknown protocol '%s'" % (str(proto)))
        buf = six.StringIO()
        buf.write(_make_header())
        if self._conf:
            buf.write("\n")
        # need to reindex IPv4 addresses
        # (because Route can contain a mix of IPv4 and IPv6)
        reindex = -1
        for key in sorted(self._conf.keys()):
            if 'ADDRESS' in key:
                index = key.replace('ADDRESS', '')
                address_value = str(self._conf[key])
                # only accept combinations:
                # if proto ipv6 only display ipv6 routes
                # if proto ipv4 only display ipv4 routes
                # do not add ipv6 routes if proto is ipv4
                # do not add ipv4 routes if proto is ipv6
                # (this array will contain a mix of ipv4 and ipv6)
                if proto == "ipv4" and not self.is_ipv6_route(address_value):
                    netmask_value = str(self._conf['NETMASK' + index])
                    gateway_value = str(self._conf['GATEWAY' + index])
                    # increase IPv4 index
                    reindex = reindex + 1
                    buf.write("%s=%s\n" % ('ADDRESS' + str(reindex),
                                           _quote_value(address_value)))
                    buf.write("%s=%s\n" % ('GATEWAY' + str(reindex),
                                           _quote_value(gateway_value)))
                    buf.write("%s=%s\n" % ('NETMASK' + str(reindex),
                                           _quote_value(netmask_value)))
                elif proto == "ipv6" and self.is_ipv6_route(address_value):
                    netmask_value = str(self._conf['NETMASK' + index])
                    gateway_value = str(self._conf['GATEWAY' + index])
                    buf.write("%s/%s via %s\n" % (address_value,
                                                  netmask_value,
                                                  gateway_value))

        return buf.getvalue()


class NetInterface(ConfigMap):
    """Represents a sysconfig/networking-script (and its config + children)."""

    iface_fn_tpl = '%(base)s/network-scripts/ifcfg-%(name)s'

    iface_types = {
        'ethernet': 'Ethernet',
        'bond': 'Bond',
        'bridge': 'Bridge',
    }

    def __init__(self, iface_name, base_sysconf_dir, kind='ethernet'):
        super(NetInterface, self).__init__()
        self.children = []
        self.routes = Route(iface_name, base_sysconf_dir)
        self.kind = kind

        self._iface_name = iface_name
        self._conf['DEVICE'] = iface_name
        self._base_sysconf_dir = base_sysconf_dir

    @property
    def name(self):
        return self._iface_name

    @name.setter
    def name(self, iface_name):
        self._iface_name = iface_name
        self._conf['DEVICE'] = iface_name

    @property
    def kind(self):
        return self._kind

    @kind.setter
    def kind(self, kind):
        if kind not in self.iface_types:
            raise ValueError(kind)
        self._kind = kind
        self._conf['TYPE'] = self.iface_types[kind]

    @property
    def path(self):
        return self.iface_fn_tpl % ({'base': self._base_sysconf_dir,
                                     'name': self.name})

    def copy(self, copy_children=False, copy_routes=False):
        c = NetInterface(self.name, self._base_sysconf_dir, kind=self._kind)
        c._conf = self._conf.copy()
        if copy_children:
            c.children = list(self.children)
        if copy_routes:
            c.routes = self.routes.copy()
        return c


class Renderer(renderer.Renderer):
    """Renders network information in a /etc/sysconfig format."""

    # See: https://access.redhat.com/documentation/en-US/\
    #      Red_Hat_Enterprise_Linux/6/html/Deployment_Guide/\
    #      s1-networkscripts-interfaces.html (or other docs for
    #                                         details about this)

    iface_defaults = tuple([
       # ('ONBOOT', True),
        ('ONBOOT', False),
        ('USERCTL', False),
        ('BOOTPROTO', 'none'),
    ])

    # If these keys exist, then their values will be used to form
    # a BONDING_OPTS grouping; otherwise no grouping will be set.
    bond_tpl_opts = tuple([
        ('bond_mode', "mode=%s"),
        ('bond_xmit_hash_policy', "xmit_hash_policy=%s"),
        ('bond_miimon', "miimon=%s"),
    ])

    bridge_opts_keys = tuple([
        ('bridge_stp', 'STP'),
        ('bridge_ageing', 'AGEING'),
        ('bridge_bridgeprio', 'PRIO'),
    ])

    def __init__(self, config=None):
        if not config:
            config = {}
        self.sysconf_dir = config.get('sysconf_dir', 'etc/sysconfig')
        self.netrules_path = config.get(
            'netrules_path', 'etc/udev/rules.d/70-persistent-net.rules')
        self.dns_path = config.get('dns_path', 'etc/resolv.conf')

    @classmethod
    def _render_iface_shared(cls, iface, iface_cfg):
        for k, v in cls.iface_defaults:
            iface_cfg[k] = v

        for (old_key, new_key) in [('mac_address', 'HWADDR'), ('mtu', 'MTU')]:
            old_value = iface.get(old_key)
            if old_value is not None:
                iface_cfg[new_key] = old_value

    @classmethod
    def _render_subnets(cls, iface_cfg, subnets):
        # setting base values
        iface_cfg['BOOTPROTO'] = 'none'

        # modifying base values according to subnets
        for i, subnet in enumerate(subnets, start=len(iface_cfg.children)):
            subnet_type = subnet.get('type')
            if subnet_type == 'dhcp6':
                iface_cfg['IPV6INIT'] = True
                iface_cfg['DHCPV6C'] = True
               # iface_cfg['BOOTPROTO'] = 'dhcp'
                iface_cfg['BOOTPROTO'] = 'none'
            elif subnet_type in ['dhcp4', 'dhcp']:
               # iface_cfg['BOOTPROTO'] = 'dhcp'
                iface_cfg['BOOTPROTO'] = 'none'
            elif subnet_type == 'static':
                # grep BOOTPROTO sysconfig.txt -A2 | head -3
                # BOOTPROTO=none|bootp|dhcp
                # 'bootp' or 'dhcp' cause a DHCP client
                # to run on the device. Any other
                # value causes any static configuration
                # in the file to be applied.
                # ==> the following should not be set to 'static'
                # but should remain 'none'
                # if iface_cfg['BOOTPROTO'] == 'none':
                #    iface_cfg['BOOTPROTO'] = 'static'
                if _subnet_is_ipv6(subnet):
                    iface_cfg['IPV6INIT'] = True
            else:
                raise ValueError("Unknown subnet type '%s' found"
                                 " for interface '%s'" % (subnet_type,
                                                          iface_cfg.name))

        # set IPv4 and IPv6 static addresses
        ipv4_index = -1
        ipv6_index = -1
        for i, subnet in enumerate(subnets, start=len(iface_cfg.children)):
            subnet_type = subnet.get('type')
            if subnet_type == 'dhcp6':
                continue
            elif subnet_type in ['dhcp4', 'dhcp']:
                continue
            elif subnet_type == 'static':
                if _subnet_is_ipv6(subnet):
                    ipv6_index = ipv6_index + 1
                    if 'netmask' in subnet and str(subnet['netmask']) != "":
                        ipv6_cidr = (subnet['address'] +
                                     '/' +
                                     str(subnet['netmask']))
                    else:
                        ipv6_cidr = subnet['address']
                    if ipv6_index == 0:
                        iface_cfg['IPV6ADDR'] = ipv6_cidr
                    elif ipv6_index == 1:
                        iface_cfg['IPV6ADDR_SECONDARIES'] = ipv6_cidr
                    else:
                        iface_cfg['IPV6ADDR_SECONDARIES'] = (
                            iface_cfg['IPV6ADDR_SECONDARIES'] +
                            " " + ipv6_cidr)
                else:
                    ipv4_index = ipv4_index + 1
                    if ipv4_index == 0:
                        iface_cfg['IPADDR'] = subnet['address']
                        if 'netmask' in subnet:
                            iface_cfg['NETMASK'] = subnet['netmask']
                    else:
                        iface_cfg['IPADDR' + str(ipv4_index)] = \
                            subnet['address']
                        if 'netmask' in subnet:
                            iface_cfg['NETMASK' + str(ipv4_index)] = \
                                subnet['netmask']

    @classmethod
    def _render_subnet_routes(cls, iface_cfg, route_cfg, subnets):
        for i, subnet in enumerate(subnets, start=len(iface_cfg.children)):
            for route in subnet.get('routes', []):
                is_ipv6 = subnet.get('ipv6')

                if _is_default_route(route):
                    if (
                            (subnet.get('ipv4') and
                             route_cfg.has_set_default_ipv4) or
                            (subnet.get('ipv6') and
                             route_cfg.has_set_default_ipv6)
                    ):
                        raise ValueError("Duplicate declaration of default "
                                         "route found for interface '%s'"
                                         % (iface_cfg.name))
                    # NOTE(harlowja): ipv6 and ipv4 default gateways
                    gw_key = 'GATEWAY0'
                    nm_key = 'NETMASK0'
                    addr_key = 'ADDRESS0'
                    # The owning interface provides the default route.
                    #
                    # TODO(harlowja): add validation that no other iface has
                    # also provided the default route?
                    iface_cfg['DEFROUTE'] = True
                    if 'gateway' in route:
                        if is_ipv6:
                            iface_cfg['IPV6_DEFAULTGW'] = route['gateway']
                            route_cfg.has_set_default_ipv6 = True
                        else:
                            iface_cfg['GATEWAY'] = route['gateway']
                            route_cfg.has_set_default_ipv4 = True

                else:
                    gw_key = 'GATEWAY%s' % route_cfg.last_idx
                    nm_key = 'NETMASK%s' % route_cfg.last_idx
                    addr_key = 'ADDRESS%s' % route_cfg.last_idx
                    route_cfg.last_idx += 1
                    # add default routes only to ifcfg files, not
                    # to route-* or route6-*
                    for (old_key, new_key) in [('gateway', gw_key),
                                               ('netmask', nm_key),
                                               ('network', addr_key)]:
                        if old_key in route:
                            route_cfg[new_key] = route[old_key]

    @classmethod
    def _render_bonding_opts(cls, iface_cfg, iface):
        bond_opts = []
        for (bond_key, value_tpl) in cls.bond_tpl_opts:
            # Seems like either dash or underscore is possible?
            bond_keys = [bond_key, bond_key.replace("_", "-")]
            for bond_key in bond_keys:
                if bond_key in iface:
                    bond_value = iface[bond_key]
                    if isinstance(bond_value, (tuple, list)):
                        bond_value = " ".join(bond_value)
                    bond_opts.append(value_tpl % (bond_value))
                    break
        if bond_opts:
            iface_cfg['BONDING_OPTS'] = " ".join(bond_opts)

    @classmethod
    def _render_physical_interfaces(cls, network_state, iface_contents):
        physical_filter = renderer.filter_by_physical
        for iface in network_state.iter_interfaces(physical_filter):
            iface_name = iface['name']
            iface_subnets = iface.get("subnets", [])
            iface_cfg = iface_contents[iface_name]
            route_cfg = iface_cfg.routes

            cls._render_subnets(iface_cfg, iface_subnets)
            cls._render_subnet_routes(iface_cfg, route_cfg, iface_subnets)

    @classmethod
    def _render_bond_interfaces(cls, network_state, iface_contents):
        bond_filter = renderer.filter_by_type('bond')
        for iface in network_state.iter_interfaces(bond_filter):
            iface_name = iface['name']
            iface_cfg = iface_contents[iface_name]
            cls._render_bonding_opts(iface_cfg, iface)
            iface_master_name = iface['bond-master']
            iface_cfg['MASTER'] = iface_master_name
            iface_cfg['SLAVE'] = True
            # Ensure that the master interface (and any of its children)
            # are actually marked as being bond types...
            master_cfg = iface_contents[iface_master_name]
            master_cfgs = [master_cfg]
            master_cfgs.extend(master_cfg.children)
            for master_cfg in master_cfgs:
                master_cfg['BONDING_MASTER'] = True
                master_cfg.kind = 'bond'

    @staticmethod
    def _render_vlan_interfaces(network_state, iface_contents):
        vlan_filter = renderer.filter_by_type('vlan')
        for iface in network_state.iter_interfaces(vlan_filter):
            iface_name = iface['name']
            iface_cfg = iface_contents[iface_name]
            iface_cfg['VLAN'] = True
            iface_cfg['PHYSDEV'] = iface_name[:iface_name.rfind('.')]

    @staticmethod
    def _render_dns(network_state, existing_dns_path=None):
        content = resolv_conf.ResolvConf("")
        if existing_dns_path and os.path.isfile(existing_dns_path):
            content = resolv_conf.ResolvConf(util.load_file(existing_dns_path))
        for nameserver in network_state.dns_nameservers:
            content.add_nameserver(nameserver)
        for searchdomain in network_state.dns_searchdomains:
            content.add_search_domain(searchdomain)
        return "\n".join([_make_header(';'), str(content)])

    @classmethod
    def _render_bridge_interfaces(cls, network_state, iface_contents):
        bridge_filter = renderer.filter_by_type('bridge')
        for iface in network_state.iter_interfaces(bridge_filter):
            iface_name = iface['name']
            iface_cfg = iface_contents[iface_name]
            iface_cfg.kind = 'bridge'
            for old_key, new_key in cls.bridge_opts_keys:
                if old_key in iface:
                    iface_cfg[new_key] = iface[old_key]
            # Is this the right key to get all the connected interfaces?
            for bridged_iface_name in iface.get('bridge_ports', []):
                # Ensure all bridged interfaces are correctly tagged
                # as being bridged to this interface.
                bridged_cfg = iface_contents[bridged_iface_name]
                bridged_cfgs = [bridged_cfg]
                bridged_cfgs.extend(bridged_cfg.children)
                for bridge_cfg in bridged_cfgs:
                    bridge_cfg['BRIDGE'] = iface_name

    @classmethod
    def _render_sysconfig(cls, base_sysconf_dir, network_state):
        '''Given state, return /etc/sysconfig files + contents'''
        iface_contents = {}
        for iface in network_state.iter_interfaces():
            iface_name = iface['name']
            iface_cfg = NetInterface(iface_name, base_sysconf_dir)
            cls._render_iface_shared(iface, iface_cfg)
            iface_contents[iface_name] = iface_cfg
        cls._render_physical_interfaces(network_state, iface_contents)
        cls._render_bond_interfaces(network_state, iface_contents)
        cls._render_vlan_interfaces(network_state, iface_contents)
        cls._render_bridge_interfaces(network_state, iface_contents)
        contents = {}
        for iface_name, iface_cfg in iface_contents.items():
            if iface_cfg or iface_cfg.children:
                contents[iface_cfg.path] = iface_cfg.to_string()
                for iface_cfg in iface_cfg.children:
                    if iface_cfg:
                        contents[iface_cfg.path] = iface_cfg.to_string()
            if iface_cfg.routes:
                contents[iface_cfg.routes.path_ipv4] = \
                    iface_cfg.routes.to_string("ipv4")
                contents[iface_cfg.routes.path_ipv6] = \
                    iface_cfg.routes.to_string("ipv6")
        return contents

    def render_network_state(self, target, network_state):
        base_sysconf_dir = os.path.join(target, self.sysconf_dir)
        for path, data in self._render_sysconfig(base_sysconf_dir,
                                                 network_state).items():
            util.write_file(path, data)
        if self.dns_path:
            dns_path = os.path.join(target, self.dns_path)
            resolv_content = self._render_dns(network_state,
                                              existing_dns_path=dns_path)
            util.write_file(dns_path, resolv_content)
        if self.netrules_path:
            netrules_content = self._render_persistent_net(network_state)
            netrules_path = os.path.join(target, self.netrules_path)
            util.write_file(netrules_path, netrules_content)

# vi: ts=4 expandtab
