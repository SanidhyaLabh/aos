// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/**
 * @title IOracle
 * @notice Standard oracle interface returning price and freshness validity flag.
 */
interface IOracle {
    function read() external view returns (uint256 price, bool valid);
}
