import base64
from copy import deepcopy
from unittest.mock import AsyncMock

import pytest

from pytonlib.client import TonlibClient
from pytonlib.utils.address import account_forms


SOURCE = "0:" + "ee" * 32
DESTINATION = "0:" + "ff" * 32
CREATED_LT = 1000000
BLOCK = {
    "@type": "ton.blockIdExt",
    "workchain": 0,
    "shard": "-9223372036854775808",
    "seqno": 1,
    "root_hash": "root",
    "file_hash": "file",
}


def b64(value):
    return base64.b64encode(value).decode("ascii")


def short_transaction(account, lt):
    return {
        "account": b64(bytes.fromhex(account.split(":")[1])),
        "lt": str(lt),
        "hash": b64(lt.to_bytes(32, "big")),
    }


def make_client(transactions):
    # Keep the real get_block_transactions conversion/pagination code in use,
    # but avoid loading native tonlib or contacting a liteserver.
    client = TonlibClient.__new__(TonlibClient)
    client.get_shards = AsyncMock(return_value={"shards": [BLOCK]})
    client.lookup_block = AsyncMock(return_value=BLOCK)

    async def read_page(block, count, after):
        assert {**block, "workchain": int(block["workchain"])} == BLOCK
        start = 0
        if after["lt"]:
            start = next(i + 1 for i, tx in enumerate(transactions)
                         if tx["account"] == after["account"]
                         and int(tx["lt"]) == int(after["lt"]))
        page = transactions[start:start + count]
        return {"id": BLOCK, "transactions": deepcopy(page),
                "incomplete": start + len(page) < len(transactions)}

    client.raw_get_block_transactions = AsyncMock(side_effect=read_page)
    return client


@pytest.mark.asyncio
@pytest.mark.parametrize("direction", ["incoming", "outcoming"])
@pytest.mark.parametrize("preceding,matches", [(0, 1), (40, 1), (80, 1), (38, 12)])
async def test_locate_transaction_across_block_pages(direction, preceding, matches):
    account = DESTINATION if direction == "incoming" else SOURCE
    unrelated = [short_transaction("0:" + "11" * 32, CREATED_LT + i)
                 for i in range(preceding)]
    matching = [short_transaction(account, CREATED_LT + 100 + i)
                for i in range(matches)]
    client = make_client(unrelated + matching)
    message = {
        "source": account_forms(SOURCE)["bounceable"]["b64url"],
        "destination": account_forms(DESTINATION)["bounceable"]["b64url"],
        "created_lt": str(CREATED_LT),
    }
    target = {"in_msg": message} if direction == "incoming" else {"out_msgs": [message]}

    async def get_transactions(address, from_transaction_lt, from_transaction_hash, limit):
        assert address == account
        assert from_transaction_lt == int(matching[-1]["lt"])
        assert from_transaction_hash == base64.b64decode(matching[-1]["hash"]).hex()
        assert limit == max(matches, 10)
        # The target is older than ten other transactions in the cross-page case.
        return [{} for _ in range(matches - 1)] + [target]

    client.get_transactions = AsyncMock(side_effect=get_transactions)
    locate = getattr(client, "try_locate_tx_by_" + direction + "_message")
    assert await locate(SOURCE, DESTINATION, CREATED_LT) == target
    assert client.raw_get_block_transactions.await_count == (preceding + matches + 39) // 40
    assert client.get_transactions.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("direction,blocks", [("incoming", 3), ("outcoming", 1)])
async def test_not_found_only_after_all_block_pages(direction, blocks):
    transactions = [short_transaction("0:" + "11" * 32, CREATED_LT + i)
                    for i in range(78)]
    client = make_client(transactions)
    client.get_transactions = AsyncMock()
    locate = getattr(client, "try_locate_tx_by_" + direction + "_message")
    with pytest.raises(Exception, match="^Tx not found$"):
        await locate(SOURCE, DESTINATION, CREATED_LT)
    assert client.raw_get_block_transactions.await_count == blocks * 2
    client.get_transactions.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("direction", ["incoming", "outcoming"])
async def test_empty_complete_block(direction):
    client = make_client([])
    locate = getattr(client, "try_locate_tx_by_" + direction + "_message")
    with pytest.raises(Exception, match="^Tx not found$"):
        await locate(SOURCE, DESTINATION, CREATED_LT)


@pytest.mark.asyncio
async def test_repeated_page_does_not_loop_forever():
    client = make_client([])
    tx = short_transaction(DESTINATION, CREATED_LT + 1)
    tx["account"] = DESTINATION
    client.get_block_transactions = AsyncMock(return_value={
        "transactions": [tx], "incomplete": True,
    })
    with pytest.raises(RuntimeError, match="pagination did not advance"):
        await client.try_locate_tx_by_incoming_message(SOURCE, DESTINATION, CREATED_LT)
    assert client.get_block_transactions.await_count == 2


@pytest.mark.asyncio
async def test_empty_incomplete_page_is_an_error():
    client = make_client([])
    client.get_block_transactions = AsyncMock(return_value={
        "transactions": [], "incomplete": True,
    })
    with pytest.raises(RuntimeError, match="Incomplete block transaction page is empty"):
        await client.try_locate_tx_by_incoming_message(SOURCE, DESTINATION, CREATED_LT)
