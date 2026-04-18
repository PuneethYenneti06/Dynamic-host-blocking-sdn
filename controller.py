from pox.core import core
from pox.lib.util import dpid_to_str
import pox.openflow.libopenflow_01 as of
from pox.lib.addresses import IPAddr
import time
import os

log = core.getLogger()

THRESHOLD = 10
TIME_WINDOW = 30
LOG_PATH = "/home/vboxuser/SDN-mininet/Dynamic-host-blocking-sdn/blocked_hosts.log"

def write_log(message):
    timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
    with open(LOG_PATH, "a") as f:
        f.write(f"[{timestamp}] {message}\n")

class DynamicBlockController(object):
    def __init__(self):
        core.openflow.addListeners(self)
        self.mac_to_port = {}
        self.packet_counts = {}
        self.blocked_hosts = set()

        # Clear log file on startup
        open(LOG_PATH, "w").close()

        log.info("=== Dynamic Block Controller Started ===")
        log.info("Threshold: %d packets in %d seconds", THRESHOLD, TIME_WINDOW)
        write_log("=== Controller Started ===")
        write_log(f"Threshold: {THRESHOLD} packets in {TIME_WINDOW} seconds")

    def _handle_ConnectionUp(self, event):
        dpid = dpid_to_str(event.dpid)
        log.info("Switch connected: %s", dpid)
        write_log(f"Switch connected: {dpid}")

    def _handle_PacketIn(self, event):
        packet = event.parsed
        if not packet.parsed:
            return

        dpid = event.dpid
        in_port = event.port

        src_mac = str(packet.src)
        dst_mac = str(packet.dst)
        self.mac_to_port.setdefault(dpid, {})
        self.mac_to_port[dpid][src_mac] = in_port

        ip_packet = packet.find('ipv4')
        if ip_packet:
            src_ip = str(ip_packet.srcip)
            dst_ip = str(ip_packet.dstip)
            now = time.time()

            if src_ip not in self.packet_counts:
                self.packet_counts[src_ip] = []

            self.packet_counts[src_ip] = [
                t for t in self.packet_counts[src_ip]
                if now - t < TIME_WINDOW
            ]
            self.packet_counts[src_ip].append(now)
            count = len(self.packet_counts[src_ip])

            # Log every packet event
            print(f"[MONITOR] {src_ip} → {dst_ip} | count: {count}/{THRESHOLD}")
            write_log(f"PACKET   | src: {src_ip} → dst: {dst_ip} | count: {count}/{THRESHOLD}")

            # Already blocked
            if src_ip in self.blocked_hosts:
                print(f"[DROPPED] Packet from blocked host {src_ip}")
                write_log(f"DROPPED  | {src_ip} is already blocked, packet dropped")
                return

            # Threshold exceeded
            if count >= THRESHOLD:
                self.blocked_hosts.add(src_ip)
                self._block_host(event, src_ip)
                return

        # Forward packet
        if dst_mac in self.mac_to_port.get(dpid, {}):
            out_port = self.mac_to_port[dpid][dst_mac]
        else:
            out_port = of.OFPP_FLOOD

        msg = of.ofp_packet_out()
        msg.data = event.ofp
        msg.actions.append(of.ofp_action_output(port=out_port))
        event.connection.send(msg)

        write_log(f"FORWARD  | {src_mac} → {dst_mac} | out_port: {out_port}")

    def _block_host(self, event, src_ip):
        timestamp = time.strftime('%Y-%m-%d %H:%M:%S')

        print("=" * 50)
        print(f"[ALERT]  SUSPICIOUS ACTIVITY DETECTED!")
        print(f"[ALERT]  Blocking host : {src_ip}")
        print(f"[ALERT]  Reason        : Exceeded {THRESHOLD} packets in {TIME_WINDOW}s")
        print(f"[ALERT]  Time          : {timestamp}")
        print("=" * 50)

        log.warning("BLOCKING HOST: %s", src_ip)

        # Install DROP rule
        fm = of.ofp_flow_mod()
        fm.match.dl_type = 0x0800
        fm.match.nw_src = IPAddr(src_ip)
        fm.priority = 100
        fm.idle_timeout = 0
        fm.hard_timeout = 0
        event.connection.send(fm)

        # Log block event
        write_log("=" * 40)
        write_log(f"BLOCKED  | Host: {src_ip}")
        write_log(f"REASON   | Exceeded {THRESHOLD} packets in {TIME_WINDOW}s")
        write_log(f"ACTION   | DROP rule installed in switch")
        write_log("=" * 40)

def launch():
    core.registerNew(DynamicBlockController)