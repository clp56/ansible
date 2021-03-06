#!/usr/bin/python
# -*- coding: utf-8 -*-
#
# Copyright (c) 2017 F5 Networks Inc.
# Copyright (c) 2013 Matt Hite <mhite@hotmail.com>
# GNU General Public License v3.0 (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function
__metaclass__ = type


ANSIBLE_METADATA = {'metadata_version': '1.1',
                    'status': ['preview'],
                    'supported_by': 'community'}

DOCUMENTATION = r'''
---
module: bigip_pool_member
short_description: Manages F5 BIG-IP LTM pool members
description:
  - Manages F5 BIG-IP LTM pool members via iControl SOAP API.
version_added: 1.4
author:
  - Matt Hite (@mhite)
  - Tim Rupp (@caphrim007)
notes:
  - Requires BIG-IP software version >= 11
  - F5 developed module 'bigsuds' required (see http://devcentral.f5.com)
  - Best run as a local_action in your playbook
  - Supersedes bigip_pool for managing pool members
requirements:
  - bigsuds
options:
  state:
    description:
      - Pool member state.
    required: True
    default: present
    choices:
      - present
      - absent
  session_state:
    description:
      - Set new session availability status for pool member.
    version_added: 2.0
    choices:
      - enabled
      - disabled
  monitor_state:
    description:
      - Set monitor availability status for pool member.
    version_added: 2.0
    choices:
      - enabled
      - disabled
  pool:
    description:
      - Pool name. This pool must exist.
    required: True
  partition:
    description:
      - Partition
    default: Common
  host:
    description:
      - Pool member IP.
    required: True
    aliases:
      - address
      - name
  port:
    description:
      - Pool member port.
    required: True
  connection_limit:
    description:
      - Pool member connection limit. Setting this to 0 disables the limit.
  description:
    description:
      - Pool member description.
  rate_limit:
    description:
      - Pool member rate limit (connections-per-second). Setting this to 0
        disables the limit.
  ratio:
    description:
      - Pool member ratio weight. Valid values range from 1 through 100.
        New pool members -- unless overridden with this value -- default
        to 1.
  preserve_node:
    description:
      - When state is absent and the pool member is no longer referenced
        in other pools, the default behavior removes the unused node
        o bject. Setting this to 'yes' disables this behavior.
    default: no
    choices:
      - yes
      - no
    version_added: 2.1
extends_documentation_fragment: f5
'''

EXAMPLES = '''
- name: Add pool member
  bigip_pool_member:
    server: lb.mydomain.com
    user: admin
    password: secret
    state: present
    pool: my-pool
    partition: Common
    host: "{{ ansible_default_ipv4['address'] }}"
    port: 80
    description: web server
    connection_limit: 100
    rate_limit: 50
    ratio: 2
  delegate_to: localhost

- name: Modify pool member ratio and description
  bigip_pool_member:
    server: lb.mydomain.com
    user: admin
    password: secret
    state: present
    pool: my-pool
    partition: Common
    host: "{{ ansible_default_ipv4['address'] }}"
    port: 80
    ratio: 1
    description: nginx server
  delegate_to: localhost

- name: Remove pool member from pool
  bigip_pool_member:
    server: lb.mydomain.com
    user: admin
    password: secret
    state: absent
    pool: my-pool
    partition: Common
    host: "{{ ansible_default_ipv4['address'] }}"
    port: 80
  delegate_to: localhost


# The BIG-IP GUI doesn't map directly to the API calls for "Pool ->
# Members -> State". The following states map to API monitor
# and session states.
#
# Enabled (all traffic allowed):
# monitor_state=enabled, session_state=enabled
# Disabled (only persistent or active connections allowed):
# monitor_state=enabled, session_state=disabled
# Forced offline (only active connections allowed):
# monitor_state=disabled, session_state=disabled
#
# See https://devcentral.f5.com/questions/icontrol-equivalent-call-for-b-node-down

- name: Force pool member offline
  bigip_pool_member:
    server: lb.mydomain.com
    user: admin
    password: secret
    state: present
    session_state: disabled
    monitor_state: disabled
    pool: my-pool
    partition: Common
    host: "{{ ansible_default_ipv4['address'] }}"
    port: 80
  delegate_to: localhost
'''

try:
    import bigsuds
    HAS_BIGSUDS = True
except ImportError:
    pass  # Handled by f5_utils.bigsuds_found

from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils.f5_utils import bigip_api, bigsuds_found

HAS_DEVEL_IMPORTS = False

try:
    from library.module_utils.network.f5.common import f5_argument_spec
    from library.module_utils.network.f5.common import fqdn_name
    HAS_DEVEL_IMPORTS = True
except ImportError:
    from ansible.module_utils.network.f5.common import fqdn_name
    from ansible.module_utils.network.f5.common import f5_argument_spec


def pool_exists(api, pool):
    # hack to determine if pool exists
    result = False
    try:
        api.LocalLB.Pool.get_object_status(pool_names=[pool])
        result = True
    except bigsuds.OperationFailed as e:
        if "was not found" in str(e):
            result = False
        else:
            # genuine exception
            raise
    return result


def member_exists(api, pool, address, port):
    # hack to determine if member exists
    result = False
    try:
        members = [{'address': address, 'port': port}]
        api.LocalLB.Pool.get_member_object_status(pool_names=[pool],
                                                  members=[members])
        result = True
    except bigsuds.OperationFailed as e:
        if "was not found" in str(e):
            result = False
        else:
            # genuine exception
            raise
    return result


def delete_node_address(api, address):
    result = False
    try:
        api.LocalLB.NodeAddressV2.delete_node_address(nodes=[address])
        result = True
    except bigsuds.OperationFailed as e:
        if "is referenced by a member of pool" in str(e):
            result = False
        else:
            # genuine exception
            raise
    return result


def remove_pool_member(api, pool, address, port):
    members = [{'address': address, 'port': port}]
    api.LocalLB.Pool.remove_member_v2(
        pool_names=[pool],
        members=[members]
    )


def add_pool_member(api, pool, address, port):
    members = [{'address': address, 'port': port}]
    api.LocalLB.Pool.add_member_v2(
        pool_names=[pool],
        members=[members]
    )


def get_connection_limit(api, pool, address, port):
    members = [{'address': address, 'port': port}]
    result = api.LocalLB.Pool.get_member_connection_limit(
        pool_names=[pool],
        members=[members]
    )[0][0]
    return result


def set_connection_limit(api, pool, address, port, limit):
    members = [{'address': address, 'port': port}]
    api.LocalLB.Pool.set_member_connection_limit(
        pool_names=[pool],
        members=[members],
        limits=[[limit]]
    )


def get_description(api, pool, address, port):
    members = [{'address': address, 'port': port}]
    result = api.LocalLB.Pool.get_member_description(
        pool_names=[pool],
        members=[members]
    )[0][0]
    return result


def set_description(api, pool, address, port, description):
    members = [{'address': address, 'port': port}]
    api.LocalLB.Pool.set_member_description(
        pool_names=[pool],
        members=[members],
        descriptions=[[description]]
    )


def get_rate_limit(api, pool, address, port):
    members = [{'address': address, 'port': port}]
    result = api.LocalLB.Pool.get_member_rate_limit(
        pool_names=[pool],
        members=[members]
    )[0][0]
    return result


def set_rate_limit(api, pool, address, port, limit):
    members = [{'address': address, 'port': port}]
    api.LocalLB.Pool.set_member_rate_limit(
        pool_names=[pool],
        members=[members],
        limits=[[limit]]
    )


def get_ratio(api, pool, address, port):
    members = [{'address': address, 'port': port}]
    result = api.LocalLB.Pool.get_member_ratio(
        pool_names=[pool],
        members=[members]
    )[0][0]
    return result


def set_ratio(api, pool, address, port, ratio):
    members = [{'address': address, 'port': port}]
    api.LocalLB.Pool.set_member_ratio(
        pool_names=[pool],
        members=[members],
        ratios=[[ratio]]
    )


def get_priority_group(api, pool, address, port):
    members = [{'address': address, 'port': port}]
    result = api.LocalLB.Pool.get_member_priority(
        pool_names=[pool],
        members=[members]
    )[0][0]
    return result


def set_priority_group(api, pool, address, port, priority_group):
    members = [{'address': address, 'port': port}]
    api.LocalLB.Pool.set_member_priority(
        pool_names=[pool],
        members=[members],
        priorities=[[priority_group]]
    )


def set_member_session_enabled_state(api, pool, address, port, session_state):
    members = [{'address': address, 'port': port}]
    session_state = ["STATE_%s" % session_state.strip().upper()]
    api.LocalLB.Pool.set_member_session_enabled_state(
        pool_names=[pool],
        members=[members],
        session_states=[session_state]
    )


def get_member_session_status(api, pool, address, port):
    members = [{'address': address, 'port': port}]
    result = api.LocalLB.Pool.get_member_session_status(
        pool_names=[pool],
        members=[members]
    )[0][0]
    result = result.split("SESSION_STATUS_")[-1].lower()
    return result


def set_member_monitor_state(api, pool, address, port, monitor_state):
    members = [{'address': address, 'port': port}]
    monitor_state = ["STATE_%s" % monitor_state.strip().upper()]
    api.LocalLB.Pool.set_member_monitor_state(
        pool_names=[pool],
        members=[members],
        monitor_states=[monitor_state]
    )


def get_member_monitor_status(api, pool, address, port):
    members = [{'address': address, 'port': port}]
    result = api.LocalLB.Pool.get_member_monitor_status(
        pool_names=[pool],
        members=[members]
    )[0][0]
    result = result.split("MONITOR_STATUS_")[-1].lower()
    return result


def main():
    result = {}
    argument_spec = f5_argument_spec

    meta_args = dict(
        session_state=dict(type='str', choices=['enabled', 'disabled']),
        monitor_state=dict(type='str', choices=['enabled', 'disabled']),
        pool=dict(type='str', required=True),
        host=dict(type='str', required=True, aliases=['address', 'name']),
        port=dict(type='int', required=True),
        connection_limit=dict(type='int'),
        description=dict(type='str'),
        rate_limit=dict(type='int'),
        ratio=dict(type='int'),
        preserve_node=dict(type='bool', default=False),
        priority_group=dict(type='int')
    )
    argument_spec.update(meta_args)

    module = AnsibleModule(
        argument_spec=argument_spec,
        supports_check_mode=True
    )

    if not bigsuds_found:
        module.fail_json(msg="the python bigsuds module is required")

    if module.params['validate_certs']:
        import ssl
        if not hasattr(ssl, 'SSLContext'):
            module.fail_json(
                msg='bigsuds does not support verifying certificates with python < 2.7.9. '
                    'Either update python or set validate_certs=False on the task')

    server = module.params['server']
    server_port = module.params['server_port']
    user = module.params['user']
    password = module.params['password']
    state = module.params['state']
    partition = module.params['partition']
    validate_certs = module.params['validate_certs']

    session_state = module.params['session_state']
    monitor_state = module.params['monitor_state']
    pool = fqdn_name(partition, module.params['pool'])
    connection_limit = module.params['connection_limit']
    description = module.params['description']
    rate_limit = module.params['rate_limit']
    ratio = module.params['ratio']
    priority_group = module.params['priority_group']
    host = module.params['host']
    address = fqdn_name(partition, host)
    port = module.params['port']
    preserve_node = module.params['preserve_node']

    if (host and port is None) or (port is not None and not host):
        module.fail_json(msg="both host and port must be supplied")

    if 0 > port or port > 65535:
        module.fail_json(msg="valid ports must be in range 0 - 65535")

    try:
        api = bigip_api(server, user, password, validate_certs, port=server_port)
        if not pool_exists(api, pool):
            module.fail_json(msg="pool %s does not exist" % pool)
        result = {'changed': False}  # default

        if state == 'absent':
            if member_exists(api, pool, address, port):
                if not module.check_mode:
                    remove_pool_member(api, pool, address, port)
                    if preserve_node:
                        result = {'changed': True}
                    else:
                        deleted = delete_node_address(api, address)
                        result = {'changed': True, 'deleted': deleted}
                else:
                    result = {'changed': True}

        elif state == 'present':
            if not member_exists(api, pool, address, port):
                if not module.check_mode:
                    add_pool_member(api, pool, address, port)
                    if connection_limit is not None:
                        set_connection_limit(api, pool, address, port, connection_limit)
                    if description is not None:
                        set_description(api, pool, address, port, description)
                    if rate_limit is not None:
                        set_rate_limit(api, pool, address, port, rate_limit)
                    if ratio is not None:
                        set_ratio(api, pool, address, port, ratio)
                    if session_state is not None:
                        set_member_session_enabled_state(api, pool, address, port, session_state)
                    if monitor_state is not None:
                        set_member_monitor_state(api, pool, address, port, monitor_state)
                    if priority_group is not None:
                        set_priority_group(api, pool, address, port, priority_group)
                result = {'changed': True}
            else:
                # pool member exists -- potentially modify attributes
                if connection_limit is not None and connection_limit != get_connection_limit(api, pool, address, port):
                    if not module.check_mode:
                        set_connection_limit(api, pool, address, port, connection_limit)
                    result = {'changed': True}
                if description is not None and description != get_description(api, pool, address, port):
                    if not module.check_mode:
                        set_description(api, pool, address, port, description)
                    result = {'changed': True}
                if rate_limit is not None and rate_limit != get_rate_limit(api, pool, address, port):
                    if not module.check_mode:
                        set_rate_limit(api, pool, address, port, rate_limit)
                    result = {'changed': True}
                if ratio is not None and ratio != get_ratio(api, pool, address, port):
                    if not module.check_mode:
                        set_ratio(api, pool, address, port, ratio)
                    result = {'changed': True}
                if session_state is not None:
                    session_status = get_member_session_status(api, pool, address, port)
                    if session_state == 'enabled' and session_status == 'forced_disabled':
                        if not module.check_mode:
                            set_member_session_enabled_state(api, pool, address, port, session_state)
                        result = {'changed': True}
                    elif session_state == 'disabled' and session_status != 'forced_disabled':
                        if not module.check_mode:
                            set_member_session_enabled_state(api, pool, address, port, session_state)
                        result = {'changed': True}
                if monitor_state is not None:
                    monitor_status = get_member_monitor_status(api, pool, address, port)
                    if monitor_state == 'enabled' and monitor_status == 'forced_down':
                        if not module.check_mode:
                            set_member_monitor_state(api, pool, address, port, monitor_state)
                        result = {'changed': True}
                    elif monitor_state == 'disabled' and monitor_status != 'forced_down':
                        if not module.check_mode:
                            set_member_monitor_state(api, pool, address, port, monitor_state)
                        result = {'changed': True}
                if priority_group is not None and priority_group != get_priority_group(api, pool, address, port):
                    if not module.check_mode:
                        set_priority_group(api, pool, address, port, priority_group)
                    result = {'changed': True}

    except Exception as e:
        module.fail_json(msg="received exception: %s" % e)

    module.exit_json(**result)


if __name__ == '__main__':
    main()
