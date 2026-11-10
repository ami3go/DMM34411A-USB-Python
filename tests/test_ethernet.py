"""LAN selection, SCPI line framing, and lifecycle over localhost."""

from __future__ import annotations

import socketserver
import threading
from contextlib import contextmanager

import pytest

from dmm34411a import DMM_34411A, DEFAULT_LAN_SOCKET_PORT
from scpi_driver_core import ConfigurationError, UnsupportedOperationError
from scpi_driver_core.transport import TcpTransport, TransportState, VisaTransport

IDN = "Agilent Technologies,34411A,LAN0001,A.03.00"


class DmmHandler(socketserver.StreamRequestHandler):
    def handle(self):
        while message := self.rfile.readline():
            command = message.decode("ascii").strip()
            self.server.commands.append(command)
            replies = {
                "*IDN?": IDN,
                "MEASure:VOLTage:DC? AUTO": "+1.250000E+00",
                "READ?": "+2.500000E+00",
            }
            if command in replies:
                self.wfile.write((replies[command] + "\n").encode("ascii"))
                self.wfile.flush()


@contextmanager
def local_dmm():
    class Server(socketserver.ThreadingTCPServer):
        allow_reuse_address = True
        daemon_threads = True

    with Server(("127.0.0.1", 0), DmmHandler) as server:
        server.commands = []
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield server.server_address[1], server.commands
        finally:
            server.shutdown()
            thread.join(timeout=3.0)


def test_vxi11_builds_standard_visa_resource_without_connecting():
    dmm = DMM_34411A.from_ethernet("192.168.0.55", auto_open=False)
    assert isinstance(dmm.transport, VisaTransport)
    assert dmm.transport.descriptor.address == "TCPIP0::192.168.0.55::inst0::INSTR"
    assert dmm.transport.state is TransportState.CREATED
    assert dmm.idn is None


def test_dns_name_and_legacy_direct_resource():
    dmm = DMM_34411A.from_ethernet("dmm.lab.local", auto_open=False)
    assert dmm.transport.descriptor.address == "TCPIP0::dmm.lab.local::inst0::INSTR"
    direct = DMM_34411A("TCPIP0::192.168.0.55::inst0::INSTR", auto_open=False)
    assert direct.transport.descriptor.address == "TCPIP0::192.168.0.55::inst0::INSTR"


@pytest.mark.parametrize("host", ["", " ", "http://dmm", "192.168.1.1:5025",
                                  "TCPIP0::192.168.1.1::inst0::INSTR", "bad..name",
                                  "-bad.local", "bad\n*RST", None, 4])
def test_bad_hosts_rejected_before_connection(host):
    with pytest.raises(ConfigurationError):
        DMM_34411A.from_ethernet(host, auto_open=False)


@pytest.mark.parametrize("protocol", ["telnet", "hislip", "SOCKET", "", None])
def test_unknown_protocol_is_rejected(protocol):
    with pytest.raises(ConfigurationError):
        DMM_34411A.from_ethernet("dmm.local", protocol=protocol, auto_open=False)


@pytest.mark.parametrize("port", [0, -1, 65536, True, 5.0, "5025"])
def test_invalid_port(port):
    with pytest.raises(ConfigurationError):
        DMM_34411A.from_ethernet("dmm.local", protocol="socket", port=port, auto_open=False)


def test_vxi11_rejects_socket_only_arguments():
    with pytest.raises(ConfigurationError):
        DMM_34411A.from_ethernet("dmm.local", port=5025, auto_open=False)
    with pytest.raises(ConfigurationError):
        DMM_34411A.from_ethernet("dmm.local", connect_timeout_s=1, auto_open=False)


def test_socket_default_port_and_timeout_validation():
    dmm = DMM_34411A.from_ethernet("dmm.local", protocol="socket", auto_open=False)
    assert dmm.transport.descriptor.address == f"dmm.local:{DEFAULT_LAN_SOCKET_PORT}"
    with pytest.raises(ConfigurationError):
        DMM_34411A.from_ethernet("dmm.local", protocol="socket", timeout_s=0, auto_open=False)
    with pytest.raises(ConfigurationError):
        DMM_34411A.from_ethernet(
            "dmm.local", protocol="socket", connect_timeout_s=0, auto_open=False
        )


@pytest.mark.integration
def test_raw_socket_end_to_end_and_explicit_device_clear_safety():
    with local_dmm() as (port, commands):
        with DMM_34411A.from_ethernet("127.0.0.1", protocol="socket", port=port) as dmm:
            assert isinstance(dmm.transport, TcpTransport)
            assert dmm.idn == IDN
            dmm.conf_voltage_dc()
            assert dmm.measure_voltage() == "+1.250000E+00"
            assert dmm.cmd_read() == "+2.500000E+00"
            with pytest.raises(UnsupportedOperationError):
                dmm.device_clear()
        assert dmm.transport.state is TransportState.CLOSED
    assert commands == [
        "*IDN?", ":CONFigure:VOLTage:DC: AUTO", "MEASure:VOLTage:DC? AUTO", "READ?"
    ]


@pytest.mark.integration
def test_raw_socket_deferred_open_close_reopen():
    with local_dmm() as (port, commands):
        dmm = DMM_34411A.from_ethernet(
            "127.0.0.1", protocol="socket", port=port, auto_open=False
        )
        assert dmm.transport.state is TransportState.CREATED
        try:
            dmm.open()
            dmm.open()
            assert dmm.idn == IDN
            dmm.close()
            assert dmm.idn is None
            dmm.open()
            assert dmm.idn == IDN
        finally:
            dmm.close()
    assert commands == ["*IDN?", "*IDN?"]
