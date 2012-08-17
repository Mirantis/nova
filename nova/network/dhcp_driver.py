from nova import flags
from nova import log as logging
from nova import utils

LOG = logging.getLogger(__name__)

FLAGS = flags.FLAGS


class DHCPDriver(object):
    def init_network(self, ctx, network_ref):
        raise NotImplementedError

    def teardown_network(self, ctx, network_ref):
        raise NotImplementedError

    def add_interface(self, ctx, network_ref, ip, vif):
        raise NotImplementedError

    def remove_interface(self, ctx, network_ref, ip, vif):
        raise NotImplementedError


class LinuxNetDHCPDriver(DHCPDriver):
    def __init__(self):
        self.driver = utils.import_object(FLAGS.network_driver)

    def init_network(self, ctx, network_ref):
        dev = self.driver.get_dev(network_ref)
        self.driver.update_dhcp(ctx, dev, network_ref)
        if FLAGS.use_ipv6:
            self.driver.update_ra(ctx, dev, network_ref)

    def teardown_network(self, ctx, network_ref):
        dev = self.driver.get_dev(network_ref)
        self.driver.update_dhcp(ctx, dev, network_ref)

    def add_interface(self, ctx, network_ref, ip, vif):
        # NOTE(yorik-sar): it's called after init_network anyway
        pass

    def remove_interface(self, ctx, network_ref, ip, vif):
        if FLAGS.force_dhcp_release:
            # NOTE(vish): The below errors should never happen, but there may
            #             be a race condition that is causing them per
            #             https://code.launchpad.net/bugs/968457, so we log
            #             an error to help track down the possible race.
            msg = _("Unable to release %s because vif doesn't exist.")
            if not vif:
                LOG.error(msg % ip)
            else:
                dev = self.driver.get_dev(network_ref)
                # NOTE(vish): This forces a packet so that the release_fixed_ip
                #             callback will get called by nova-dhcpbridge.
                self.driver.release_dhcp(dev, ip, vif['address'])
