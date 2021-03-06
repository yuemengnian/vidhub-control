import os
import asyncio
import time
import pytest

KIVY_STALL_TIMEOUT = 90

@pytest.fixture
def kivy_app(tmpdir, monkeypatch):
    vidhub_conf = tmpdir.join('vidhubcontrol.json')
    ui_conf = tmpdir.join('vidhubcontrol-ui.ini')

    monkeypatch.setenv('KIVY_UNITTEST', '1')
    monkeypatch.setattr('vidhubcontrol.runserver.Config.DEFAULT_FILENAME', str(vidhub_conf))

    from kivy.clock import Clock
    from kivy.base import runTouchApp, stopTouchApp
    from vidhubcontrol.kivyui import main as kivy_main

    aio_loop = asyncio.get_event_loop()
    aio_loop.set_debug(True)

    class AppOverride(kivy_main.VidhubControlApp):
        def get_application_config(self):
            return str(ui_conf)

        def on_start(self, *args, **kwargs):
            super().on_start(*args, **kwargs)
            self._startup_ready.set()

        def run(self):
            self.aio_loop = aio_loop
            kv_dir = os.path.dirname(os.path.abspath(kivy_main.__file__))
            self.kv_file = os.path.join(kv_dir, 'vidhubcontrol.kv')
            self._startup_ready = asyncio.Event()
            if not self.built:
                self.load_config()
                self.load_kv(filename=self.kv_file)
                root = self.build()
                if root:
                    self.root = root

            if self.root:
                from kivy.core.window import Window
                Window.add_widget(self.root)

            # Check if the window is already created
            from kivy.base import EventLoop
            window = EventLoop.window
            if window:
                self._app_window = window
                window.set_title(self.get_application_name())
                icon = self.get_application_icon()
                if icon:
                    window.set_icon(icon)
                self._install_settings_keys(window)
            else:
                Logger.critical("Application: No window is created."
                                " Terminating application run.")
                return
            self._kv_loop = EventLoop
            self._kv_loop_running = True
            self._aio_running = True
            self.dispatch('on_start')
            runTouchApp(self.root, slave=True)
            self._aio_mainloop_future = asyncio.ensure_future(self._aio_mainloop())

        def stop(self):
            self.dispatch('on_stop')

            stopTouchApp()

            # Clear the window children
            if self._app_window:
                for child in self._app_window.children:
                    self._app_window.remove_widget(child)

            self._kv_loop_running = False

        async def wait_for_widget_init(self, root=None):
            if root is None:
                root = self.root
            def check_init():
                for w in root.walk():
                    if w.parent is None:
                        return False
                    if 'app' in w.properties() and w.app is None:
                        return False
                return True
            while not check_init():
                await asyncio.sleep(0)

        async def start_async(self):
            self.run()
            await self._startup_ready.wait()
            await self.wait_for_widget_init()

        async def stop_async(self):
            if self._kv_loop_running:
                self.stop()
            await self._aio_mainloop_future
            while not self.async_server.thread_stop_event.is_set():
                await asyncio.sleep(.1)

        async def _aio_mainloop(self):
            start_ts = self.aio_loop.time()
            while not self._kv_loop.quit:
                now = self.aio_loop.time()
                if now >= start_ts + KIVY_STALL_TIMEOUT:
                    print ('Exiting app. Runtime exceeded threshold')
                    raise KeyboardInterrupt()
                self._kv_loop.idle()
                await asyncio.sleep(0)
            self._kv_loop.exit()

    app = AppOverride()
    return app

@pytest.fixture
def KvEventWaiter():
    class KvEventWaiter_(object):
        def __init__(self):
            self.aio_event = asyncio.Event()
        def bind(self, obj, *events):
            kwargs = {e:self.kivy_callback for e in events}
            obj.bind(**kwargs)
        def unbind(self, obj, *events):
            kwargs = {e:self.kivy_callback for e in events}
            obj.unbind(**kwargs)
        async def wait(self):
            await self.aio_event.wait()
            self.aio_event.clear()
        async def bind_and_wait(self, obj, *events):
            self.aio_event.clear()
            self.bind(obj, *events)
            await self.wait()
        def kivy_callback(self, *args, **kwargs):
            self.aio_event.set()

    return KvEventWaiter_
