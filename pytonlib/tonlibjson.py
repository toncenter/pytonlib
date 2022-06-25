import json
import platform
import traceback

import pkg_resources
import random
import asyncio
import time
import functools
import logging

from copy import deepcopy
from ctypes import *

logger = logging.getLogger(__name__)


class TonlibException(Exception):
    pass

class TonlibNoResponse(TonlibException):
    def __str__(self):
        return 'tonlibjson did not respond'

class TonlibError(TonlibException):
    def __init__(self, result):
        self.result = result

    @property
    def code(self):
        return self.result.get('code')

    def __str__(self):
        return self.result.get('message')

class LiteServerTimeout(TonlibError):
    pass

class BlockNotFound(TonlibError):
    pass

class BlockDeleted(TonlibError):
    pass

class ExternalMessageNotAccepted(TonlibError):
    pass

def parse_tonlib_error(result):
    if result.get('@type') == 'error':
        message = result.get('message')
        if 'not in db' in message:
            return BlockNotFound(result)
        if "state already gc'd" in message:
            return BlockDeleted(result)
        if 'cannot apply external message to current state' in message:
            return ExternalMessageNotAccepted(result)
        if 'adnl query timeout' in message:
            return LiteServerTimeout(result)
        return TonlibError(result)
    return None

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
class TonLib:
    def __init__(self, loop, ls_index, cdll_path=None, verbosity_level=0):
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

        self.futures = {}
        self.loop = loop
        self.ls_index = ls_index
        self._state = None  # None, "finished", "crashed", "stuck"

        self.is_dead = False

        # creating tasks
        self.read_results_task = self.loop.create_task(self.read_results())
        self.del_expired_futures_task = self.loop.create_task(self.del_expired_futures_loop())
    
    def __del__(self):
        try:
            self._tonlib_json_client_destroy(self._client)
        except Exception as ee:
            logger.error(f"Exception in tonlibjson.__del__: {traceback.format_exc()}")
            raise RuntimeError(f'Error in tonlibjson.__del__: {ee}')

    def send(self, query):
        if not self._is_working:
            raise RuntimeError(f"TonLib failed with state: {self._state}")

        query = json.dumps(query).encode('utf-8')
        try:
            self._tonlib_json_client_send(self._client, query)
        except Exception as ee:
            logger.error(f"Exception in tonlibjson.send: {traceback.format_exc()}")
            raise RuntimeError(f'Error in tonlibjson.send: {ee}')

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
        if not self._is_working:
            raise RuntimeError(f"TonLib failed with state: {self._state}")

        extra_id = "%s:%s:%s" % (time.time() + timeout, self.ls_index, random.random())
        query["@extra"] = extra_id
        
        future_result = self.loop.create_future()
        self.futures[extra_id] = future_result

        self.loop.run_in_executor(None, lambda: self.send(query))
        return future_result
    
    @property
    def _is_working(self):
        return self._state not in ('crashed', 'stuck', 'finished')

    async def close(self):
        try:
            self._state = 'finished'
            await self.read_results_task
            await self.del_expired_futures_task
        except Exception as ee:
            logger.error(f"Exception in tonlibjson.close: {traceback.format_exc()}")
            raise RuntimeError(f'Error in tonlibjson.close: {ee}')

    def cancel_futures(self, cancel_all=False):
        now = time.time()
        to_del = []
        for i in self.futures:
            if float(i.split(":")[0]) <= now or cancel_all:
                to_del.append(i)
        logger.debug(f'Pruning {len(to_del)} tasks')
        for i in to_del:
            self.futures[i].set_exception(TonlibNoResponse())
            self.futures.pop(i)

    # tasks
    async def read_results(self):
        timeout = 1
        delta = 5
        receive_func = functools.partial(self.receive, timeout)
        try:
            while self._is_working:
                # return reading result
                result = None
                try:
                    result = await asyncio.wait_for(self.loop.run_in_executor(None, receive_func), timeout=timeout + delta)
                except asyncio.TimeoutError:
                    logger.critical(f"Tonlib #{self.ls_index:03d} stuck (timeout error)")
                    self._state = "stuck"
                except:
                    logger.critical(f"Tonlib #{self.ls_index:03d} crashed: {traceback.format_exc()}")
                    self._state = "crashed"
                
                if isinstance(result, dict) and ("@extra" in result) and (result["@extra"] in self.futures):
                    try:
                        if not self.futures[result["@extra"]].done():
                            tonlib_error = parse_tonlib_error(result)
                            if tonlib_error is not None:
                                self.futures[result["@extra"]].set_exception(tonlib_error)
                            else:
                                self.futures[result["@extra"]].set_result(result)
                        self.futures.pop(result["@extra"])
                    except Exception as e:
                        logger.error(f'Tonlib #{self.ls_index:03d} receiving result exception: {e}')
        except Exception as ee:
            logger.critical(f'Task read_results failed: {ee}')

    async def del_expired_futures_loop(self):
        try:
            while self._is_working:
                self.cancel_futures()
                await asyncio.sleep(1)

            self.cancel_futures(cancel_all=True)
        except Exception as ee:
            logger.critical(f'Task del_expired_futures_loop failed: {ee}')
