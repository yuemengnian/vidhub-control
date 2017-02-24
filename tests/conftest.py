import os
import asyncio

import pytest

def get_vidhub_preamble():
    p = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(p, 'vidhub-preamble.txt'), 'rb') as f:
        s = f.read()
    assert type(s) is bytes
    return s

def get_smartscope_preamble():
    p = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(p, 'smartscope-preamble.txt'), 'rb') as f:
        s = f.read()
    assert type(s) is bytes
    return s

VIDHUB_PREAMBLE = get_vidhub_preamble()
VIDHUB_DEVICE_ID = 'a0b2c3d4e5f6'
VIDHUB_PORT = 9990

SMARTSCOPE_PREAMBLE = get_smartscope_preamble()
SMARTSCOPE_DEVICE_ID = '0a1b2c3d4e5f'
SMARTSCOPE_PORT = 9992

PREAMBLES = {'vidhub':VIDHUB_PREAMBLE, 'smartscope':SMARTSCOPE_PREAMBLE}

@pytest.fixture
def vidhub_telnet_responses():
    d = {
        'preamble':VIDHUB_PREAMBLE,
        'nak':b'NAK\n\n',
        'ack':b'ACK\n\n',
    }
    change_fmt = b'ACK\n\n{command}:\n{changes}\n'
    def get_change_response(command, *args):
        changes = []
        for out_idx, val in args:
            routes.append(b'{} {}'.format(out_idx, val))
        changes = b'\n'.join(changes)
        return change_fmt.format(command=command, changes=changes)
    def get_output_routing(*args):
        return get_change_response(b'VIDEO OUTPUT ROUTING', *args)
    def get_input_routing(*args):
        return get_change_response(b'VIDEO INPUT ROUTING', *args)
    def get_output_labels(*args):
        return get_change_response(b'OUTPUT LABELS', *args)
    def get_input_labels(*args):
        return get_change_response(b'INPUT LABELS', *args)

    d.update(dict(
        output_routing=get_output_routing,
        input_routing=get_input_routing,
        output_labels=get_output_labels,
        input_labels=get_input_labels,
    ))

    return d

@pytest.fixture
def vidhub_zeroconf_info():
    d = {
        'device_name':'Smart Videohub 12x12',
        'device_id':VIDHUB_DEVICE_ID.upper(),
        'info_args':['_blackmagic._tcp.local.', 9990],
        'info_kwargs':{
            'name':'Smart Videohub 12x12-{}._blackmagic._tcp.local.'.format(VIDHUB_DEVICE_ID.upper()),
            'addresses':['127.0.0.1'],
            'properties':{
                'name':'Smart Videohub 12x12',
                'protocol version':'2.7',
                'class':'Videohub',
                'unique id':VIDHUB_DEVICE_ID,
            },
        },
    }
    return d

@pytest.fixture
def smartscope_zeroconf_info():
    d = {
        'device_name':'SmartScope Duo',
        'device_id':SMARTSCOPE_DEVICE_ID.upper(),
        'info_args':['_blackmagic._tcp.local.', 9992],
        'info_kwargs':{
            'name':'SmartScope Duo-{}._blackmagic._tcp.local.'.format(SMARTSCOPE_DEVICE_ID.upper()),
            'addresses':['127.0.0.1'],
            'properties':{
                'name':'SmartScope Duo 4K',
                'protocol version':'1.3',
                'class':'SmartView',
                'unique id':SMARTSCOPE_DEVICE_ID,
            },
        },
    }
    return d

@pytest.fixture
def mocked_vidhub_telnet_device(monkeypatch, vidhub_telnet_responses):
    class Telnet(object):
        preamble = 'vidhub'
        def __init__(self, host=None, port=None, timeout=None, loop=None):
            self.port = port
            self.loop = loop
            self.rx_bfr = b''
            self.tx_bfr = b''
            self.tx_lock = asyncio.Lock()
        @property
        def port(self):
            return getattr(self, '_port', None)
        @port.setter
        def port(self, value):
            self._port = value
            if value == VIDHUB_PORT:
                self.preamble = 'vidhub'
            elif value == SMARTSCOPE_PORT:
                self.preamble = 'smartscope'
        async def open(self, host, port=0, timeout=0, loop=None):
            if self.port is None:
                self.port = port
            self.port
            if not loop and not self.loop:
                loop = self.loop = asyncio.get_event_loop()
            async with self.tx_lock:
                self.tx_bfr = PREAMBLES[self.preamble]
        def close(self):
            pass
        async def close_async(self):
            pass
        async def write(self, bfr):
            self.rx_bfr = b''.join([self.rx_bfr, bfr])
            if bfr.endswith(b'\n\n'):
                bfr = self.rx_bfr
                self.rx_bfr = b''
                await self.process_command(bfr)
        async def process_command(self, bfr):
            async with self.tx_lock:
                if self.preamble == 'vidhub':
                    tx_bfr = b''.join([vidhub_telnet_responses['ack'], bfr])
                else:
                    tx_bfr = vidhub_telnet_responses['ack']
                self.tx_bfr = b''.join([self.tx_bfr, tx_bfr])
        async def read_very_eager(self):
            async with self.tx_lock:
                bfr = self.tx_bfr
                self.tx_bfr = b''
                return bfr
    monkeypatch.setattr('vidhubcontrol.aiotelnetlib._Telnet', Telnet)
    monkeypatch.setattr('vidhubcontrol.backends.telnet.aiotelnetlib._Telnet', Telnet)
    return Telnet

@pytest.fixture
def tempconfig(tmpdir):
    return tmpdir.join('vidhubcontrol.json')
