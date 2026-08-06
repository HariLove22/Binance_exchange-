// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

// A minimal, self-contained ERC-20 (no external imports) so the backend can compile it with just
// solc — no node_modules / import remapping. Standard interface, so wallets and DEXes treat it as a
// normal token. The whole supply is minted to `owner_` at deploy.
contract Token {
    string public name;
    string public symbol;
    uint8 public constant decimals = 18;
    uint256 public totalSupply;

    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;

    event Transfer(address indexed from, address indexed to, uint256 value);
    event Approval(address indexed owner, address indexed spender, uint256 value);

    constructor(string memory name_, string memory symbol_, uint256 supply_, address owner_) {
        name = name_;
        symbol = symbol_;
        totalSupply = supply_;
        balanceOf[owner_] = supply_;
        emit Transfer(address(0), owner_, supply_);
    }

    function transfer(address to, uint256 value) external returns (bool) {
        _transfer(msg.sender, to, value);
        return true;
    }

    function approve(address spender, uint256 value) external returns (bool) {
        allowance[msg.sender][spender] = value;
        emit Approval(msg.sender, spender, value);
        return true;
    }

    function transferFrom(address from, address to, uint256 value) external returns (bool) {
        uint256 allowed = allowance[from][msg.sender];
        require(allowed >= value, "allowance");
        if (allowed != type(uint256).max) {
            allowance[from][msg.sender] = allowed - value;
        }
        _transfer(from, to, value);
        return true;
    }

    function _transfer(address from, address to, uint256 value) internal {
        require(to != address(0), "zero address");
        uint256 bal = balanceOf[from];
        require(bal >= value, "insufficient balance");
        unchecked {
            balanceOf[from] = bal - value;
            balanceOf[to] += value;
        }
        emit Transfer(from, to, value);
    }
}
