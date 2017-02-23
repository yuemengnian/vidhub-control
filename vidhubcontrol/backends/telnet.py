import asyncio
import logging
import string

from pydispatch import Property

from vidhubcontrol import aiotelnetlib
from . import VidhubBackendBase, SmartScopeBackendBase

logger = logging.getLogger(__name__)

class TelnetBackendBase(object):
    hostaddr = Property()
    hostport = Property()
    def __init__(self, **kwargs):
        self.read_enabled = False
        self.current_section = None
        self.ack_or_nak = None
        self.read_coro = None
        self.hostaddr = kwargs.get('hostaddr')
        self.hostport = kwargs.get('hostport', self.DEFAULT_PORT)
        self.rx_bfr = b''
        self.response_ready = asyncio.Event()
    async def read_loop(self):
        while self.read_enabled:
            try:
                rx_bfr = await self.client.read_very_eager()
            except Exception as e:
                self.client = None
                self.read_enabled = False
                self.connected = False
                logger.error(e)
                return
            if len(rx_bfr):
                self.rx_bfr += rx_bfr
                if True:#self.rx_bfr.endswith(b'\n\n'):
                    logger.debug(self.rx_bfr.decode('UTF-8'))
                    await self.parse_rx_bfr()
                    self.rx_bfr = b''
            await asyncio.sleep(.1)
    async def send_to_client(self, data):
        if not self.connected:
            c = await self.connect()
        c = self.client
        if not c:
            return
        s = '\n'.join(['---> {}'.format(line) for line in data.decode('UTF-8').splitlines()])
        logger.debug(s)
        try:
            await c.write(data)
        except Exception as e:
            self.client = None
            self.connected = False
            logger.error(e)
    async def do_connect(self):
        self.rx_bfr = b''
        logger.debug('connecting')
        try:
            c = self.client = await aiotelnetlib.Telnet(self.hostaddr, self.hostport)
        except OSError as e:
            logger.error(e)
            self.client = None
            return False
        self.prelude_parsed = False
        self.read_enabled = True
        self.read_coro = asyncio.ensure_future(self.read_loop(), loop=self.event_loop)
        await self.wait_for_response(prelude=True)
        logger.debug('prelude parsed')
        return c
    async def do_disconnect(self):
        logger.debug('disconnecting')
        self.read_enabled = False
        if self.read_coro is not None:
            await asyncio.wait([self.read_coro], loop=self.event_loop)
            self.read_coro = None
        if self.client is not None:
            await self.client.close_async()
        self.client = None
        logger.debug('disconnected')
    async def wait_for_response(self, prelude=False):
        logger.debug('wait_for_response...')
        while self.read_enabled:
            await self.response_ready.wait()
            self.response_ready.clear()
            if prelude:
                if self.prelude_parsed:
                    return
                else:
                    await asyncio.sleep(.1)
            if self.ack_or_nak is not None:
                resp = self.ack_or_nak
                logger.debug('ack_or_nak: {}'.format(resp))
                self.ack_or_nak = None
                return resp

class TelnetBackend(TelnetBackendBase, VidhubBackendBase):
    DEFAULT_PORT = 9990
    SECTION_NAMES = [
        'PROTOCOL PREAMBLE:',
        'VIDEOHUB DEVICE:',
        'INPUT LABELS:',
        'OUTPUT LABELS:',
        'VIDEO OUTPUT LOCKS:',
        'VIDEO OUTPUT ROUTING:',
        'CONFIGURATION:',
    ]
    def __init__(self, **kwargs):
        VidhubBackendBase.__init__(self, **kwargs)
        TelnetBackendBase.__init__(self, **kwargs)
    async def parse_rx_bfr(self):
        def split_value(line):
            return line.split(':')[1].strip(' ')
        bfr = self.rx_bfr.decode('UTF-8')
        section_parsed = False
        for line_idx, line in enumerate(bfr.splitlines()):
            if 'END PRELUDE' in line:
                self.current_section = None
                self.rx_bfr = b''
                self.prelude_parsed = True
                break
            line = line.rstrip('\n')
            if not len(line):
                continue
            if line.startswith('ACK') or line.startswith('NAK'):
                self.ack_or_nak = line
                continue
            if line in self.SECTION_NAMES:
                self.current_section = line.rstrip(':')
                continue
            if self.current_section is None:
                continue
            elif self.current_section == 'PROTOCOL PREAMBLE':
                if line.startswith('Version:'):
                    self.device_version = split_value(line)
            elif self.current_section == 'VIDEOHUB DEVICE':
                if line.startswith('Model name:'):
                    self.device_model = split_value(line)
                elif line.startswith('Unique ID:'):
                    self.device_id = split_value(line).upper()
                elif line.startswith('Video outputs:'):
                    self.num_outputs = int(split_value(line))
                elif line.startswith('Video inputs:'):
                    self.num_inputs = int(split_value(line))
            elif self.current_section == 'OUTPUT LABELS':
                i = int(line.split(' ')[0])
                self.output_labels[i] = ' '.join(line.split(' ')[1:])
                section_parsed = True
            elif self.current_section == 'INPUT LABELS':
                i = int(line.split(' ')[0])
                self.input_labels[i] = ' '.join(line.split(' ')[1:])
                section_parsed = True
            elif self.current_section == 'VIDEO OUTPUT ROUTING':
                out_idx, in_idx = [int(v) for v in line.split(' ')]
                self.crosspoints[out_idx] = in_idx
            else:
                section_parsed = True
        self.response_ready.set()
        if not self.prelude_parsed:
            return
        if self.current_section is not None and section_parsed:
            self.current_section = None
    async def get_status(self, *sections):
        if not len(sections):
            sections = [
                b'VIDEO OUTPUT ROUTING:\n\n',
                b'OUTPUT LABELS:\n\n',
                b'INPUT LABELS:\n\n',
            ]
        for section in sections:
            await self.send_to_client(section)
    async def set_crosspoint(self, out_idx, in_idx):
        return await self.set_crosspoints((out_idx, in_idx))
    async def set_crosspoints(self, *args):
        tx_lines = ['VIDEO OUTPUT ROUTING:']
        for arg in args:
            out_idx, in_idx = arg
            tx_lines.append('{} {}'.format(out_idx, in_idx))
        tx_bfr = bytes('\n'.join(tx_lines), 'UTF-8')
        tx_bfr += b'\n\n'
        with self.emission_lock('crosspoints'):
            await self.send_to_client(tx_bfr)
            r = await self.wait_for_response()
        if r is None or r.startswith('NAK'):
            return False
        return True
    async def set_output_label(self, out_idx, label):
        return await self.set_output_labels((out_idx, label))
    async def set_output_labels(self, *args):
        tx_lines = ['OUTPUT LABELS:']
        for arg in args:
            out_idx, label = arg
            tx_lines.append('{} {}'.format(out_idx, label))
        tx_bfr = bytes('\n'.join(tx_lines), 'UTF-8')
        tx_bfr += b'\n\n'
        with self.emission_lock('output_labels'):
            await self.send_to_client(tx_bfr)
            r = await self.wait_for_response()
        if r is None or r.startswith('NAK'):
            return False
        return True
    async def set_input_label(self, in_idx, label):
        return await self.set_input_labels((in_idx, label))
    async def set_input_labels(self, *args):
        tx_lines = ['INPUT LABELS:']
        for arg in args:
            in_idx, label = arg
            tx_lines.append('{} {}'.format(in_idx, label))
        tx_bfr = bytes('\n'.join(tx_lines), 'UTF-8')
        tx_bfr += b'\n\n'
        with self.emission_lock('input_labels'):
            await self.send_to_client(tx_bfr)
            r = await self.wait_for_response()
        if r is None or r.startswith('NAK'):
            return False
        return True

class SmartScopeTelnetBackend(TelnetBackendBase, SmartScopeBackendBase):
    DEFAULT_PORT = 9992
    SECTION_NAMES = [
        'PROTOCOL PREAMBLE:',
        'SMARTVIEW DEVICE:',
        'NETWORK:',
    ]
    def __init__(self, **kwargs):
        SmartScopeBackendBase.__init__(self, **kwargs)
        TelnetBackendBase.__init__(self, **kwargs)
    async def parse_rx_bfr(self):
        def split_value(line):
            return line.split(':')[1].strip(' ')
        bfr = self.rx_bfr.decode('UTF-8')
        section_parsed = False
        for line_idx, line in enumerate(bfr.splitlines()):
            line = line.rstrip('\n')
            if not len(line):
                if self.current_section.startswith('MONITOR') and len(self.monitors) == self.num_monitors:
                    self.current_section = None
                    self.rx_bfr = b''
                    self.prelude_parsed = True
                    break
                continue
            else:
                newline_count = 0
            if line.startswith('ACK') or line.startswith('NAK'):
                self.ack_or_nak = line
                continue
            if line in self.SECTION_NAMES:
                self.current_section = line.rstrip(':')
                continue
            if self.current_section is None:
                continue
            elif self.current_section == 'PROTOCOL PREAMBLE':
                if line.startswith('Version:'):
                    self.device_version = split_value(line)
            elif self.current_section == 'SMARTVIEW DEVICE':
                if line.startswith('Model:'):
                    self.device_model = split_value(line)
                elif line.startswith('Hostname:'):
                    self.device_id = split_value(line).split('-')[1].upper()
                elif line.startswith('Name:'):
                    if self.device_name is None or self.device_name == self.device_id:
                        self.device_name = split_value(line)
                elif line.startswith('Monitors:'):
                    self.num_monitors = int(split_value(line))
                    for c in string.ascii_uppercase[:self.num_monitors]:
                        s = 'MONITOR {}:'.format(c)
                        if s not in self.SECTION_NAMES:
                            self.SECTION_NAMES.append(s)
                elif line.startswith('Inverted:'):
                    self.inverted = split_value(line) == 'true'
            elif self.current_section == 'NETWORK':
                pass
            elif self.current_section.startswith('MONITOR '):
                monitor_name = self.current_section
                await self.parse_monitor_line(monitor_name, line, split_value(line))
            else:
                section_parsed = True
        self.response_ready.set()
        if not self.prelude_parsed:
            return
        if self.current_section is not None and section_parsed:
            self.current_section = None
    async def parse_monitor_line(self, monitor_name, line, value):
        monitor = None
        for _m in self.monitors:
            if _m.name == monitor_name:
                monitor = _m
                break
        if monitor is None:
            monitor = await self.add_monitor(name=monitor_name)
        prop = None
        if line.startswith('Brightness:'):
            prop = 'brightness'
        elif line.startswith('Contrast:'):
            prop = 'contrast'
        elif line.startswith('Saturation:'):
            prop = 'saturation'
        elif line.startswith('Identify:'):
            prop = 'identify'
        elif line.startswith('Border:'):
            prop = 'border'
        elif line.startswith('WidescreenSD:'):
            prop = 'widescreen_sd'
        elif line.startswith('ScopeMode:'):
            prop = 'scope_mode'
        elif line.startswith('AudioChannel:'):
            prop = 'audio_channel'
        if prop is None:
            return
        if value.isdigit():
            value = int(value)
        await monitor.set_property_from_backend(prop, value)
    def _on_monitors(self, *args, **kwargs):
        return
