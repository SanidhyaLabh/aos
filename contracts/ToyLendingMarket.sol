// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "./interfaces/IOracle.sol";

interface ISentinel {
    function debtCeiling() external view returns (uint256);
    function currentState() external view returns (uint8);
}

interface IRiskEngine {
    function gamma() external view returns (uint256);
    function epochGrowthCap() external view returns (uint256);
}

/**
 * @title ToyLendingMarket (v2 / v3.1)
 * @notice Downstream credit facility with bounded-loss epoch caps & cost-gated pricing.
 * @dev Implements:
 * 1. Hard maximum borrow growth per epoch (epoch loss budget / epoch growth cap)
 * 2. Dynamic cost-anchored debt ceiling (Gamma = k * C_net(mRef) / mRef)
 * 3. Sentinel protective state enforcement
 * 4. Ungated repayments in every state
 */
contract ToyLendingMarket {
    IOracle public oracle;
    string public oracleType; // "VanillaOSM" or "ASOAdapter"
    address public sentinel;
    address public riskEngine;
    address public governance;

    uint256 public constant LTV_BPS = 8000;              // 80.00% Max Loan-to-Value
    uint256 public constant LIQUIDATION_BPS = 8500;       // 85.00% Liquidation threshold
    uint256 public constant BPS_DENOMINATOR = 10000;

    // Configured debt ceiling
    uint256 public configuredDebtCeiling = 1000000 ether; // $1,000,000 baseline ceiling

    // Epoch loss budget: max USD borrowed per address per epoch
    uint256 public maxBorrowGrowthPerEpoch = 50000 ether; // $50,000 USD per epoch fallback
    uint256 public epochDuration = 300;                  // 300 seconds (5 min) epoch

    struct Position {
        uint256 collateralAmount; // 18 decimals (e.g. tokenized RWA units)
        uint256 debtAmount;       // 18 decimals (USD stablecoin debt)
    }

    mapping(address => Position) public positions;
    // user => epochId => borrowedAmount
    mapping(address => mapping(uint256 => uint256)) public borrowedInEpoch;

    uint256 public totalCollateral;
    uint256 public totalDebt;

    event CollateralDeposited(address indexed user, uint256 amount);
    event CollateralWithdrawn(address indexed user, uint256 amount);
    event Borrowed(address indexed user, uint256 amount, uint256 oraclePriceUsed, uint256 epoch);
    event Repaid(address indexed user, uint256 amount);
    event OracleUpdated(address indexed newOracle, string oracleType);
    event EpochCapUpdated(uint256 newCap, uint256 newDuration);

    modifier onlyGov() {
        require(msg.sender == governance, "Lending: not-governance");
        _;
    }

    constructor(address _oracle, string memory _oracleType) {
        governance = msg.sender;
        oracle = IOracle(_oracle);
        oracleType = _oracleType;
    }

    function setOracle(address _newOracle, string memory _oracleType) external onlyGov {
        oracle = IOracle(_newOracle);
        oracleType = _oracleType;
        emit OracleUpdated(_newOracle, _oracleType);
    }

    function setSentinel(address _sentinel) external onlyGov {
        sentinel = _sentinel;
    }

    function setRiskEngine(address _riskEngine) external onlyGov {
        riskEngine = _riskEngine;
    }

    function setConfiguredDebtCeiling(uint256 _ceiling) external onlyGov {
        configuredDebtCeiling = _ceiling;
    }

    function setEpochCap(uint256 _newCap, uint256 _newDuration) external onlyGov {
        maxBorrowGrowthPerEpoch = _newCap;
        epochDuration = _newDuration;
        emit EpochCapUpdated(_newCap, _newDuration);
    }

    function currentEpoch() public view returns (uint256) {
        return block.timestamp / epochDuration;
    }

    function getBorrowedThisEpoch(address user) external view returns (uint256) {
        return borrowedInEpoch[user][currentEpoch()];
    }

    function depositCollateral(uint256 amount) external {
        require(amount > 0, "Lending: zero-deposit");
        positions[msg.sender].collateralAmount += amount;
        totalCollateral += amount;
        emit CollateralDeposited(msg.sender, amount);
    }

    /**
     * @notice Effective dynamic ceiling: min(configuredDebtCeiling, Gamma)
     */
    function effectiveDebtCeiling() public view returns (uint256) {
        uint256 ceiling = configuredDebtCeiling;
        if (riskEngine != address(0)) {
            uint256 dynamicCeiling = IRiskEngine(riskEngine).gamma();
            if (dynamicCeiling < ceiling) {
                ceiling = dynamicCeiling;
            }
        }
        if (sentinel != address(0)) {
            uint256 sentCeiling = ISentinel(sentinel).debtCeiling();
            if (sentCeiling < ceiling) {
                ceiling = sentCeiling;
            }
        }
        return ceiling;
    }

    /**
     * @notice Active epoch growth cap: g * Gamma (or configured fallback)
     */
    function effectiveEpochGrowthCap() public view returns (uint256) {
        if (riskEngine != address(0)) {
            return IRiskEngine(riskEngine).epochGrowthCap();
        }
        return maxBorrowGrowthPerEpoch;
    }

    /**
     * @notice Borrows USD against posted RWA collateral with epoch loss budget & ceiling checks.
     * @param amount USD amount to borrow
     */
    function borrow(uint256 amount) external returns (uint256 oraclePrice) {
        require(amount > 0, "Lending: zero-borrow");
        Position storage pos = positions[msg.sender];
        require(pos.collateralAmount > 0, "Lending: no-collateral");

        // Sentinel state check: PROTECTIVE state reverts
        if (sentinel != address(0)) {
            uint8 sState = ISentinel(sentinel).currentState();
            // RiskState enum: 0=FRESH, 1=WATCH, 2=STALE, 3=DISPUTED, 4=PROTECTIVE, 5=RECOVERING
            require(sState != 4, "sentinel protective");
        }

        // 1. Query oracle
        bool valid;
        (oraclePrice, valid) = oracle.read();
        require(valid, "Lending: Oracle halted or stale - borrowing paused");
        require(oraclePrice > 0, "Lending: invalid-oracle-price");

        // 2. Epoch growth cap check
        uint256 epoch = currentEpoch();
        uint256 epochCap = effectiveEpochGrowthCap();
        require(
            borrowedInEpoch[msg.sender][epoch] + amount <= epochCap,
            "epoch growth cap"
        );

        // 3. Dynamic cost-anchored ceiling check
        uint256 ceiling = effectiveDebtCeiling();
        require(totalDebt + amount <= ceiling, "cost-anchored ceiling");

        // 4. Calculate collateral capacity: (amount * price * LTV) / 1e18 / 10000
        uint256 collateralValueUsd = (pos.collateralAmount * oraclePrice) / 1e18;
        uint256 maxBorrowUsd = (collateralValueUsd * LTV_BPS) / BPS_DENOMINATOR;

        require(pos.debtAmount + amount <= maxBorrowUsd, "exceeds-borrow-capacity");

        // Update state
        borrowedInEpoch[msg.sender][epoch] += amount;
        pos.debtAmount += amount;
        totalDebt += amount;

        emit Borrowed(msg.sender, amount, oraclePrice, epoch);
        return oraclePrice;
    }

    /**
     * @notice Repayment is completely ungated in every state (crucial DeFi invariant).
     */
    function repay(uint256 amount) external {
        Position storage pos = positions[msg.sender];
        require(amount > 0 && pos.debtAmount >= amount, "Lending: invalid-repay");
        pos.debtAmount -= amount;
        totalDebt -= amount;
        emit Repaid(msg.sender, amount);
    }

    function evaluateRisk(address user, uint256 groundTruthPrice)
        external
        view
        returns (
            uint256 trueCollateralValue,
            uint256 debt,
            uint256 badDebt,
            bool isUnderwater
        )
    {
        Position memory pos = positions[user];
        debt = pos.debtAmount;
        trueCollateralValue = (pos.collateralAmount * groundTruthPrice) / 1e18;

        if (debt > trueCollateralValue) {
            badDebt = debt - trueCollateralValue;
            isUnderwater = true;
        } else {
            badDebt = 0;
            isUnderwater = false;
        }
    }
}
