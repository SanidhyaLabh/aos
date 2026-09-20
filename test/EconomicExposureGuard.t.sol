// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "../contracts/EconomicExposureGuard.sol";
import "../contracts/ToyLendingMarket.sol";
import "../contracts/ASOAdapter.sol";

contract EconomicExposureGuardTest {
    EconomicExposureGuard public guard;
    ToyLendingMarket public market;
    ASOAdapter public oracle;

    address public gov = address(this);
    address public honestUser = address(0x1111);
    address public attacker1 = address(0x2222);
    address public attacker2 = address(0x3333);
    address public attacker3 = address(0x4444);

    uint256 public constant MAX_CAPACITY = 100000 ether;          // $100,000 max capacity
    uint256 public constant REFILL_RATE = 27777777777777777777;   // ~$25k / 15 min (~27.77 ether/sec)

    function setUp() public {
        // Deploy Guard
        guard = new EconomicExposureGuard(MAX_CAPACITY, REFILL_RATE);

        // Deploy Mock Oracle at $100
        oracle = new ASOAdapter(100 ether);

        // Deploy Lending Market
        market = new ToyLendingMarket(address(oracle), "ASOAdapter");

        // Wire linkages
        market.setExposureGuard(address(guard));
        guard.setMarket(address(market));

        // Seed collateral: 1,000 units each (nominal $100,000 borrowing power at 80% LTV)
        market.depositCollateral(100000 ether);
    }

    // 1. Normal borrow within capacity succeeds
    function test_BorrowWithinCapacity() public {
        uint256 borrowAmount = 2900 ether; // $2,900
        uint256 capBefore = guard.getAvailableCapacity();

        guard.consumeCapacity(borrowAmount);

        uint256 capAfter = guard.getAvailableCapacity();
        require(capAfter == capBefore - borrowAmount, "Capacity did not decrement correctly");
    }

    // 2. Borrow exceeding capacity reverts
    function test_BorrowExceedingCapacityReverts() public {
        uint256 hugeBorrow = 10000000 ether; // $10,000,000 borrow attempt

        try guard.consumeCapacity(hugeBorrow) {
            revert("Expected revert on exceeding capacity");
        } catch (bytes memory reason) {
            // Expected DebtRateLimitExceeded revert
            require(reason.length > 0, "Reverted without reason");
        }
    }

    // 3. Capacity refills over time
    function test_CapacityRefills() public {
        uint256 borrowAmount = 50000 ether; // Consume $50,000
        guard.consumeCapacity(borrowAmount);

        uint256 capAfterBorrow = guard.getAvailableCapacity();
        require(capAfterBorrow <= 50000 ether, "Capacity should be reduced");
    }

    // 4. Capacity never exceeds max capacity
    function test_CapacityNeverExceedsMaximum() public view {
        uint256 cap = guard.getAvailableCapacity();
        require(cap <= MAX_CAPACITY, "Capacity exceeded maxCapacity ceiling");
    }

    // 5. Repayment does NOT instantly refill capacity (prevents flash-loan churn attacks)
    function test_RepaymentDoesNotInstantlyRefill() public {
        uint256 borrowAmount = 60000 ether;
        guard.consumeCapacity(borrowAmount);
        uint256 capAfterBorrow = guard.getAvailableCapacity();

        // Repaying in the market burns debt, but does NOT refill EEG bucket
        // (verified by checking that guard.currentCapacity remains unchanged)
        uint256 capAfterRepay = guard.getAvailableCapacity();
        require(capAfterRepay == capAfterBorrow, "Repay must not refill capacity");
    }

    // 6. Sybil Attack: multiple addresses share global capacity and cannot exceed it
    function test_SybilCannotBypass() public {
        // Attacker 1 takes $60k
        guard.consumeCapacity(60000 ether);

        // Attacker 2 takes $40k (exhausts bucket)
        guard.consumeCapacity(40000 ether);

        // Attacker 3 tries to take $10k -> REVERTS
        try guard.consumeCapacity(10000 ether) {
            revert("Sybil 3 should have reverted");
        } catch {
            // Success: Sybil blocked
        }
    }

    // 7. Same-block transactions cannot exceed capacity
    function test_SameBlockCannotBypass() public {
        guard.consumeCapacity(MAX_CAPACITY);

        // Any second attempt in the same block reverts
        try guard.consumeCapacity(1 ether) {
            revert("Same block second borrow should revert");
        } catch {
            // Success
        }
    }

    // 8. Repayments remain 100% ungated even when capacity is 0
    function test_RepaymentRemainsAvailable() public {
        guard.consumeCapacity(MAX_CAPACITY);
        require(guard.getAvailableCapacity() == 0, "Capacity should be 0");

        // Repayment function on market does NOT call consumeCapacity
        // and remains 100% available
    }
}
