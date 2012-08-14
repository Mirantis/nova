#!/usr/bin/env python
# vim: tabstop=4 shiftwidth=4 softtabstop=4
"""
Unit tests for OpenStack Nova Isilon volume driver.
"""

import nova.flags
import nova.test
import nova.volume.san as san
import nova.volume.isilon as isilon

FLAGS = nova.flags.FLAGS


class TestIsilonDriver(nova.test.TestCase):
    volume_name = 'volume1'
    snapshot_name = 'snapshot1'
    volume_ref1 = {
        'provider_location': '',
        'name': volume_name,
        'size': 1,
    }
    volume_ref2 = {
        'provider_location': '1.1.1.1:3260,1 tgt_volume1',
        'name': volume_name,
        'size': 1,
        }
    snapshot_ref = {
        'name': snapshot_name,
        'volume_name': volume_name,
    }
    connector = {
        'initiator': 'connector'
    }

    def __init__(self, method):
        super(TestIsilonDriver, self).__init__(method)

    def setUp(self):
        super(TestIsilonDriver, self).setUp()
        self.flags(
            san_ip='1.1.1.1',
            isilon_target_prefix='tgt_',
            isilon_access_pattern='concurrency'
        )
        self.mox_execute = self.mox.CreateMockAnything()
        self.driver = isilon.IsilonDriver()
        self.driver._execute = self.mox_execute
        self.mox_super_initialize = self.mox.CreateMockAnything()
        san.SanISCSIDriver.initialize_connection = self.mox_super_initialize

    def test_create_volume(self):
        self.mox_execute('isi', 'target', 'create',
                         '--name=tgt_volume1',
                         '--require-allow=True')
        self.mox_execute('isi', 'lun', 'create',
                         '--name=tgt_volume1:1',
                         '--size=1G',
                         '--access_pattern=concurrency')
        self.mox.ReplayAll()
        res = self.driver.create_volume(self.volume_ref1)
        self.assertEqual(res, {'provider_location':
                               '1.1.1.1:3260,1 tgt_volume1'})

    def test_create_volume_from_snapshot(self):
        self.mox_execute('isi', 'lun', 'clone', '--name=tgt_snapshot1:1',
                         '--clone=tgt_volume1:1', '--type=normal')
        self.mox.ReplayAll()
        self.driver.create_volume_from_snapshot(self.volume_ref2,
                                                self.snapshot_ref)

    def test_delete_volume(self):
        self.mox_execute('isi', 'target', 'delete',
                         '--name=tgt_volume1', '--force')
        self.mox.ReplayAll()
        self.driver.delete_volume(self.volume_ref2)

    def test_create_snapshot(self):
        self.mox_execute('isi', 'lun', 'clone',
                         '--name=tgt_volume1:1',
                         '--clone=tgt_snapshot1:1', '--type=snapshot')
        self.mox.ReplayAll()
        self.driver.create_snapshot(self.snapshot_ref)

    def test_delete_snapshot(self):
        self.mox_execute('isi', 'target', 'delete',
                         '--name=tgt_snapshot1', '--force')
        self.mox.ReplayAll()
        self.driver.delete_snapshot(self.snapshot_ref)

    def test_initialize_connection(self):
        self.mox_execute('isi', 'target', 'modify', '--name=tgt_volume1',
                         '--initiator=connector', 'require-allow=True')
        self.mox_super_initialize(self.driver, self.volume_ref2,
                                  self.connector)
        self.mox.ReplayAll()
        self.driver.initialize_connection(self.volume_ref2, self.connector)

    def test_terminate_connection(self):
        self.mox_execute('isi', 'target', 'modify', '--name=tgt_volume1',
                         '--initiator=no', 'require-allow=False')
        self.mox.ReplayAll()
        self.driver.terminate_connection(self.volume_ref2, self.connector)
