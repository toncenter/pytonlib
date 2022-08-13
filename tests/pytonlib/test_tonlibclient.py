import requests
import pytest
import pytest_asyncio
import asyncio

from time import time
from pathlib import Path
from pytonlib.client import TonlibClient


@pytest.fixture
def tonlib_config():
    url = 'https://ton-blockchain.github.io/global.config.json'
    return requests.get(url).json()


@pytest.fixture
def ton_keystore():
    return f"/tmp/ton_keystore"


@pytest.fixture
def ls_index():
    return 3


@pytest_asyncio.fixture
async def tonlib_client(tonlib_config, ton_keystore, ls_index):
    loop = asyncio.get_running_loop()
    Path(ton_keystore).mkdir(parents=True, exist_ok=True)
    client = TonlibClient(ls_index=ls_index,
                          config=tonlib_config,
                          keystore=ton_keystore,
                          loop=loop,
                          verbosity_level=0,
                          tonlib_timeout=30)
    await client.init()
    return client


# tests
@pytest.mark.asyncio
async def test_get_masterchain_info(tonlib_client: TonlibClient):
    exception = None
    try:
        res = await tonlib_client.get_masterchain_info()
        assert res['@type'] == 'blocks.masterchainInfo'
    except Exception as ee:
        exception = ee
    finally:    
        await tonlib_client.close()
    assert exception is None


@pytest.mark.asyncio
async def test_sync_tonlib_method(tonlib_client: TonlibClient):
    exception = None
    try:
        res = await tonlib_client.sync_tonlib()
        assert res['@type'] == 'ton.blockIdExt'
    except Exception as ee:
        exception = ee
    finally:    
        await tonlib_client.close()
    assert exception is None


@pytest.mark.asyncio
async def test_get_block_header(tonlib_client: TonlibClient):
    exception = None
    try:
        masterchain_block = await tonlib_client.get_masterchain_info()
        res = await tonlib_client.get_block_header(**masterchain_block['last'])
        assert res['@type'] == 'blocks.header'
    except Exception as ee:
        exception = ee
    finally:    
        await tonlib_client.close()
    assert exception is None


@pytest.mark.asyncio
async def test_get_shards(tonlib_client: TonlibClient):
    exception = None
    try:
        masterchain_info = await tonlib_client.get_masterchain_info()
        shards = await tonlib_client.get_shards(master_seqno=masterchain_info['last']['seqno'])
        assert shards['@type'] == 'blocks.shards'
    except Exception as ee:
        exception = ee
    finally:    
        await tonlib_client.close()
    assert exception is None


@pytest.mark.asyncio
async def test_get_transactions(tonlib_client: TonlibClient):
    exception = None
    try:
        masterchain_info = await tonlib_client.get_masterchain_info()

        txs = await tonlib_client.get_block_transactions(**masterchain_info['last'], count=10)
        assert txs['@type'] == 'blocks.transactions'

        tx = await tonlib_client.get_transactions(**txs['transactions'][0], limit=1)
        assert tx[0]['@type'] == 'raw.transaction'
    except Exception as ee:
        exception = ee
    finally:    
        await tonlib_client.close()
    assert exception is None


@pytest.mark.asyncio
async def test_correct_close(tonlib_client: TonlibClient):
    exception = None
    try:
        masterchain_info = await tonlib_client.get_masterchain_info()
        raise RuntimeError('Test error')
    except Exception as ee:
        exception = ee
    finally:
        await tonlib_client.close()
    assert exception.args == ('Test error',)


def test_sync_code(tonlib_config, ton_keystore, ls_index):
    async def main():
        loop = asyncio.get_running_loop()
        exception = None
        try:
            Path(ton_keystore).mkdir(parents=True, exist_ok=True)
            client = TonlibClient(ls_index=ls_index,
                                config=tonlib_config,
                                keystore=ton_keystore,
                                loop=loop,
                                verbosity_level=0)
            await client.init()    
        except Exception as ee:
            exception = ee
        finally:    
            await client.close()
        assert exception is None
    asyncio.run(main())
