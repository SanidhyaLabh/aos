// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

interface IToyLendingMarket {
    function effectiveDebtCeiling() external view returns (uint256);
    function totalDebt() external view returns (uint256);
}

interface IRiskEngine {
    function gamma() external view returns (uint256);
}

/**
 * @title FrictionEngine (Dual-Horizon Friction Engine — DHFE)
 * @notice Computes instantaneous and cumulative structuring-resistant borrow friction.
 * @dev Formulas ported from friction_engine.py:
 *      1. Instantaneous friction: f_inst(x) = phi(x / (Gamma - D))
 *      2. Convex friction curve: phi(u) = u^k_phi
 *      3. EWMA cumulative exposure: E_addr(t) = lambda * E_addr(t-1) + (1 - lambda) * x_t
 *      4. Cumulative friction: f_cum(t) = phi(E_addr(t) / Gamma_addr), Gamma_addr = Gamma / N_active
 *      5. Combined friction (Noisy-OR): f_final = f_inst + f_cum - (f_inst * f_cum)
 *      6. Effective rate: effective_rate = base_rate * (1 + beta * f_final)
 *
 * NOTE ON k_phi:
 * In this on-chain implementation, k_phi is constrained to positive integer values (default 3)
 * for gas efficiency and overflow safety. This is a deliberate on-chain approximation of the
 * off-chain Python reference.
 */
contract FrictionEngine {
    address public governance;
    address public lendingMarket;
    address public riskEngine;

    // Configurable parameters (matching defaults in friction_engine.py)
    uint256 public lambdaWad = 950000000000000000;  // DEFAULT_LAMBDA = 0.95 (18 decimals)
    uint256 public kPhi = 3;                         // DEFAULT_K_PHI = 3
    uint256 public betaWad = 1500000000000000000;   // DEFAULT_BETA = 1.5 (18 decimals)
    uint256 public nActiveBorrowers = 50;            // Target active borrower partition
    uint256 public fallbackGamma = 500000 ether;     // $500,000 fallback debt ceiling

    // Per-address EWMA cumulative exposure (in 18-decimal fixed-point)
    mapping(address => uint256) public ewmaExposure;

    event ParametersUpdated(
        uint256 lambdaWad,
        uint256 kPhi,
        uint256 betaWad,
        uint256 nActiveBorrowers
    );
    event ExposureUpdated(address indexed borrower, uint256 oldExposure, uint256 newExposure);
    event LendingMarketSet(address indexed newLendingMarket);
    event RiskEngineSet(address indexed newRiskEngine);
    event FallbackGammaSet(uint256 newFallbackGamma);

    modifier onlyGov() {
        require(msg.sender == governance, "FrictionEngine: not-governance");
        _;
    }

    modifier onlyAuthorized() {
        require(
            msg.sender == lendingMarket || msg.sender == governance,
            "FrictionEngine: not-authorized"
        );
        _;
    }

    constructor() {
        governance = msg.sender;
    }

    function setGovernance(address _gov) external onlyGov {
        require(_gov != address(0), "FrictionEngine: zero-address");
        governance = _gov;
    }

    function setLendingMarket(address _market) external onlyGov {
        lendingMarket = _market;
        emit LendingMarketSet(_market);
    }

    function setRiskEngine(address _engine) external onlyGov {
        riskEngine = _engine;
        emit RiskEngineSet(_engine);
    }

    function setFallbackGamma(uint256 _gamma) external onlyGov {
        fallbackGamma = _gamma;
        emit FallbackGammaSet(_gamma);
    }

    function setParameters(
        uint256 _lambdaWad,
        uint256 _kPhi,
        uint256 _betaWad,
        uint256 _nActiveBorrowers
    ) external onlyGov {
        require(_lambdaWad < 1e18, "FrictionEngine: lambda must be < 1.0");
        require(_kPhi >= 1 && _kPhi <= 10, "FrictionEngine: k_phi out of range");
        require(_nActiveBorrowers > 0, "FrictionEngine: nActiveBorrowers must be > 0");

        lambdaWad = _lambdaWad;
        kPhi = _kPhi;
        betaWad = _betaWad;
        nActiveBorrowers = _nActiveBorrowers;

        emit ParametersUpdated(_lambdaWad, _kPhi, _betaWad, _nActiveBorrowers);
    }

    /**
     * @notice Convex friction function phi(u) = u^k_phi.
     * @param u Utilization ratio in Wad [0, 1e18].
     * @return phiVal Resulting friction ratio in Wad [0, 1e18].
     */
    function phi(uint256 u) public view returns (uint256 phiVal) {
        if (u >= 1e18) return 1e18;
        if (u == 0) return 0;

        uint256 res = 1e18;
        for (uint256 i = 0; i < kPhi; i++) {
            res = (res * u) / 1e18;
        }
        return res;
    }

    /**
     * @notice Resolves the current protocol Gamma (debt ceiling) and total debt D.
     */
    function getGammaAndDebt() public view returns (uint256 gammaVal, uint256 debtVal) {
        if (lendingMarket != address(0)) {
            try IToyLendingMarket(lendingMarket).effectiveDebtCeiling() returns (uint256 c) {
                gammaVal = c;
            } catch {
                gammaVal = fallbackGamma;
            }
            try IToyLendingMarket(lendingMarket).totalDebt() returns (uint256 d) {
                debtVal = d;
            } catch {
                debtVal = 0;
            }
        } else if (riskEngine != address(0)) {
            try IRiskEngine(riskEngine).gamma() returns (uint256 g) {
                gammaVal = g;
            } catch {
                gammaVal = fallbackGamma;
            }
            debtVal = 0;
        } else {
            gammaVal = fallbackGamma;
            debtVal = 0;
        }

        if (gammaVal == 0) gammaVal = fallbackGamma;
    }

    /**
     * @notice Computes instantaneous friction f_inst(x) = phi(x / (Gamma - D)).
     */
    function instantaneousFriction(
        uint256 x,
        uint256 gammaVal,
        uint256 debtVal
    ) public view returns (uint256) {
        uint256 headroom = gammaVal > debtVal ? (gammaVal - debtVal) : 1;
        uint256 u = (x * 1e18) / headroom;
        return phi(u);
    }

    /**
     * @notice Computes cumulative friction f_cum(t) = phi(E_addr(t) / Gamma_addr).
     */
    function cumulativeFriction(
        uint256 projectedExposure,
        uint256 gammaVal
    ) public view returns (uint256) {
        uint256 nActive = nActiveBorrowers > 0 ? nActiveBorrowers : 1;
        uint256 gammaAddr = gammaVal / nActive;
        if (gammaAddr == 0) gammaAddr = 1;

        uint256 u = (projectedExposure * 1e18) / gammaAddr;
        return phi(u);
    }

    /**
     * @notice Noisy-OR combination: f_final = f_inst + f_cum - (f_inst * f_cum)
     */
    function combinedFriction(uint256 fInst, uint256 fCum) public pure returns (uint256) {
        uint256 cross = (fInst * fCum) / 1e18;
        uint256 sum = fInst + fCum;
        if (sum <= cross) return 0;
        uint256 fFinal = sum - cross;
        return fFinal > 1e18 ? 1e18 : fFinal;
    }

    /**
     * @notice Pure view of what friction signals will be produced for a given borrow size x.
     * @dev Reflects projected exposure including this tx, matching friction_engine.py lines 132-137.
     */
    function computeFriction(
        address borrower,
        uint256 x
    ) public view returns (uint256 fInst, uint256 fCum, uint256 fFinal) {
        (uint256 gammaVal, uint256 debtVal) = getGammaAndDebt();

        // 1. Instantaneous friction based on pre-update headroom
        fInst = instantaneousFriction(x, gammaVal, debtVal);

        // 2. Cumulative friction based on projected EWMA exposure including this tx
        uint256 prevExp = ewmaExposure[borrower];
        uint256 projectedExp = (lambdaWad * prevExp + (1e18 - lambdaWad) * x) / 1e18;
        fCum = cumulativeFriction(projectedExp, gammaVal);

        // 3. Combined Noisy-OR
        fFinal = combinedFriction(fInst, fCum);
    }

    /**
     * @notice Converts friction into an effective rate: effective_rate = base_rate * (1 + beta * f_final)
     */
    function effectiveRate(uint256 baseRate, uint256 fFinal) public view returns (uint256) {
        uint256 rateIncrease = (baseRate * ((betaWad * fFinal) / 1e18)) / 1e18;
        return baseRate + rateIncrease;
    }

    /**
     * @notice Internal EWMA state transition: E(t) = lambda * E(t-1) + (1 - lambda) * x
     */
    function _updateExposure(address borrower, uint256 amount) internal returns (uint256 newExp) {
        uint256 prev = ewmaExposure[borrower];
        newExp = (lambdaWad * prev + (1e18 - lambdaWad) * amount) / 1e18;
        ewmaExposure[borrower] = newExp;
        emit ExposureUpdated(borrower, prev, newExp);
    }

    /**
     * @notice Updates borrower EWMA exposure upon successful borrow.
     * @dev Only callable by the connected lending market or governance.
     */
    function updateExposure(
        address borrower,
        uint256 amount
    ) external onlyAuthorized returns (uint256) {
        return _updateExposure(borrower, amount);
    }
}
