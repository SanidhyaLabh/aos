// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "../contracts/FrictionEngine.sol";

// Minimal forge-std interface for Foundry compatibility
interface Vm {
    function prank(address) external;
}

contract FrictionEngineTest {
    FrictionEngine public engine;
    address public gov = address(this);
    address public user = address(0x1111);
    address public attacker = address(0x9999);

    function setUp() public {
        engine = new FrictionEngine();
        engine.setFallbackGamma(400000 ether); // Gamma = $400,000
        // Set parameters: lambda = 0.95, k_phi = 3, beta = 1.5, nActive = 50
        engine.setParameters(
            950000000000000000, // 0.95 ether
            3,
            1500000000000000000, // 1.5 ether
            50
        );
    }

    // 1. Single small borrow -> near-zero friction
    function test_single_small_borrow_near_zero_friction() public view {
        uint256 smallBorrow = 2000 ether; // $2,000
        (uint256 fInst, uint256 fCum, uint256 fFinal) = engine.computeFriction(user, smallBorrow);

        // f_inst should be virtually 0 (< 1e12 in Wad)
        require(fInst < 1e12, "f_inst not near zero");
        // f_cum for $2k when Gamma_addr = $400k/50 = $8k: u = 100/8000 = 0.0125, u^3 = ~1.95e-6
        require(fCum < 1e14, "f_cum too high for small borrow");
        require(fFinal < 1e14, "f_final too high for small borrow");

        uint256 baseRate = 0.05 ether; // 5%
        uint256 effRate = engine.effectiveRate(baseRate, fFinal);
        require(effRate >= baseRate && effRate <= baseRate + 1e12, "Rate distorted for honest user");
    }

    // 2. Single large borrow near Gamma-D -> high f_inst
    function test_single_large_borrow_high_f_inst() public view {
        uint256 largeBorrow = 250000 ether; // $250,000 (headroom is $400k)
        (uint256 fInst, uint256 fCum, uint256 fFinal) = engine.computeFriction(attacker, largeBorrow);

        // u = 250/400 = 0.625 -> u^3 = ~0.244 Wad
        require(fInst > 2e17, "f_inst should be high for large borrow");
        require(fFinal >= fInst, "f_final should reflect high f_inst");

        uint256 baseRate = 0.05 ether; // 5%
        uint256 effRate = engine.effectiveRate(baseRate, fFinal);
        require(effRate > baseRate, "Rate must increase significantly for large borrow");
    }

    // 3. CORE STRUCTURING-RESISTANCE TEST:
    // N small borrows in sequence from the same address within a short window
    // -> rising f_cum even though each individual f_inst stays low
    function test_structuring_resistance_rising_f_cum_low_f_inst() public {
        uint256 sliceSize = 10000 ether; // $10,000 per slice
        uint256 prevFCum = 0;
        uint256 prevFFinal = 0;

        for (uint256 i = 1; i <= 10; i++) {
            (uint256 fInst, uint256 fCum, uint256 fFinal) = engine.computeFriction(attacker, sliceSize);

            // Each individual transaction size is small ($10k / $400k = 0.025), so f_inst remains near-zero
            // u = 10k/400k = 1/40, (1/40)^3 = 1/64000 = ~0.0000156 Wad (< 2e13)
            require(fInst < 2e13, "f_inst should remain very low on small slices");

            // But cumulative friction f_cum MUST strictly rise as EWMA accumulates
            if (i > 1) {
                require(fCum > prevFCum, "Structuring resistance violation: f_cum must rise monotonically");
                require(fFinal > prevFFinal, "Structuring resistance violation: f_final must rise monotonically");
            }

            prevFCum = fCum;
            prevFFinal = fFinal;

            // Update on-chain exposure for the next slice
            engine.updateExposure(attacker, sliceSize);
        }

        // After 10 sequential borrows, f_cum should be substantially elevated (> 0.05 Wad)
        require(prevFCum > 5e16, "Structuring resistance: cumulative friction must be significantly elevated");
    }
}
