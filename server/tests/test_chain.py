"""On-chain deploy: compile the ERC-20 template and deploy a real contract to an in-process EVM.

Proves the backend can create a genuine token contract end-to-end (the same thing Remix did by hand),
against an eth-tester chain so it needs no external node.
"""

from decimal import Decimal

import pytest

from app.services import chain


def test_compile_produces_abi_and_bytecode():
    abi, bytecode = chain.compile_token()
    names = {e.get("name") for e in abi}
    assert {"transfer", "approve", "balanceOf", "totalSupply"} <= names
    assert bytecode.startswith("6080") or len(bytecode) > 100  # real EVM bytecode


def test_deploy_mints_supply_on_chain():
    w3 = chain.make_w3(None)                    # in-process eth-tester
    owner = w3.eth.accounts[1]
    result = chain.deploy_token(
        w3, name="Galaxy", symbol="GALX", supply_whole=Decimal("1000000"), owner_address=owner,
    )
    assert result["address"].startswith("0x") and len(result["address"]) == 42

    # The whole supply is on-chain in the owner's balance.
    assert chain.balance_of(w3, result["address"], result["abi"], owner) == Decimal("1000000")

    # It's a working ERC-20: totalSupply and a transfer move real state.
    c = chain.token_contract(w3, result["address"], result["abi"])
    assert c.functions.totalSupply().call() == 1000000 * 10**18
    assert c.functions.symbol().call() == "GALX"

    to = w3.eth.accounts[2]
    c.functions.transfer(to, 250000 * 10**18).transact({"from": owner})
    assert chain.balance_of(w3, result["address"], result["abi"], to) == Decimal("250000")
    assert chain.balance_of(w3, result["address"], result["abi"], owner) == Decimal("750000")
