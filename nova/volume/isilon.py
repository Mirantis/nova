#!/usr/bin/env python
# vim: tabstop=4 shiftwidth=4 softtabstop=4
"""
Isilon volume driver.
"""

from nova import exception
from nova import flags
from nova import log as logging
from nova.openstack.common import cfg
import nova.volume.san as san

LOG = logging.getLogger(__name__)
FLAGS = flags.FLAGS

isilon_opts = [
    cfg.StrOpt('isilon_isi_cmd', default='isi',
        help='Comand to run at Isilon appliance (may contain sudo)'),
    cfg.StrOpt('isilon_target_prefix',
        default='',
        help='Prefix to generate target name'),
    cfg.StrOpt('isilon_target_iqn_prefix',
        default='iqn.2001-07.com.isilon:chaisi01:',
        help='Prefix to generate target name'),
    cfg.BoolOpt('isilon_thin_provisioning',
        default=True,
        help='Should the thin provisioning be used'),
    cfg.BoolOpt('isilon_smart_cache',
        default=True,
        help='Is the caching ot LUN files enabled'),
    cfg.BoolOpt('isilon_access_pattern',
        default='random',
        help='Defines LUN access pattern'),
    cfg.BoolOpt('isilon_read_only',
        default=False,
        help='Should the LUN be read-only'),
]
FLAGS.register_opts(isilon_opts)


class IsilonDriver(san.SanISCSIDriver):
    """Executes volume driver commands on Isilon.
    There is one target for every LUN, so LUN id is fixed - '1'.
    LUN name will look like <target_name>:1.
    To use this driver the following flags should be set in nova.conf file:

    :san_ip: IP address of SAN controller.
    :san_login: username for SAN controller.
    :san_ssh_port: SSH port to use with SAN.
    :san_password: password for SAN controller or it can be
    :san_private_key: filename of private key to use for SSH authentication.
    """

    def __init__(self):
        super(IsilonDriver, self).__init__()

    def _run_isi(self, *cmd):
        return self._execute(FLAGS.isilon_isi_cmd, *cmd)

    @staticmethod
    def _get_target_name(volume_name):
        """Return iSCSI target name to access volume."""
        return '%s%s' % (FLAGS.isilon_target_prefix, volume_name)

    @staticmethod
    def _get_provider_location(target_name):
        return {'provider_location': '%s:%s,1 %s%s 1' % (
            FLAGS.san_ip, FLAGS.iscsi_port, FLAGS.isilon_target_iqn_prefix,
            target_name)}

    def _create_target(self, target_name):
        """Creates target if there is no one with such name.
        This target will be accessible only for initiator added to it.
        """
        LOG.debug('Target %s creation started' % target_name)
        self._run_isi('target', 'create', '--name=%s' % target_name,
                      '--require-allow=True')

    def _delete_lun(self, target_name):
        """Deletes LUN #1 on specified target."""
        LOG.debug('LUN %s:1 deleting started' % target_name)
        try:
            self._run_isi('lun', 'delete', '--name=%s:1' % target_name,
                          '--force')
        except exception.ProcessExecutionError as e:
            if 'cannot find the specified LUN' in e.stderr:
                LOG.warn('Tried to delete nonexistent LUN %s:1', target_name)
            elif 'cannot find the specified target' in e.stderr:
                LOG.warn('Tried to LUN in nonexistent target %s', target_name)
            else:
                raise

    def _delete_target(self, target_name):
        """Deletes target after there is no one LUN in it.
        All iSCSI sessions connected to the target are terminated.
        """
        LOG.debug('Target %s deleting started' % target_name)
        try:
            self._run_isi('target', 'delete', '--name=%s' % target_name,
                          '--force')
        except exception.ProcessExecutionError as e:
            if 'cannot find the specified target' in e.stderr:
                LOG.warn('Tried to delete nonexistent target %s', target_name)
            else:
                raise

    def create_volume(self, volume):
        """Creates LUN (Logical Unit) on Isilon
        :param volume: reference of volume to be created
        To create LUN appropriate target should be created firstly.
        This LUN will be exported at the very beginning.
        """
        target_name = self._get_target_name(volume['name'])
        self._create_target(target_name)
        self._run_isi('lun', 'create',
            '--name=%s' % target_name + ':1',
            '--size=%s' % self._sizestr(volume['size']),
            '--smart-cache=%s' % (FLAGS.isilon_smart_cache,),
            '--read-only=%s' % (FLAGS.isilon_read_only,),
            '--thin=%s' % (FLAGS.isilon_thin_provisioning,),
        )
        return self._get_provider_location(target_name)

    def create_volume_from_snapshot(self, volume, snapshot):
        """Creates LUN (Logical Unit) from snapshot for Isilon.
        :param volume: reference of volume to be created
        :param snapshot: reference of source snapshot
        """
        volume_target_name = self._get_target_name(volume['name'])
        self._create_target(volume_target_name)
        snapshot_target_name = self._get_target_name(snapshot['name'])
        self._run_isi('lun', 'clone',
            '--name=%s:1' % snapshot_target_name,
            '--clone=%s:1' % volume_target_name, '--type=normal',
            '--smart-cache=%s' % (FLAGS.isilon_smart_cache,),
            '--read-only=%s' % (FLAGS.isilon_read_only,),
        )
        return self._get_provider_location(volume_target_name)

    def delete_volume(self, volume):
        """Deletes LUN (Logical Unit)
        :param volume: reference of volume to be deleted
        """
        target_name = self._get_target_name(volume['name'])
        self._delete_lun(target_name)
        self._delete_target(target_name)

    def create_snapshot(self, snapshot):
        """Creates LUN snapshot (LUN clone with type 'snapshot' meant)
        :param snapshot: reference of snapshot to be created
        'name' is the name of LUN to clone (<lun_target_name>:1)
        'clone' is the name of clone (<snapshot_target_name>:1)
        """
        snapshot_target_name = self._get_target_name(snapshot['name'])
        self._create_target(snapshot_target_name)
        volume_target_name = self._get_target_name(snapshot['volume_name'])
        self._run_isi('lun', 'clone',
                      '--name=%s:1' % volume_target_name,
                      '--clone=%s:1' % snapshot_target_name, '--type=snapshot')

    def delete_snapshot(self, snapshot):
        """Deletes LUN snapshot (LUN clone with type 'snapshot' meant).
        :param snapshot: reference of snapshot to be deleted
        """
        target_name = self._get_target_name(snapshot['name'])
        self._delete_lun(target_name)
        self._delete_target(target_name)

    def create_export(self, context, volume):
        """Exports LUN. There is nothing to export."""
        pass

    def ensure_export(self, context, volume):
        """Recreates export - nothing to recreate."""
        pass

    def remove_export(self, context, volume):
        """Removes all resources connected to volume.
        On Isilon we need to create target before LUN, so there is nothing
        to remove.
        """
        pass

    def initialize_connection(self, volume, connector):
        """Adds initiator to volumes target.
        Restricts LUNs target access only to the initiator mentioned.
        :param volume: reference of volume to be created
        :param connector: dictionary with information about the host that will
        connect to the volume in the format: {'ip': ip, 'initiator': initiator}
        Here ip is the ip address of the connecting machine,
        initiator is the ISCSI initiator name of the connecting machine.
        """
        target_name = self._get_target_name(volume['name'])
        self._run_isi('target', 'modify', '--name=%s' % (target_name,),
                '--add-initiator=%s' % (connector['initiator'],))
        return super(IsilonDriver, self).initialize_connection(
                volume, connector)

    def terminate_connection(self, volume, connector):
        """Deletes initiator from volumes target.
        Access to the LUNs target is unrestricted.
        :param volume: reference of volume to be created
        :param connector: dictionary with information about the connector
        """
        target_name = self._get_target_name(volume['name'])
        self._run_isi('target', 'modify', '--name=%s' % (target_name,),
                      '--delete-initiator=%s' % (connector['initiator'],))
