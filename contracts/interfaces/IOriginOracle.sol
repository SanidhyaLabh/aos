// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/**
 * @title IOriginOracle
 * @notice Standard oracle interface for ORIGIN — Oracle & Economic Risk Infrastructure.
 * Downstream DeFi lending protocols depend on this interface rather than internal ASO adapters.
 */
interface IOriginOracle {
    enum OracleStatus {
        FRESH,
        STALE,
        DIVERGENT,
        INSUFFICIENT_SOURCES,
        INVALID_SIGNATURE,
        UNAVAILABLE
    }

    /**
     * @notice Retrieves verified price and health status for an asset.
     * @param assetId Unique identifier (bytes32) of the asset (e.g. keccak256("RWAUSD"))
     * @return price Active valuation normalized to 18 decimals (Wad)
     * @return updatedAt Unix timestamp of the accepted valuation
     * @return status Health enum indicating whether price is usable (FRESH = 0)
     */
    function getPrice(bytes32 assetId)
        external
        view
        returns (
            uint256 price,
            uint256 updatedAt,
            OracleStatus status
        );

    /**
     * @notice Backward-compatible simple read method.
     * @return price Latest price in 18 decimals
     * @return valid True if status == FRESH and not paused
     */
    function read() external view returns (uint256 price, bool valid);
}
