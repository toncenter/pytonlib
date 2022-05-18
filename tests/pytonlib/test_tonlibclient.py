import logging
import requests
import pytest
import pytest_asyncio
import asyncio

from time import time
from pytonlib.client import TonlibClient


# logging.basicConfig(format='%(asctime)s %(module)-15s %(message)s',
#                     level=logging.INFO)
# logger = logging.getLogger(__name__)


@pytest.fixture
def tonlib_config():
    url = 'https://newton-blockchain.github.io/global.config.json'
    return requests.get(url).json()


@pytest.fixture
def ton_keystore():
    return f"/tmp/ton_keystore"


@pytest.fixture
def ls_index():
    return 0


@pytest_asyncio.fixture
async def tonlib_client(tonlib_config, ton_keystore, ls_index):
    loop = asyncio.get_running_loop()

    client = TonlibClient(ls_index=ls_index,
                          config=tonlib_config,
                          keystore=ton_keystore,
                          loop=loop,
                          verbosity_level=0)
    await client.init()
    return client


# tests
@pytest.mark.asyncio
async def test_get_masterchain_info(tonlib_client: TonlibClient):
    res = await tonlib_client.get_masterchain_info()
    assert res['@type'] == 'blocks.masterchainInfo'

    await tonlib_client.close()


@pytest.mark.asyncio
async def test_get_block_header(tonlib_client: TonlibClient):
    masterchain_block = await tonlib_client.get_masterchain_info()
    res = await tonlib_client.get_block_header(**masterchain_block['last'])
    assert res['@type'] == 'blocks.header'

    await tonlib_client.close()


@pytest.mark.asyncio
async def test_get_shards(tonlib_client: TonlibClient):
    masterchain_info = await tonlib_client.get_masterchain_info()
    shards = await tonlib_client.get_shards(master_seqno=masterchain_info['last']['seqno'])
    assert shards['@type'] == 'blocks.shards'

    await tonlib_client.close()


@pytest.mark.asyncio
async def test_get_transactions(tonlib_client: TonlibClient):
    masterchain_info = await tonlib_client.get_masterchain_info()

    txs = await tonlib_client.get_block_transactions(**masterchain_info['last'], count=10)
    assert txs['@type'] == 'blocks.transactions'

    tx = await tonlib_client.get_transactions(**txs['transactions'][0], limit=1)
    assert tx[0]['@type'] == 'raw.transaction'
    
    await tonlib_client.close()


def test_sync_code(tonlib_config, ton_keystore, ls_index):
    async def main():
        loop = asyncio.get_running_loop()

        client = TonlibClient(ls_index=ls_index,
                              config=tonlib_config,
                              keystore=ton_keystore,
                              loop=loop,
                              verbosity_level=0)
        await client.init()
        await client.close()

    asyncio.run(main())
