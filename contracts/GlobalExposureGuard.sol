// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/**
 * @title GlobalExposureGuard (ORIGIN — Global EEG)
 * @notice Protocol-wide top-level token-bucket rate limiter that constrains aggregate gross debt creation.
 * @dev Enforces the protocol-wide invariant:
 * Sum_{all markets} Delta Debt_new <= Global_Capacity_0 + R_global * Delta t.
 *
 * Repayments and liquidations do NOT refill the bucket (Anti-churn invariant).
 * Even if every individual market has remaining local capacity, global gross issuance is strictly bounded.
 */
contract GlobalExposureGuard {
    address public governance;
    address public emergencyGuardian;

    // Token-bucket parameters (18 decimals Wad)
    uint256 public maxCapacity;             // Maximum global bucket burst allowance (e.g. $5,000,000 ether)
    uint256 public refillRatePerSecond;      // Continuous refill rate (e.g. $138.88 ether/sec = $500k/hr)
    uint256 public currentCapacity;          // Currently available global capacity in Wad
    uint256 public lastUpdateTimestamp;      // Timestamp of last capacity replenishment
    uint256 public totalIssued;              // Cumulative gross debt authorized by this guard

    mapping(address => bool) public authorizedCallers; // Authorized BorrowGateways

    // Custom errors
    error GlobalDebtRateLimitExceeded(uint256 requested, uint256 available);
    error Unauthorized();
    error InvalidParameter(string reason);

    event GlobalCapacityConsumed(address indexed caller, uint256 amount, uint256 remainingCapacity, uint256 totalIssued);
    event GlobalCapacityReplenished(uint256 newCapacity, uint256 elapsed);
    event ParametersUpdated(uint256 maxCapacity, uint256 refillRatePerSecond);
    event CallerAuthorizationUpdated(address indexed caller, bool authorized);
    event EmergencyCapacityReduced(uint256 oldCapacity, uint256 newCapacity, string reason);
    event GovernanceTransferred(address indexed previousGov, address indexed newGov);

    modifier onlyGov() {
        if (msg.sender != governance) revert Unauthorized();
        _;
    }

    modifier onlyGuardianOrGov() {
        if (msg.sender != governance && msg.sender != emergencyGuardian) revert Unauthorized();
        _;
    }

    modifier onlyAuthorized() {
        if (!authorizedCallers[msg.sender] && msg.sender != governance) revert Unauthorized();
        _;
    }

    constructor(
        uint256 _maxCapacity,
        uint256 _refillRatePerSecond,
        address _emergencyGuardian
    ) {
        if (_maxCapacity == 0) revert InvalidParameter("Zero capacity");
        if (_refillRatePerSecond == 0) revert InvalidParameter("Zero refill rate");

        governance = msg.sender;
        emergencyGuardian = _emergencyGuardian != address(0) ? _emergencyGuardian : msg.sender;
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

    function setEmergencyGuardian(address _guardian) external onlyGov {
        emergencyGuardian = _guardian;
    }

    function setAuthorizedCaller(address _caller, bool _authorized) external onlyGov {
        if (_caller == address(0)) revert InvalidParameter("Zero address");
        authorizedCallers[_caller] = _authorized;
        emit CallerAuthorizationUpdated(_caller, _authorized);
    }

    /**
     * @notice Governance parameter update with replenishment prior to change.
     */
    function setParameters(uint256 _maxCapacity, uint256 _refillRatePerSecond) external onlyGov {
        if (_maxCapacity == 0) revert InvalidParameter("Zero capacity");
        if (_refillRatePerSecond == 0) revert InvalidParameter("Zero refill rate");

        _replenish();

        maxCapacity = _maxCapacity;
        refillRatePerSecond = _refillRatePerSecond;
        if (currentCapacity > _maxCapacity) {
            currentCapacity = _maxCapacity;
        }

        emit ParametersUpdated(_maxCapacity, _refillRatePerSecond);
    }

    /**
     * @notice Emergency immediate risk reduction without delay.
     * Guardian can only REDUCE capacity, never increase it.
     */
    function emergencyReduceCapacity(uint256 _newCapacity, string calldata reason) external onlyGuardianOrGov {
        _replenish();
        if (_newCapacity >= currentCapacity) {
            revert InvalidParameter("Emergency action can only reduce capacity");
        }
        uint256 oldCapacity = currentCapacity;
        currentCapacity = _newCapacity;
        emit EmergencyCapacityReduced(oldCapacity, _newCapacity, reason);
    }

    /**
     * @notice Replenishes capacity linearly based on elapsed block timestamp.
     */
    function _replenish() internal returns (uint256) {
        uint256 nowTs = block.timestamp;
        if (nowTs > lastUpdateTimestamp) {
            uint256 elapsed = nowTs - lastUpdateTimestamp;
            uint256 replenished = elapsed * refillRatePerSecond;
            uint256 newCap = currentCapacity + replenished;
            if (newCap > maxCapacity) {
                newCap = maxCapacity;
            }
            currentCapacity = newCap;
            lastUpdateTimestamp = nowTs;
            emit GlobalCapacityReplenished(newCap, elapsed);
        }
        return currentCapacity;
    }

    /**
     * @notice Atomically consumes global issuance capacity for a borrow.
     * @param amount Requested new debt origination in Wad.
     * @return remainingCapacity Available global capacity remaining after consumption.
     */
    function consumeCapacity(uint256 amount) external onlyAuthorized returns (uint256 remainingCapacity) {
        uint256 available = _replenish();

        if (amount > available) {
            revert GlobalDebtRateLimitExceeded(amount, available);
        }

        currentCapacity = available - amount;
        totalIssued += amount;
        remainingCapacity = currentCapacity;

        emit GlobalCapacityConsumed(msg.sender, amount, remainingCapacity, totalIssued);
    }

    /**
     * @notice View function returning current available capacity including uncommitted elapsed time.
     */
    function getAvailableCapacity() public view returns (uint256 available) {
        uint256 nowTs = block.timestamp;
        if (nowTs > lastUpdateTimestamp) {
            uint256 elapsed = nowTs - lastUpdateTimestamp;
            uint256 replenished = elapsed * refillRatePerSecond;
            available = currentCapacity + replenished;
            if (available > maxCapacity) {
                available = maxCapacity;
            }
        } else {
            available = currentCapacity;
        }
    }

    /**
     * @notice Estimates seconds required to replenish up to desiredAmount.
     */
    function timeToRefill(uint256 desiredAmount) external view returns (uint256 secondsNeeded) {
        uint256 available = getAvailableCapacity();
        if (desiredAmount <= available) return 0;
        if (desiredAmount > maxCapacity) return type(uint256).max;

        uint256 deficit = desiredAmount - available;
        secondsNeeded = (deficit + refillRatePerSecond - 1) / refillRatePerSecond;
    }
}
