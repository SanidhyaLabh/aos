// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "./interfaces/IOracle.sol";

/**
 * @title VanillaOSM
 * @notice Faithful recreation of the MakerDAO Oracle Security Module (OSM) pattern.
 * @dev Relies on a single whitelisted feeder (src) calling poke() after a fixed delay (hop).
 *
 * Vulnerability inherent to this design:
 * - Staleness-by-omission: If the feeder stops calling poke() (due to downtime, network congestion,
 *   or malicious intent), the last accepted price (cur) persists indefinitely and read()
 *   continues to flag it as valid.
 * - Single-source trust: No cryptographic proof of multi-source consensus or freshness window.
 */
contract VanillaOSM is IOracle {
    address public governance;
    address public src;              // Whitelisted single data feeder
    uint256 public hop;              // Delay period between updates (e.g. 3600s / 1 hour)
    uint256 public zzz;              // Timestamp of last successful poke
    bool public stopped;

    uint256 public cur;              // Current active price served downstream
    uint256 public nxt;              // Staged price waiting for next hop delay

    event LogPoke(uint256 curVal, uint256 nxtVal, uint256 timestamp);
    event LogChangeSrc(address indexed newSrc);
    event LogEmergencyStop(bool stopped);

    modifier onlyGov() {
        require(msg.sender == governance, "OSM: not-governance");
        _;
    }

    modifier onlySrc() {
        require(msg.sender == src, "OSM: not-whitelisted-feeder");
        _;
    }

    constructor(address _src, uint256 _hop, uint256 _initialPrice) {
        governance = msg.sender;
        src = _src;
        hop = _hop;
        cur = _initialPrice;
        nxt = _initialPrice;
        zzz = block.timestamp;
    }

    /**
     * @notice Feeds a new price into nxt and promotes previous nxt to cur if hop elapsed.
     * @param price New price feed value (e.g., 18 decimals)
     */
    function poke(uint256 price) external onlySrc {
        require(!stopped, "OSM: stopped");
        require(price > 0, "OSM: invalid-price");

        // Can only promote when at least hop seconds have elapsed since last poke
        if (block.timestamp >= zzz + hop) {
            cur = nxt;
            nxt = price;
            zzz = block.timestamp;
            emit LogPoke(cur, nxt, block.timestamp);
        } else {
            // Stage new value without promoting cur yet
            nxt = price;
        }
    }

    /**
     * @notice Reads the current price and validity.
     * @return price The currently active price.
     * @return valid True as long as cur > 0 and contract is not stopped.
     * @dev Notice that 'valid' does NOT check if the price is fresh! Even if poke() hasn't
     * been called for days, valid returns TRUE.
     */
    function read() external view override returns (uint256 price, bool valid) {
        valid = (cur > 0 && !stopped);
        return (cur, valid);
    }

    function setSrc(address newSrc) external onlyGov {
        src = newSrc;
        emit LogChangeSrc(newSrc);
    }

    function setHop(uint256 newHop) external onlyGov {
        hop = newHop;
    }

    function emergencyStop(bool _stopped) external onlyGov {
        stopped = _stopped;
        emit LogEmergencyStop(_stopped);
    }
}
