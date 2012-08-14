#!/usr/bin/env python
# vim: tabstop=4 shiftwidth=4 softtabstop=4
"""
Isilon volume driver.
"""

from nova import flags
from nova import log as logging
from nova.openstack.common import cfg
import nova.volume.san as san

LOG = logging.getLogger(__name__)
FLAGS = flags.FLAGS

isilon_opts = [
    cfg.StrOpt('isilon_target_prefix',
        default='',
        help='Prefix to generate target name'),
    cfg.StrOpt('isilon_thin_provisioning',
        default=True,
        help='Should the thin provisioning be used'),
    cfg.StrOpt('isilon_smart_cache',
        default=True,
        help='Is the caching ot LUN files enabled'),
    cfg.StrOpt('isilon_access_pattern',
        default='random',
        help='Defines LUN access pattern'),
    cfg.StrOpt('isilon_read_only',
        default=False,
        help='Should the LUN be read-only')]
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

    @staticmethod
    def _get_target_name(volume_name):
        """Return iSCSI target name to access volume."""
        return '%s%s' % (FLAGS.isilon_target_prefix, volume_name)

    def _create_target(self, target_name):
        """Creates target if there is no one with such name.
        This target will be accessible only for initiator added to it.
        """
        LOG.debug('Target %s creation started' % target_name)
        try:
            self._execute('isi', 'target', 'create', '--name=%s' % target_name,
                          '--require-allow=%s' % True)
        except Exception:
            LOG.debug('Target with name %s has existed already' % target_name)

    def _update_target(self, target_name, prop_dict):
        """Updates target due to properties in the prop_dict"""
        LOG.debug('Target %s updating started' % target_name)
        cmd = ['isi', 'target', 'modify', '--name=%s' % target_name]
        for prop in prop_dict.keys():
            cmd.append('--%s=%s' % (prop, prop_dict[prop]))
        try:
            self._execute(*cmd)
        except Exception as exc:
            LOG.debug('Exception during target updating raised with \
                       message %s' % exc.message)

    def _delete_target(self, target_name):
        """Deletes target after there is no one LUN in it.
        All iSCSI sessions connected to the target are terminated.
        """
        LOG.debug('Target %s deleting started' % target_name)
        self._execute('isi', 'target', 'delete', '--name=%s' % target_name,
                      '--force')

    def create_volume(self, volume):
        """Creates LUN (Logical Unit) on Isilon
        :param volume: reference of volume to be created
        To create LUN appropriate target should be created firstly.
        This LUN will be exported at the very beginning.
        """
        LOG.debug('Volume with name %s creating started' % volume['name'])
        tg_name = self._get_target_name(volume['name'])
        self._create_target(tg_name)

        cmd = ['isi', 'lun', 'create',
               '--name=%s' % tg_name + ':1',
               '--size=%s' % self._sizestr(volume['size'])]
        if not FLAGS.isilon_smart_cache:
            cmd.append('--smart-cache=False')
        if FLAGS.isilon_read_only:
            cmd.append('--read-only=True')
        if not FLAGS.isilon_thin_provisioning:
            cmd.append('--thin=False')
        cmd.append('--access_pattern=%s' % FLAGS.isilon_access_pattern)
        self._execute(*cmd)
        return {'provider_location': '%s:%s,1 %s' % (FLAGS.san_ip,
                                                     FLAGS.iscsi_port,
                                                     tg_name)}

    def create_volume_from_snapshot(self, volume, snapshot):
        """Creates LUN (Logical Unit) from snapshot for Isilon.
        :param volume: reference of volume to be created
        :param snapshot: reference of source snapshot
        """
        LOG.debug('Volume with name %s creating from snapshot with name \
                  %s started', (volume['name'], snapshot['name']))
        snapshot_lun_name = self._get_target_name(snapshot['name']) + ':1'
        volume_lun_name = volume['provider_location'].split()[-1] + ':1'
        self._execute('isi', 'lun', 'clone', '--name=%s' % snapshot_lun_name,
                      '--clone=%s' % volume_lun_name, '--type=normal')

    def delete_volume(self, volume):
        """Deletes LUN (Logical Unit)
        :param volume: reference of volume to be deleted
        """
        LOG.debug('LUN %s deletion started' % volume['name'])
        self._delete_target(volume['provider_location'].split()[-1])

    def create_snapshot(self, snapshot):
        """Creates LUN snapshot (LUN clone with type 'snapshot' meant)
        :param snapshot: reference of snapshot to be created
        'name' is the name of LUN to clone (<lun_target_name>:1)
        'clone' is the name of clone (<snapshot_target_name>:1)
        """
        LOG.debug('Snapshot creating started for the snapshot with name %s' %
                  snapshot['name'])
        lun_name = self._get_target_name(snapshot['volume_name']) + ':1'
        snapshot_name = self._get_target_name(snapshot['name']) + ':1'
        self._execute('isi', 'lun', 'clone',
                      '--name=%s' % lun_name,
                      '--clone=%s' % snapshot_name, '--type=snapshot')

    def delete_snapshot(self, snapshot):
        """Deletes LUN snapshot (LUN clone with type 'snapshot' meant).
        :param snapshot: reference of snapshot to be deleted
        """
        LOG.debug('Snapshot deletion started for the snapshot with name %s' %
                  snapshot['name'])
        self._delete_target(self._get_target_name(snapshot['name']))

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
        LOG.debug('Connection to the volume with name %s initializing' %
                  volume['name'])
        self._update_target(volume['provider_location'].split()[-1],
                            {'initiator': connector['initiator'],
                            'require-allow': True})
        san.SanISCSIDriver.initialize_connection(self, volume, connector)

    def terminate_connection(self, volume, connector):
        """Deletes initiator from volumes target.
        Access to the LUNs target is unrestricted.
        :param volume: reference of volume to be created
        :param connector: dictionary with information about the connector
        """
        LOG.debug('Connection to the volume with name %s terminating' %
                  volume['name'])
        self._update_target(volume['provider_location'].split()[-1],
                            {'initiator': 'no',
                             'require-allow': False})
