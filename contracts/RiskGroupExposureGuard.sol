// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/**
 * @title RiskGroupExposureGuard (ORIGIN — Risk-Group EEG)
 * @notice Intermediate token-bucket rate limiter that constrains aggregate gross debt creation
 * across correlated asset classes (e.g., RWA, Crypto, Stablecoin).
 * @dev Enforces the invariant:
 * Sum_{markets in Group} Delta Debt_new <= Group_Capacity_0 + R_group * Delta t.
 */
contract RiskGroupExposureGuard {
    bytes32 public immutable groupId;
    string public groupName;

    address public governance;
    address public emergencyGuardian;

    // Token-bucket parameters (18 decimals Wad)
    uint256 public maxCapacity;
    uint256 public refillRatePerSecond;
    uint256 public currentCapacity;
    uint256 public lastUpdateTimestamp;
    uint256 public totalIssued;

    mapping(address => bool) public authorizedCallers; // Authorized BorrowGateways

    // Custom errors
    error GroupDebtRateLimitExceeded(bytes32 groupId, uint256 requested, uint256 available);
    error Unauthorized();
    error InvalidParameter(string reason);

    event GroupCapacityConsumed(bytes32 indexed groupId, address indexed caller, uint256 amount, uint256 remainingCapacity, uint256 totalIssued);
    event GroupCapacityReplenished(bytes32 indexed groupId, uint256 newCapacity, uint256 elapsed);
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
        bytes32 _groupId,
        string memory _groupName,
        uint256 _maxCapacity,
        uint256 _refillRatePerSecond,
        address _emergencyGuardian
    ) {
        if (_groupId == bytes32(0)) revert InvalidParameter("Zero groupId");
        if (_maxCapacity == 0) revert InvalidParameter("Zero capacity");
        if (_refillRatePerSecond == 0) revert InvalidParameter("Zero refill rate");

        groupId = _groupId;
        groupName = _groupName;
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

    function emergencyReduceCapacity(uint256 _newCapacity, string calldata reason) external onlyGuardianOrGov {
        _replenish();
        if (_newCapacity >= currentCapacity) {
            revert InvalidParameter("Emergency action can only reduce capacity");
        }
        uint256 oldCapacity = currentCapacity;
        currentCapacity = _newCapacity;
        emit EmergencyCapacityReduced(oldCapacity, _newCapacity, reason);
    }

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
            emit GroupCapacityReplenished(groupId, newCap, elapsed);
        }
        return currentCapacity;
    }

    function consumeCapacity(uint256 amount) external onlyAuthorized returns (uint256 remainingCapacity) {
        uint256 available = _replenish();

        if (amount > available) {
            revert GroupDebtRateLimitExceeded(groupId, amount, available);
        }

        currentCapacity = available - amount;
        totalIssued += amount;
        remainingCapacity = currentCapacity;

        emit GroupCapacityConsumed(groupId, msg.sender, amount, remainingCapacity, totalIssued);
    }

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

    function timeToRefill(uint256 desiredAmount) external view returns (uint256 secondsNeeded) {
        uint256 available = getAvailableCapacity();
        if (desiredAmount <= available) return 0;
        if (desiredAmount > maxCapacity) return type(uint256).max;

        uint256 deficit = desiredAmount - available;
        secondsNeeded = (deficit + refillRatePerSecond - 1) / refillRatePerSecond;
    }
}
