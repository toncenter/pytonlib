# PyTONLib

This is standalone Python library based on `libtonlibjson`, the functionality is similar to the [ton-http-api](https://github.com/toncenter/ton-http-api) 
with the following restrictions:

* a client can connect to only one LiteServer;
* a client is asyncronious;
* no requests cache.

## Installation

### From PyPi
Currently, the library works with Ubuntu OS. To install package run
```bash
pip install pytonlib
```

### Docker

Also, the library can be installed inside the Docker. 
To deploy the example of service with Docker Compose run:
```bash
docker-compose -f docker-compose.jupyter.yaml build
docker-compose -f docker-compose.jupyter.yaml up -d
```

This command runs Jupyter Notebook on port 3100 (http://localhost:3100).

## Examples

* Connecting to the first LiteServer in mainnet config:
```python
import requests
import asyncio

from pytonlib import TonlibClient


# downloading mainnet config
ton_config = requests.get('https://newton-blockchain.github.io/global.config.json').json()

# get running event loop
loop = asyncio.get_running_loop()

# init TonlibClient
client = TonlibClient(ls_index=0, # choose LiteServer index to connect
                      config=ton_config,
                      keystore='/tmp/ton_keystore',
                      loop=loop)

# init tonlibjson
await client.init(max_restarts=None)
```

* Reading blocks info:
```python
masterchain_info = await client.get_masterchain_info()
block_header = await client.get_block_header(**masterchain_info['last'])
shards = await client.get_shards(master_seqno=masterchain_info['last']['seqno'])
```

* Reading Block Transactions for masterchain block:
```python
masterchain_info = await client.get_masterchain_info()
txs = await client.get_block_transactions(**masterchain_info['last'], count=10)
```
