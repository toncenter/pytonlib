import json
import platform
import traceback

import pkg_resources
import random
import time
import logging

from ctypes import *

logger = logging.getLogger(__name__)


class TonlibSyncError:
    def __init__(self, result):
        self.result = result

    @property
    def code(self):
        return self.result.get('code')

    def __str__(self):
        return self.result.get('message')


def get_tonlib_path():
    arch_name = platform.system().lower()
    machine = platform.machine().lower()
    if arch_name == 'linux':
        lib_name = f'libtonlibjson.{machine}.so'
    elif arch_name == 'darwin':
        lib_name = f'libtonlibjson.{machine}.dylib'
    elif arch_name == 'freebsd':
        lib_name = f'libtonlibjson.{machine}.so'
    elif arch_name == 'windows':
        lib_name = f'tonlibjson.{machine}.dll'
    else:
        raise RuntimeError(f"Platform '{arch_name}({machine})' is not compatible yet")
    return pkg_resources.resource_filename('pytonlib', f'distlib/{arch_name}/{lib_name}')


# class TonLib for single liteserver
class TonLibSync:
    def __init__(self, ls_index, cdll_path=None, verbosity_level=0):
        cdll_path = get_tonlib_path() if not cdll_path else cdll_path
        tonlib = CDLL(cdll_path)

        tonlib_client_set_verbosity_level = tonlib.tonlib_client_set_verbosity_level
        tonlib_client_set_verbosity_level.restype = None
        tonlib_client_set_verbosity_level.argtypes = [c_int]

        try:
            tonlib_client_set_verbosity_level(verbosity_level)
        except Exception as ee:
            raise RuntimeError(f"Failed to set verbosity level: {ee}")

        tonlib_json_client_create = tonlib.tonlib_client_json_create
        tonlib_json_client_create.restype = c_void_p
        tonlib_json_client_create.argtypes = []
        try:
            self._client = tonlib_json_client_create()
        except Exception as ee:
            raise RuntimeError(f"Failed to create tonlibjson client: {ee}")

        tonlib_json_client_receive = tonlib.tonlib_client_json_receive
        tonlib_json_client_receive.restype = c_char_p
        tonlib_json_client_receive.argtypes = [c_void_p, c_double]
        self._tonlib_json_client_receive = tonlib_json_client_receive

        tonlib_json_client_send = tonlib.tonlib_client_json_send
        tonlib_json_client_send.restype = None
        tonlib_json_client_send.argtypes = [c_void_p, c_char_p]
        self._tonlib_json_client_send = tonlib_json_client_send

        tonlib_json_client_execute = tonlib.tonlib_client_json_execute
        tonlib_json_client_execute.restype = c_char_p
        tonlib_json_client_execute.argtypes = [c_void_p, c_char_p]
        self._tonlib_json_client_execute = tonlib_json_client_execute

        tonlib_json_client_destroy = tonlib.tonlib_client_json_destroy
        tonlib_json_client_destroy.restype = None
        tonlib_json_client_destroy.argtypes = [c_void_p]
        self._tonlib_json_client_destroy = tonlib_json_client_destroy

        self.ls_index = ls_index
        self._state = None  # None, "finished", "crashed", "stuck"

        self.is_dead = False

    
    def __del__(self):
        try:
            self._tonlib_json_client_destroy(self._client)
        except Exception as ee:
            logger.error(f"Exception in tonlibjson.__del__: {traceback.format_exc()}")
            raise RuntimeError(f'Error in tonlibjson.__del__: {ee}')

    def send(self, query):
        query = json.dumps(query).encode('utf-8')
        try:
            self._tonlib_json_client_send(self._client, query)
        except Exception as ee:
            logger.error(f"Exception in tonlibjson.send: {traceback.format_exc()}")
            raise RuntimeError(f'Error in tonlibjson.send: {ee}')
        return

    def receive(self, timeout=10):
        result = None
        try:
            result = self._tonlib_json_client_receive(self._client, timeout)  # time.sleep # asyncio.sleep
        except Exception as ee:
            logger.error(f"Exception in tonlibjson.receive: {traceback.format_exc()}")
            raise RuntimeError(f'Error in tonlibjson.receive: {ee}')
        if result:
            result = json.loads(result.decode('utf-8'))
        return result

    def execute(self, query, timeout=10):
        extra_id = f'ls_index={self.ls_index}'
        query["@extra"] = extra_id
        
        # execution        
        self.send(query)
        result = None
        is_timeout = False
        start_time = time.time()
        while not result and not is_timeout:
            result = self.receive(timeout=0.001)
            is_timeout = time.time() - start_time > timeout
        if is_timeout:
            raise TonlibSyncError(f'timeouted ({timeout} seconds)')
        return result
