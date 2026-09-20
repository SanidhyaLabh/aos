// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/**
 * @title EconomicExposureGuard (ORIGIN — EEG)
 * @notice On-chain token-bucket rate limiter that constrains aggregate new debt origination.
 * @dev Enforces the core invariant: Delta Debt <= Capacity_0 + R_max * Delta t.
 * Even if an oracle is completely compromised or manipulated, newly created credit
 * cannot exceed available bucket capacity.
 */
contract EconomicExposureGuard {
    address public governance;
    address public market;

    // Token-bucket parameters (18 decimals Wad)
    uint256 public maxCapacity;             // Maximum bucket capacity (e.g. $100,000 ether)
    uint256 public refillRatePerSecond;      // Continuous refill rate (e.g. $27.77 ether/sec = $25k/15min)
    uint256 public currentCapacity;          // Current available capacity in Wad
    uint256 public lastUpdateTimestamp;      // Timestamp of last capacity replenishment

    // Custom errors for gas efficiency and clear reverts
    error DebtRateLimitExceeded(uint256 requested, uint256 available);
    error Unauthorized();
    error InvalidParameter(string reason);

    event CapacityConsumed(address indexed caller, uint256 amount, uint256 remainingCapacity);
    event CapacityReplenished(uint256 newCapacity, uint256 elapsed);
    event ParametersUpdated(uint256 maxCapacity, uint256 refillRatePerSecond);
    event MarketSet(address indexed market);
    event GovernanceTransferred(address indexed previousGov, address indexed newGov);

    modifier onlyGov() {
        if (msg.sender != governance) revert Unauthorized();
        _;
    }

    modifier onlyAuthorized() {
        if (msg.sender != market && msg.sender != governance) revert Unauthorized();
        _;
    }

    /**
     * @param _maxCapacity Maximum protected capacity in Wad (e.g. 100000 ether)
     * @param _refillRatePerSecond Capacity replenishment rate in Wad per second
     */
    constructor(uint256 _maxCapacity, uint256 _refillRatePerSecond) {
        if (_maxCapacity == 0) revert InvalidParameter("Zero capacity");
        if (_refillRatePerSecond == 0) revert InvalidParameter("Zero refill rate");

        governance = msg.sender;
        maxCapacity = _maxCapacity;
        refillRatePerSecond = _refillRatePerSecond;
        currentCapacity = _maxCapacity;
        lastUpdateTimestamp = block.timestamp;

        emit ParametersUpdated(_maxCapacity, _refillRatePerSecond);
    }

    function setGovernance(address _newGov) external onlyGov {
        if (_newGov == address(0)) revert InvalidParameter("Zero address");
        emit GovernanceTransferred(governance, _newGov);
        governance = _newGov;
    }

    function setMarket(address _market) external onlyGov {
        market = _market;
        emit MarketSet(_market);
    }

    function setParameters(uint256 _maxCapacity, uint256 _refillRatePerSecond) external onlyGov {
        if (_maxCapacity == 0) revert InvalidParameter("Zero capacity");
        if (_refillRatePerSecond == 0) revert InvalidParameter("Zero refill rate");

        // Replenish with existing parameters before updating
        _replenish();

        maxCapacity = _maxCapacity;
        refillRatePerSecond = _refillRatePerSecond;
        if (currentCapacity > _maxCapacity) {
            currentCapacity = _maxCapacity;
        }

        emit ParametersUpdated(_maxCapacity, _refillRatePerSecond);
    }

    /**
     * @notice Pure internal capacity replenishment over elapsed time.
     */
    function _replenish() internal returns (uint256) {
        uint256 nowTs = block.timestamp;
        if (nowTs > lastUpdateTimestamp) {
            uint256 elapsed = nowTs - lastUpdateTimestamp;
            uint256 replenishedAmount = elapsed * refillRatePerSecond;
            uint256 newCapacity = currentCapacity + replenishedAmount;
            if (newCapacity > maxCapacity) {
                newCapacity = maxCapacity;
            }
            currentCapacity = newCapacity;
            lastUpdateTimestamp = nowTs;
            emit CapacityReplenished(newCapacity, elapsed);
        }
        return currentCapacity;
    }

    /**
     * @notice Consumes protected borrowing capacity for a new debt origination.
     * @param amount Newly requested borrow amount in Wad.
     * @return remainingCapacity Remaining protected capacity after consumption.
     */
    function consumeCapacity(uint256 amount) external onlyAuthorized returns (uint256 remainingCapacity) {
        uint256 available = _replenish();

        if (amount > available) {
            revert DebtRateLimitExceeded(amount, available);
        }

        currentCapacity = available - amount;
        remainingCapacity = currentCapacity;

        emit CapacityConsumed(msg.sender, amount, remainingCapacity);
    }

    /**
     * @notice View function for frontend pre-flight checks before submitting transactions.
     * @return available Current available capacity including uncommitted elapsed time.
     */
    function getAvailableCapacity() public view returns (uint256 available) {
        uint256 nowTs = block.timestamp;
        if (nowTs > lastUpdateTimestamp) {
            uint256 elapsed = nowTs - lastUpdateTimestamp;
            uint256 replenishedAmount = elapsed * refillRatePerSecond;
            available = currentCapacity + replenishedAmount;
            if (available > maxCapacity) {
                available = maxCapacity;
            }
        } else {
            available = currentCapacity;
        }
    }

    /**
     * @notice Estimates the seconds needed until desired borrow amount becomes available.
     */
    function timeToRefill(uint256 desiredAmount) external view returns (uint256 secondsNeeded) {
        uint256 available = getAvailableCapacity();
        if (desiredAmount <= available) return 0;
        if (desiredAmount > maxCapacity) return type(uint256).max; // Impossible without parameter change

        uint256 deficit = desiredAmount - available;
        secondsNeeded = (deficit + refillRatePerSecond - 1) / refillRatePerSecond;
    }
}
