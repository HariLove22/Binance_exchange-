"""On-chain deploy service: compile the ERC-20 template and deploy real tokens to an EVM chain.

This is the on-chain counterpart of token_factory (which mints a synthetic ledger asset). Here the
backend compiles `app/contracts/Token.sol` with solc and deploys it via web3 — custodial model: an
exchange-owned deployer account signs and pays gas.

Works against any web3 provider:
  - in-process eth-tester (unit tests) — accounts are unlocked, no signing key needed
  - a local dev node (Anvil / Hardhat) — dev accounts unlocked too
  - a public testnet/mainnet (Sepolia/BSC) — a real private key signs and pays gas

Config (settings / env):
  CHAIN_RPC_URL       JSON-RPC endpoint (e.g. http://127.0.0.1:8545). Empty => in-process eth-tester.
  CHAIN_DEPLOYER_KEY  Deployer private key (0x…). Empty => use the node's first unlocked account.
"""

from decimal import Decimal
from functools import lru_cache
from pathlib import Path

import solcx
from web3 import Web3

SOLC_VERSION = "0.8.24"
DECIMALS = 18
_TOKEN_SOL = Path(__file__).resolve().parent.parent / "contracts" / "Token.sol"


class ChainError(Exception):
    """An on-chain action failed. Safe to surface to a caller."""


@lru_cache(maxsize=1)
def compile_token() -> tuple[list, str]:
    """Compile Token.sol once. Returns (abi, bytecode_hex)."""
    if SOLC_VERSION not in [str(v) for v in solcx.get_installed_solc_versions()]:
        solcx.install_solc(SOLC_VERSION)
    compiled = solcx.compile_source(
        _TOKEN_SOL.read_text(), output_values=["abi", "bin"], solc_version=SOLC_VERSION
    )
    _, artifact = next(iter(compiled.items()))  # single contract in the file
    return artifact["abi"], artifact["bin"]


def make_w3(rpc_url: str | None) -> Web3:
    """A Web3 for the configured RPC, or an in-process eth-tester chain when no RPC is set."""
    if rpc_url:
        return Web3(Web3.HTTPProvider(rpc_url))
    from web3.providers.eth_tester import EthereumTesterProvider
    return Web3(EthereumTesterProvider())


def deployer_address(w3: Web3, private_key: str | None) -> str:
    """The account that deploys: derived from the key, or the node's first unlocked account."""
    if private_key:
        return w3.eth.account.from_key(private_key).address
    if not w3.eth.accounts:
        raise ChainError("no unlocked accounts on the node and no deployer key configured")
    return w3.eth.accounts[0]


def deploy_token(
    w3: Web3,
    *,
    name: str,
    symbol: str,
    supply_whole: Decimal,
    owner_address: str,
    private_key: str | None = None,
) -> dict:
    """Deploy the ERC-20, minting `supply_whole` tokens (whole units) to `owner_address`.

    Returns {address, tx_hash, abi}. Custodial: the deployer signs and pays gas.
    """
    abi, bytecode = compile_token()
    supply_wei = int(supply_whole * (Decimal(10) ** DECIMALS))
    deployer = Web3.to_checksum_address(deployer_address(w3, private_key))
    owner = Web3.to_checksum_address(owner_address)

    Contract = w3.eth.contract(abi=abi, bytecode=bytecode)
    ctor = Contract.constructor(name, symbol, supply_wei, owner)

    if private_key:  # public network: build, sign, send raw
        tx = ctor.build_transaction({
            "from": deployer,
            "nonce": w3.eth.get_transaction_count(deployer),
            "gas": 1_500_000,
            "gasPrice": w3.eth.gas_price,
        })
        signed = w3.eth.account.sign_transaction(tx, private_key)
        tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    else:            # dev node / eth-tester: account is unlocked
        tx_hash = ctor.transact({"from": deployer})

    receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
    if receipt.status != 1:
        raise ChainError("token deployment reverted")
    return {"address": receipt.contractAddress, "tx_hash": tx_hash.hex(), "abi": abi}


def token_contract(w3: Web3, address: str, abi: list):
    return w3.eth.contract(address=Web3.to_checksum_address(address), abi=abi)


def balance_of(w3: Web3, address: str, abi: list, holder: str) -> Decimal:
    """On-chain token balance of `holder`, in whole units."""
    raw = token_contract(w3, address, abi).functions.balanceOf(Web3.to_checksum_address(holder)).call()
    return Decimal(raw) / (Decimal(10) ** DECIMALS)
