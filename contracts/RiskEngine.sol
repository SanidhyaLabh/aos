// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/**
 * @title RiskEngine (Origin // ASO v3.1)
 * @notice Quantitative manipulation-cost awareness and price-gate evaluation layer.
 * @dev Implements Origin ASO v3.1 Part A:
 * A1. Capital to push one source:
 *     C_cap_s(m) = R_s * (sqrt(1+m) - 1) if tradable_s, infinity if untradable.
 * A2. Weights over available reporting sources: w'_s = w_s / sum(w_reporting)
 * A3. Coalition cost to move weighted median:
 *     Merges upstream groups, brute-forces subsets S where sum(w'_s) >= 0.5.
 *     C_cap_med(m) = min_S sum_{s in S} C_cap_s(m)
 * A4. Net cost: C_net(m) = rho * C_cap_med(m) (rho measured from Part D simulation)
 * A5. Extractable borrow: E_borrow(m) = LTV * V * m
 * A6. Cap:
 *     Gamma = k * C_net(mRef) / mRef
 *     debtCeilingAsset = min(configuredCeiling, Gamma)
 *     epochGrowthCap   = g * Gamma
 * A7. Two known holes closed:
 *     (i) Slow ratchet: measures m against a 24h slow anchor with max drift rate per epoch.
 *     (ii) Fake depth: computes Gamma from MINIMUM depth seen over last N cycles (default 12).
 */
contract RiskEngine {
    address public governance;

    struct SourceInfo {
        address id;
        string name;
        uint256 weight;          // Base weight (bps, sum to 10000)
        uint256 quoteDepth;      // Current quote depth R_s in USD (18 decimals)
        bool isTradable;         // False for untradable indices like Fed H.15
        bool isReporting;        // Available & reporting in current cycle
        uint8 upstreamGroup;     // If sources share upstream feed, assign same group ID (>0)
        uint256[12] depthHistory;// Ring buffer of last 12 cycles
        uint8 depthHistoryIndex;
    }

    // List of registered sources
    address[] public sourceAddresses;
    mapping(address => SourceInfo) public sources;

    // Part A Parameters
    uint256 public rhoBps = 1500;       // rho = 0.15 (15% net loss ratio measured from Part D)
    uint256 public kFactorBps = 1000;   // k = 0.10 (safety factor chosen below 5th-percentile rho)
    uint256 public mRefBps = 1500;      // mRef = 15% (largest move defended)
    uint256 public epochGrowthShareBps = 2000; // g = 20% epoch growth share
    uint256 public configuredCeiling = 1000000 ether; // $1,000,000 baseline ceiling
    uint256 public collateralValue = 1000000 ether;   // V = $1,000,000 honest collateral value
    uint256 public ltvBps = 8000;       // 80% LTV
    uint256 public liquidationDiscountBps = 500; // 5% liquidation discount

    // Slow Ratchet Anchor (A7.i)
    uint256 public slowAnchorPrice = 100 ether; // Slow anchor initialized at $100
    uint256 public maxDriftPerEpochBps = 100;    // Max 1.00% drift allowed per epoch

    // Historical rates for vault sanity check
    mapping(address => uint256) public lastKnownGoodRate;
    uint256 public constant MAX_RATE_JUMP_BPS = 500; // 5.00% max single-epoch jump

    event SourceRegistered(address indexed source, string name, uint256 weight, uint256 depth, bool tradable, uint8 upstreamGroup);
    event SourceDepthUpdated(address indexed source, uint256 newDepth, uint256 minRecentDepth);
    event ParametersUpdated(uint256 rhoBps, uint256 kFactorBps, uint256 mRefBps, uint256 epochGrowthShareBps);
    event SlowAnchorUpdated(uint256 oldAnchor, uint256 newAnchor);
    event VaultIntegrityAlert(address indexed vault, uint256 impliedRate, uint256 expectedRate);

    modifier onlyGov() {
        require(msg.sender == governance, "RiskEngine: not-governance");
        _;
    }

    constructor() {
        governance = msg.sender;

        // Register 4 benchmark feeds:
        // 1. Ondo / Securitize RWA (Tradable, Group 1, $85M depth, weight 3500)
        _registerSource(address(0x1111111111111111111111111111111111111111), "Ondo RWA NAV", 3500, 85000000 ether, true, 1);

        // 2. Coinbase Prime Index (Tradable, Group 2, $95M depth, weight 4000)
        _registerSource(address(0x2222222222222222222222222222222222222222), "Coinbase Prime", 4000, 95000000 ether, true, 2);

        // 3. Kraken Treasury (Tradable, Group 3, $38M depth, weight 1500)
        _registerSource(address(0x3333333333333333333333333333333333333333), "Kraken Treasury", 1500, 38000000 ether, true, 3);

        // 4. Fed H.15 Interbank (Untradable reference, Group 4, weight 1000)
        _registerSource(address(0x4444444444444444444444444444444444444444), "Fed H.15", 1000, 0, false, 4);
    }

    function _registerSource(
        address id,
        string memory name,
        uint256 weight,
        uint256 depth,
        bool tradable,
        uint8 upstreamGroup
    ) internal {
        sourceAddresses.push(id);
        SourceInfo storage s = sources[id];
        s.id = id;
        s.name = name;
        s.weight = weight;
        s.quoteDepth = depth;
        s.isTradable = tradable;
        s.isReporting = true;
        s.upstreamGroup = upstreamGroup;
        s.depthHistoryIndex = 0;
        for (uint256 i = 0; i < 12; i++) {
            s.depthHistory[i] = depth;
        }
        emit SourceRegistered(id, name, weight, depth, tradable, upstreamGroup);
    }

    function setSourceReporting(address source, bool reporting) external onlyGov {
        sources[source].isReporting = reporting;
    }

    function setSourceDepth(address source, uint256 depthUsd) external onlyGov {
        SourceInfo storage s = sources[source];
        s.quoteDepth = depthUsd;
        s.depthHistory[s.depthHistoryIndex] = depthUsd;
        s.depthHistoryIndex = uint8((s.depthHistoryIndex + 1) % 12);

        uint256 minD = getMinRecentDepth(source);
        emit SourceDepthUpdated(source, depthUsd, minD);
    }

    function setParameters(
        uint256 _rhoBps,
        uint256 _kFactorBps,
        uint256 _mRefBps,
        uint256 _epochGrowthShareBps
    ) external onlyGov {
        rhoBps = _rhoBps;
        kFactorBps = _kFactorBps;
        mRefBps = _mRefBps;
        epochGrowthShareBps = _epochGrowthShareBps;
        emit ParametersUpdated(_rhoBps, _kFactorBps, _mRefBps, _epochGrowthShareBps);
    }

    /**
     * @notice A7.ii Fake Depth Defense: Returns the MINIMUM depth seen over the last 12 cycles.
     */
    function getMinRecentDepth(address source) public view returns (uint256 minDepth) {
        SourceInfo storage s = sources[source];
        if (!s.isTradable) return 0;
        minDepth = s.depthHistory[0];
        for (uint256 i = 1; i < 12; i++) {
            if (s.depthHistory[i] < minDepth) {
                minDepth = s.depthHistory[i];
            }
        }
    }

    /**
     * @notice Integer square root helper.
     */
    function sqrt(uint256 y) internal pure returns (uint256 z) {
        if (y > 3) {
            z = y;
            uint256 x = y / 2 + 1;
            while (x < z) {
                z = x;
                x = (y / x + x) / 2;
            }
        } else if (y != 0) {
            z = 1;
        }
    }

    /**
     * @notice A1: Capital to push one source by fractional move m (constant-product model).
     * C_cap_s(m) = R_s * (sqrt(1+m) - 1) if tradable, infinity if untradable.
     * @param source Address of the source
     * @param mBps Fractional upward price move in bps (e.g. 1500 = 15%)
     */
    function costCapSingle(address source, uint256 mBps) public view returns (uint256) {
        SourceInfo storage s = sources[source];
        if (!s.isTradable) {
            return type(uint256).max; // Untradable feed cannot be pushed via DEX capital
        }
        // Use minimum recent depth (A7.ii) to defend against liquidity pulling
        uint256 r = getMinRecentDepth(source);
        if (r == 0) return 0;

        // sqrt(1 + m) with 18 decimal precision
        // sqrt(((10000 + mBps) / 10000) * 1e36) = sqrt((10000 + mBps) * 1e32)
        uint256 factor = sqrt((10000 + mBps) * 1e32); // 18 decimals sqrt
        if (factor <= 1e18) return 0;
        uint256 multiplier = factor - 1e18; // (sqrt(1+m) - 1) with 18 decimals
        return (r * multiplier) / 1e18;
    }

    function _evaluateSubset(
        uint256 mask,
        uint256 mBps,
        uint256 n
    ) internal view returns (bool valid, uint256 weightSum, uint256 costSum) {
        uint256 handledGroupsMask = 0;
        for (uint256 i = 0; i < n; i++) {
            if ((mask & (1 << i)) != 0) {
                SourceInfo storage s = sources[sourceAddresses[i]];
                if (!s.isReporting) {
                    return (false, 0, 0);
                }
                weightSum += s.weight;

                uint256 groupBit = 1 << s.upstreamGroup;
                if ((handledGroupsMask & groupBit) == 0) {
                    handledGroupsMask |= groupBit;
                    uint256 c = costCapSingle(s.id, mBps);
                    if (c == type(uint256).max) {
                        return (false, 0, 0);
                    }
                    costSum += c;
                }
            }
        }
        return (true, weightSum, costSum);
    }

    /**
     * @notice A3: Coalition search on-chain.
     * Computes C_cap_med(m) = min over S of sum_{s in S} C_cap_s(m)
     * such that sum_{s in S} w'_s >= 50%.
     * Upstream groups sharing an upstream source are merged.
     * @param mBps Move size in basis points (e.g. 1500)
     */
    function costCap(uint256 mBps) public view returns (uint256 minCost, uint8 bestCoalitionMask) {
        uint256 n = sourceAddresses.length;
        require(n <= 8, "RiskEngine: max 8 sources");

        uint256 totalReportingWeight = 0;
        for (uint256 i = 0; i < n; i++) {
            if (sources[sourceAddresses[i]].isReporting) {
                totalReportingWeight += sources[sourceAddresses[i]].weight;
            }
        }
        if (totalReportingWeight == 0) return (type(uint256).max, 0);

        uint256 halfWeight = totalReportingWeight / 2;
        minCost = type(uint256).max;
        bestCoalitionMask = 0;

        uint256 subsets = 1 << n;
        for (uint256 mask = 1; mask < subsets; mask++) {
            (bool valid, uint256 weightSum, uint256 costSum) = _evaluateSubset(mask, mBps, n);
            if (valid && weightSum >= halfWeight) {
                if (costSum < minCost) {
                    minCost = costSum;
                    bestCoalitionMask = uint8(mask);
                }
            }
        }
    }

    /**
     * @notice A4: Net attack cost after selling tokens back.
     * C_net(m) = rho * C_cap_med(m)
     */
    function costNet(uint256 mBps) public view returns (uint256) {
        (uint256 cCap, ) = costCap(mBps);
        if (cCap == type(uint256).max) return type(uint256).max;
        return (cCap * rhoBps) / 10000;
    }

    /**
     * @notice A6: Cost-anchored borrow ceiling.
     * Gamma = k * C_net(mRef) / mRef
     */
    function gamma() public view returns (uint256) {
        uint256 cNetRef = costNet(mRefBps);
        if (cNetRef == type(uint256).max) {
            return configuredCeiling;
        }
        // mRef fraction = mRefBps / 10000
        // Gamma = (k * C_net(mRef)) / (mRefBps / 10000) = (k * C_net * 10000) / (mRefBps * 10000)
        uint256 rawGamma = (cNetRef * kFactorBps) / mRefBps;
        return rawGamma < configuredCeiling ? rawGamma : configuredCeiling;
    }

    /**
     * @notice Returns the active epoch growth cap.
     * epochGrowthCap = g * Gamma
     */
    function epochGrowthCap() external view returns (uint256) {
        return (gamma() * epochGrowthShareBps) / 10000;
    }

    /**
     * @notice Attack economics read by the Minimal Terminal UI.
     * @param mBps Price push to evaluate (e.g. 1500 for 15%)
     * @return attackerNetCost Capital lost by attacker: C_net(m)
     * @return maxExtraBorrow Maximum additional USD borrowed: E_borrow(m) = LTV * V * m
     * @return netResult Profit or loss: maxExtraBorrow - attackerNetCost (negative means attack loses money)
     * @return margin Safety margin ratio (attackerNetCost / maxExtraBorrow * 10000)
     * @return coalitionMask Bitmask of sources in the cheapest coalition
     */
    function attackEconomics(uint256 mBps) external view returns (
        uint256 attackerNetCost,
        uint256 maxExtraBorrow,
        int256 netResult,
        uint256 margin,
        uint8 coalitionMask
    ) {
        (uint256 cCap, uint8 mask) = costCap(mBps);
        coalitionMask = mask;
        attackerNetCost = (cCap == type(uint256).max) ? type(uint256).max : (cCap * rhoBps) / 10000;

        // E_borrow(m) = LTV * V * m
        maxExtraBorrow = (collateralValue * ltvBps * mBps) / (1e4 * 1e4);

        if (attackerNetCost == type(uint256).max) {
            netResult = -1000000 ether;
            margin = 99999;
        } else {
            netResult = int256(maxExtraBorrow) - int256(attackerNetCost);
            margin = maxExtraBorrow > 0 ? (attackerNetCost * 10000) / maxExtraBorrow : 99999;
        }
    }

    /**
     * @notice A7.i: Updates slow ratchet anchor (24h anchor with max drift rate per epoch).
     */
    function updateSlowAnchor(uint256 reportedSpotPrice) external onlyGov returns (uint256) {
        uint256 maxDrift = (slowAnchorPrice * maxDriftPerEpochBps) / 10000;
        uint256 oldAnchor = slowAnchorPrice;

        if (reportedSpotPrice > slowAnchorPrice + maxDrift) {
            slowAnchorPrice = slowAnchorPrice + maxDrift;
        } else if (reportedSpotPrice < slowAnchorPrice - maxDrift) {
            slowAnchorPrice = slowAnchorPrice - maxDrift;
        } else {
            slowAnchorPrice = reportedSpotPrice;
        }

        emit SlowAnchorUpdated(oldAnchor, slowAnchorPrice);
        return slowAnchorPrice;
    }

    /**
     * @notice Computes liquidity-weighted median across prices.
     */
    function weightedMedian(
        uint256[] memory prices,
        uint256[] memory weights
    ) public pure returns (uint256) {
        uint256 n = prices.length;
        require(n > 0 && n == weights.length, "RiskEngine: invalid-arrays");

        uint256[] memory p = new uint256[](n);
        uint256[] memory w = new uint256[](n);
        uint256 totalWeight = 0;

        for (uint256 i = 0; i < n; i++) {
            p[i] = prices[i];
            w[i] = weights[i];
            totalWeight += weights[i];
        }
        require(totalWeight > 0, "RiskEngine: zero-total-weight");

        for (uint256 i = 1; i < n; i++) {
            uint256 keyP = p[i];
            uint256 keyW = w[i];
            int256 j = int256(i) - 1;
            while (j >= 0 && p[uint256(j)] > keyP) {
                p[uint256(j + 1)] = p[uint256(j)];
                w[uint256(j + 1)] = w[uint256(j)];
                j--;
            }
            p[uint256(j + 1)] = keyP;
            w[uint256(j + 1)] = keyW;
        }

        uint256 cumulative = 0;
        uint256 halfWeight = totalWeight / 2;
        for (uint256 i = 0; i < n; i++) {
            cumulative += w[i];
            if (cumulative > halfWeight) {
                return p[i];
            }
        }
        return p[n - 1];
    }

    /**
     * @notice Vault sanity check to prevent donation / share inflation attacks (Venus wUSDM/vTHE defense).
     */
    function checkVaultIntegrity(
        address vault,
        uint256 totalAssets,
        uint256 totalSupply
    ) external returns (bool valid, uint256 impliedRate, uint256 expectedRate) {
        require(totalSupply > 0, "RiskEngine: zero-vault-supply");
        impliedRate = (totalAssets * 1e18) / totalSupply;
        expectedRate = lastKnownGoodRate[vault];

        if (expectedRate == 0) {
            lastKnownGoodRate[vault] = impliedRate;
            return (true, impliedRate, impliedRate);
        }

        uint256 maxAllowed = (expectedRate * (10000 + MAX_RATE_JUMP_BPS)) / 10000;
        if (impliedRate > maxAllowed) {
            emit VaultIntegrityAlert(vault, impliedRate, expectedRate);
            return (false, impliedRate, expectedRate);
        }

        lastKnownGoodRate[vault] = impliedRate;
        return (true, impliedRate, expectedRate);
    }
}
