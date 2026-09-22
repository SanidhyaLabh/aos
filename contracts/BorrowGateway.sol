// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "./interfaces/IOriginOracle.sol";

interface ISentinelRegistry {
    function currentState() external view returns (uint8);
}

interface IExposureBucket {
    function consumeCapacity(uint256 amount) external returns (uint256 remainingCapacity);
    function getAvailableCapacity() external view returns (uint256);
}

interface ILendingMarket {
    function borrowFromGateway(address borrower, uint256 amount, uint256 oraclePrice) external returns (uint256);
}

/**
 * @title BorrowGateway (ORIGIN — Single Atomic Credit Origination Gateway)
 * @notice Canonical entry point for all debt origination across ORIGIN-secured lending markets.
 * @dev Enforces the critical path within a single atomic transaction:
 * 1. Oracle Freshness & Health Verification
 * 2. Sentinel Risk-State Verification
 * 3. Market-level EEG Capacity Check & Consumption
 * 4. Risk-Group EEG Capacity Check & Consumption
 * 5. Global EEG Capacity Check & Consumption
 * 6. Forwarding of authorized debt creation to the underlying lending market
 *
 * If ANY condition fails at any step, the ENTIRE transaction reverts and all capacity consumptions roll back.
 */
contract BorrowGateway {
    address public governance;
    address public emergencyGuardian;

    struct MarketConfig {
        bytes32 assetId;
        address oracle;
        address sentinel;
        address marketGuard;
        address riskGroupGuard;
        address globalGuard;
        bool active;
    }

    // market contract address => MarketConfig
    mapping(address => MarketConfig) public marketConfigs;

    // Custom errors
    error MarketNotConfigured(address market);
    error OracleUnhealthy(bytes32 assetId, uint8 status);
    error OraclePriceZero();
    error SentinelStateBlocked(uint8 state);
    error Unauthorized();
    error InvalidParameter(string reason);

    event MarketRegistered(
        address indexed market,
        bytes32 indexed assetId,
        address oracle,
        address sentinel,
        address marketGuard,
        address riskGroupGuard,
        address globalGuard
    );
    event MarketStatusUpdated(address indexed market, bool active);
    event BorrowExecuted(
        address indexed borrower,
        address indexed market,
        uint256 amount,
        uint256 oraclePrice,
        uint256 marketCapRemaining,
        uint256 groupCapRemaining,
        uint256 globalCapRemaining
    );
    event GovernanceTransferred(address indexed previousGov, address indexed newGov);

    modifier onlyGov() {
        if (msg.sender != governance) revert Unauthorized();
        _;
    }

    constructor() {
        governance = msg.sender;
        emergencyGuardian = msg.sender;
    }

    function setGovernance(address _newGov) external onlyGov {
        if (_newGov == address(0)) revert InvalidParameter("Zero address");
        emit GovernanceTransferred(governance, _newGov);
        governance = _newGov;
    }

    function setEmergencyGuardian(address _guardian) external onlyGov {
        emergencyGuardian = _guardian;
    }

    function registerMarket(
        address market,
        bytes32 assetId,
        address oracle,
        address sentinel,
        address marketGuard,
        address riskGroupGuard,
        address globalGuard
    ) external onlyGov {
        if (market == address(0)) revert InvalidParameter("Zero market address");
        if (oracle == address(0)) revert InvalidParameter("Zero oracle address");
        if (marketGuard == address(0)) revert InvalidParameter("Zero market guard address");
        if (globalGuard == address(0)) revert InvalidParameter("Zero global guard address");

        marketConfigs[market] = MarketConfig({
            assetId: assetId,
            oracle: oracle,
            sentinel: sentinel,
            marketGuard: marketGuard,
            riskGroupGuard: riskGroupGuard,
            globalGuard: globalGuard,
            active: true
        });

        emit MarketRegistered(
            market,
            assetId,
            oracle,
            sentinel,
            marketGuard,
            riskGroupGuard,
            globalGuard
        );
    }

    function setMarketActive(address market, bool active) external onlyGov {
        if (marketConfigs[market].oracle == address(0)) revert MarketNotConfigured(market);
        marketConfigs[market].active = active;
        emit MarketStatusUpdated(market, active);
    }

    /**
     * @notice Canonical atomic borrow function.
     * @param market Address of the target lending pool.
     * @param amount Desired borrow amount in debt units (Wad).
     * @return oraclePrice Verified oracle price used for collateral evaluation.
     */
    function borrow(address market, uint256 amount) external returns (uint256 oraclePrice) {
        if (amount == 0) revert InvalidParameter("Zero borrow amount");

        MarketConfig memory cfg = marketConfigs[market];
        if (!cfg.active) revert MarketNotConfigured(market);

        // 1. Verify Oracle Health & Freshness
        IOriginOracle.OracleStatus status;
        uint256 updatedAt;
        (oraclePrice, updatedAt, status) = IOriginOracle(cfg.oracle).getPrice(cfg.assetId);

        if (status != IOriginOracle.OracleStatus.FRESH) {
            revert OracleUnhealthy(cfg.assetId, uint8(status));
        }
        if (oraclePrice == 0) revert OraclePriceZero();

        // 2. Verify Sentinel Risk State (if wired)
        if (cfg.sentinel != address(0)) {
            uint8 sState = ISentinelRegistry(cfg.sentinel).currentState();
            // States: 0=FRESH/NORMAL, 1=WATCH/DEGRADED, 2=STALE, 3=DISPUTED, 4=PROTECTIVE/GUARDED, 5=BLOCKED
            // In BLOCKED state, new gross borrow is strictly disallowed
            if (sState == 5) {
                revert SentinelStateBlocked(sState);
            }
        }

        // 3. Atomically consume Market EEG capacity
        uint256 marketCapRemaining = IExposureBucket(cfg.marketGuard).consumeCapacity(amount);

        // 4. Atomically consume Risk-Group EEG capacity (if configured for this asset class)
        uint256 groupCapRemaining = 0;
        if (cfg.riskGroupGuard != address(0)) {
            groupCapRemaining = IExposureBucket(cfg.riskGroupGuard).consumeCapacity(amount);
        }

        // 5. Atomically consume Global EEG capacity (protocol-wide systemic backstop)
        uint256 globalCapRemaining = IExposureBucket(cfg.globalGuard).consumeCapacity(amount);

        // 6. Execute debt origination in the underlying lending market
        ILendingMarket(market).borrowFromGateway(msg.sender, amount, oraclePrice);

        emit BorrowExecuted(
            msg.sender,
            market,
            amount,
            oraclePrice,
            marketCapRemaining,
            groupCapRemaining,
            globalCapRemaining
        );

        return oraclePrice;
    }

    /**
     * @notice View function for frontend pre-flight validation.
     * Checks if a borrow amount can pass all 3 EEG layers simultaneously.
     */
    function canBorrow(address market, uint256 amount)
        external
        view
        returns (
            bool allowed,
            uint256 marketAvail,
            uint256 groupAvail,
            uint256 globalAvail,
            string memory revertReason
        )
    {
        MarketConfig memory cfg = marketConfigs[market];
        if (!cfg.active) {
            return (false, 0, 0, 0, "Market inactive or not configured");
        }

        (, , IOriginOracle.OracleStatus status) = IOriginOracle(cfg.oracle).getPrice(cfg.assetId);
        if (status != IOriginOracle.OracleStatus.FRESH) {
            return (false, 0, 0, 0, "Oracle unhealthy or stale");
        }

        if (cfg.sentinel != address(0)) {
            uint8 sState = ISentinelRegistry(cfg.sentinel).currentState();
            if (sState == 5) {
                return (false, 0, 0, 0, "Sentinel state blocked");
            }
        }

        marketAvail = IExposureBucket(cfg.marketGuard).getAvailableCapacity();
        if (amount > marketAvail) {
            return (false, marketAvail, 0, 0, "Exceeds market capacity");
        }

        if (cfg.riskGroupGuard != address(0)) {
            groupAvail = IExposureBucket(cfg.riskGroupGuard).getAvailableCapacity();
            if (amount > groupAvail) {
                return (false, marketAvail, groupAvail, 0, "Exceeds risk group capacity");
            }
        }

        globalAvail = IExposureBucket(cfg.globalGuard).getAvailableCapacity();
        if (amount > globalAvail) {
            return (false, marketAvail, groupAvail, globalAvail, "Exceeds global capacity");
        }

        return (true, marketAvail, groupAvail, globalAvail, "");
    }
}
