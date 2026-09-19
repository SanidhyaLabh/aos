// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "./interfaces/IOracle.sol";

/**
 * @title SentinelRegistry (v2)
 * @notice Quantitative risk & protection state machine for Origin // ASO v2.
 * @dev Manages a 6-state machine:
 * FRESH → WATCH → STALE → DISPUTED → PROTECTIVE → RECOVERING
 * Adjusts lending debt ceilings and records specific trigger causes.
 */
contract SentinelRegistry {
    enum RiskState { FRESH, WATCH, STALE, DISPUTED, PROTECTIVE, RECOVERING }

    struct StateLogEntry {
        RiskState oldState;
        RiskState newState;
        uint256 timestamp;
        string trigger;
    }

    // --- Immutable References ---
    IOracle public oracle;           // ASOAdapter
    address public governance;
    address public riskEngine;

    // --- State Machine ---
    RiskState public currentState;
    uint256 public lastCheckTimestamp;
    uint256 public stateChangedAt;
    string public currentTrigger;

    // --- Debt Ceiling ---
    uint256 public debtCeiling;
    uint256 public baseCeiling;      // The "full health" ceiling ($500k base)

    // --- Recovery ---
    uint256 public recoveryStreak;
    uint256 public constant REQUIRED_RECOVERY_STREAK = 3;

    // --- History ---
    StateLogEntry[] public stateLog;
    uint256 public totalChecks;

    // --- Events ---
    event StateChanged(RiskState indexed oldState, RiskState indexed newState, uint256 timestamp, string trigger);
    event CeilingCapped(uint256 oldCeiling, uint256 newCeiling, string reason);
    event CheckPerformed(uint256 indexed checkId, RiskState resultState, uint256 price, bool valid, string trigger);

    modifier onlyAuthorized() {
        require(msg.sender == governance || msg.sender == riskEngine, "Sentinel: not-authorized");
        _;
    }

    modifier onlyGov() {
        require(msg.sender == governance, "Sentinel: not-governance");
        _;
    }

    constructor(address _oracle, uint256 _baseCeiling) {
        governance = msg.sender;
        oracle = IOracle(_oracle);
        baseCeiling = _baseCeiling;
        debtCeiling = _baseCeiling;
        currentState = RiskState.FRESH;
        currentTrigger = "Genesis: SentinelRegistry v2 deployed";
        lastCheckTimestamp = block.timestamp;
        stateChangedAt = block.timestamp;

        stateLog.push(StateLogEntry({
            oldState: RiskState.FRESH,
            newState: RiskState.FRESH,
            timestamp: block.timestamp,
            trigger: currentTrigger
        }));
    }

    function setRiskEngine(address _riskEngine) external onlyGov {
        riskEngine = _riskEngine;
    }

    /**
     * @notice External signal from Risk Engine or Attestation Pipeline (e.g. cost-gate or velocity alert)
     */
    function updateRiskSignal(RiskState targetState, string calldata trigger) external onlyAuthorized {
        RiskState oldState = currentState;
        if (oldState == RiskState.DISPUTED && targetState != RiskState.RECOVERING) {
            // DISPUTED can only be exited via resolve()
            return;
        }

        if (targetState == RiskState.PROTECTIVE) {
            _transitionState(oldState, RiskState.PROTECTIVE, trigger);
            _setCeiling((baseCeiling * 30) / 100, "PROTECTIVE: Cost-gate failure; ceiling capped at 30%");
            recoveryStreak = 0;
        } else if (targetState == RiskState.WATCH) {
            _transitionState(oldState, RiskState.WATCH, trigger);
            _setCeiling((baseCeiling * 80) / 100, "WATCH: Velocity/TWAP soft threshold; ceiling at 80%");
        } else if (targetState == RiskState.DISPUTED) {
            _transitionState(oldState, RiskState.DISPUTED, trigger);
            _setCeiling(0, "DISPUTED: Vault or consensus breach; ceiling zeroed");
            recoveryStreak = 0;
        } else if (targetState == RiskState.STALE) {
            _transitionState(oldState, RiskState.STALE, trigger);
            _setCeiling((baseCeiling * 50) / 100, "STALE: Source offline / staleness breach; ceiling at 50%");
            recoveryStreak = 0;
        }
    }

    /**
     * @notice Periodic health evaluation
     */
    function checkAndUpdate() external returns (RiskState oldState, RiskState newState) {
        totalChecks++;
        lastCheckTimestamp = block.timestamp;

        (uint256 price, bool valid) = oracle.read();
        oldState = currentState;

        if (currentState == RiskState.DISPUTED) {
            newState = RiskState.DISPUTED;
            emit CheckPerformed(totalChecks, newState, price, valid, currentTrigger);
            return (oldState, newState);
        }

        if (valid) {
            if (currentState == RiskState.FRESH) {
                newState = RiskState.FRESH;
                recoveryStreak = 0;
            } else if (currentState == RiskState.RECOVERING) {
                recoveryStreak++;
                if (recoveryStreak >= REQUIRED_RECOVERY_STREAK) {
                    newState = RiskState.FRESH;
                    recoveryStreak = 0;
                    currentTrigger = "Full recovery: 3/3 healthy checks";
                    _setCeiling(baseCeiling, "Ceiling restored to 100%");
                } else {
                    newState = RiskState.RECOVERING;
                    currentTrigger = "Recovering: consecutive healthy check";
                    uint256 partialCeiling = (baseCeiling * (25 + (25 * recoveryStreak))) / 100;
                    _setCeiling(partialCeiling, "Recovery progress: ceiling partially restored");
                }
            } else if (currentState == RiskState.STALE || currentState == RiskState.PROTECTIVE || currentState == RiskState.WATCH) {
                // Begin recovery from adverse states
                newState = RiskState.RECOVERING;
                recoveryStreak = 1;
                currentTrigger = "Entering recovery: first healthy check";
                _setCeiling((baseCeiling * 50) / 100, "Entering recovery: ceiling at 50%");
            }
        } else {
            // Oracle read is invalid / stale
            newState = RiskState.STALE;
            recoveryStreak = 0;
            currentTrigger = "Stale attestation (freshness check elapsed > 60s)";
            _setCeiling((baseCeiling * 50) / 100, "Oracle stale: ceiling halved");
        }

        if (oldState != newState) {
            _transitionState(oldState, newState, currentTrigger);
        }

        emit CheckPerformed(totalChecks, newState, price, valid, currentTrigger);
        return (oldState, newState);
    }

    function dispute(string calldata reason) external onlyGov {
        RiskState oldState = currentState;
        _transitionState(oldState, RiskState.DISPUTED, reason);
        _setCeiling(0, "DISPUTED: ceiling zeroed");
        recoveryStreak = 0;
    }

    function resolve(string calldata reason) external onlyGov {
        require(currentState == RiskState.DISPUTED, "Sentinel: not-disputed");
        _transitionState(RiskState.DISPUTED, RiskState.RECOVERING, reason);
        recoveryStreak = 0;
        _setCeiling((baseCeiling * 25) / 100, "Dispute resolved: ceiling at 25% pending recovery");
    }

    function setBaseCeiling(uint256 _newBase) external onlyGov {
        baseCeiling = _newBase;
    }

    function setOracle(address _newOracle) external onlyGov {
        oracle = IOracle(_newOracle);
    }

    // --- View Functions ---

    function stateLogLength() external view returns (uint256) {
        return stateLog.length;
    }

    function getStateLog(uint256 index) external view returns (
        RiskState oldState,
        RiskState newState,
        uint256 timestamp,
        string memory trigger
    ) {
        require(index < stateLog.length, "Sentinel: index-out-of-bounds");
        StateLogEntry storage entry = stateLog[index];
        return (entry.oldState, entry.newState, entry.timestamp, entry.trigger);
    }

    function getRecentLogs(uint256 count) external view returns (StateLogEntry[] memory) {
        uint256 len = stateLog.length;
        if (count > len) count = len;
        StateLogEntry[] memory result = new StateLogEntry[](count);
        for (uint256 i = 0; i < count; i++) {
            result[i] = stateLog[len - count + i];
        }
        return result;
    }

    // --- Internal Helpers ---

    function _transitionState(RiskState oldState, RiskState newState, string memory trigger) internal {
        currentState = newState;
        currentTrigger = trigger;
        stateChangedAt = block.timestamp;
        stateLog.push(StateLogEntry({
            oldState: oldState,
            newState: newState,
            timestamp: block.timestamp,
            trigger: trigger
        }));
        emit StateChanged(oldState, newState, block.timestamp, trigger);
    }

    function _setCeiling(uint256 newCeiling, string memory reason) internal {
        uint256 oldCeiling = debtCeiling;
        if (oldCeiling != newCeiling) {
            debtCeiling = newCeiling;
            emit CeilingCapped(oldCeiling, newCeiling, reason);
        }
    }
}
