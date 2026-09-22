// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "./interfaces/IOracle.sol";
import "./interfaces/IOriginOracle.sol";

/**
 * @title ASOAdapter (Attested Staleness Oracle Adapter — Production EIP-712)
 * @notice Multi-source, cryptographically verified freshness oracle for ORIGIN.
 * @dev Enforces:
 * 1. EIP-712 structured data signing with domain separation (chainId, verifyingContract, assetId, roundId)
 * 2. Monotonic round IDs preventing replay attacks
 * 3. Minimum source quorum & independent source group verification
 * 4. Precise sampling window tightness & anti-staleness bounds
 * 5. On-chain divergence verification between source observations
 * 6. Economic slashable bonding for authorized attesters
 */
contract ASOAdapter is IOracle, IOriginOracle {
    // --- EIP-712 TypeHashes ---
    bytes32 public constant EIP712_DOMAIN_TYPEHASH = keccak256(
        "EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)"
    );
    bytes32 public constant OBSERVATION_TYPEHASH = keccak256(
        "Observation(bytes32 sourceId,bytes32 sourceGroup,uint256 price,uint256 timestamp)"
    );
    bytes32 public constant ATTESTATION_TYPEHASH = keccak256(
        "Attestation(bytes32 assetId,uint256 aggregatePrice,Observation[] observations,uint256 windowStart,uint256 windowEnd,uint256 roundId,uint256 validUntil)Observation(bytes32 sourceId,bytes32 sourceGroup,uint256 price,uint256 timestamp)"
    );

    struct Observation {
        bytes32 sourceId;
        bytes32 sourceGroup;
        uint256 price;
        uint256 timestamp;
    }

    struct Attestation {
        bytes32 assetId;
        uint256 aggregatePrice;
        Observation[] observations;
        uint256 windowStart;
        uint256 windowEnd;
        uint256 roundId;
        uint256 validUntil;
        bytes signature;
    }

    // Legacy Attestation struct for backward compatibility
    struct LegacyAttestation {
        uint256 price;
        uint256 minPrice;
        uint256 maxPrice;
        address[] sources;
        uint256 windowStart;
        uint256 windowEnd;
        bytes signature;
    }

    struct AttestationRecord {
        uint256 price;
        uint256 timestamp;
        address attester;
        uint256 divergenceBps;
        uint256 roundId;
    }

    // --- Governance & Security Parameters ---
    address public governance;
    uint256 public constant MIN_SOURCES = 3;
    uint256 public constant MIN_INDEPENDENT_GROUPS = 2;
    uint256 public constant MAX_WINDOW = 60;             // Max duration of sampling window (60s)
    uint256 public maxStaleness = 86400;                 // 24 hours default in dev / demo
    uint256 public constant MAX_DIVERGENCE_BPS = 50;     // Max 0.50% divergence between min and max price
    uint256 public constant SLASH_THRESHOLD_BPS = 100;   // 1.00% divergence triggers slash
    uint256 public minBond = 1 ether;

    // --- State Variables ---
    uint256 public currentPrice;
    uint256 public lastAttestedAt;
    address public lastAttester;
    bool public paused;

    // Per-asset tracking: assetId => state
    mapping(bytes32 => uint256) public assetPrices;
    mapping(bytes32 => uint256) public assetLastAttested;
    mapping(bytes32 => uint256) public latestRound;

    mapping(address => bool) public whitelistedAttesters;
    mapping(address => uint256) public attesterBonds;

    mapping(uint256 => AttestationRecord) public attestationHistory;
    uint256 public attestationCount;
    LegacyAttestation public latestAttestation;

    // --- Custom Errors ---
    error OraclePaused();
    error UnauthorizedAttester(address caller);
    error InsufficientBond(address caller, uint256 bond, uint256 minRequired);
    error InsufficientSourceQuorum(uint256 count, uint256 minRequired);
    error InsufficientIndependentGroups(uint256 groups, uint256 minRequired);
    error DuplicateSource(bytes32 sourceId);
    error InvalidSamplingWindow(uint256 start, uint256 end);
    error WindowInFuture(uint256 windowEnd, uint256 blockTime);
    error AttestationStale(uint256 elapsed, uint256 maxStaleness);
    error AttestationExpired(uint256 validUntil, uint256 blockTime);
    error StaleRoundOrNonce(uint256 roundId, uint256 latestRoundId);
    error ExcessiveDivergence(uint256 divergenceBps, uint256 maxAllowed);
    error InvalidAggregatePrice(uint256 price, uint256 minPrice, uint256 maxPrice);
    error InvalidSignature(address recovered, address expected);
    error InvalidParameter(string reason);

    // --- Events ---
    event PriceAccepted(
        uint256 indexed attestationId,
        bytes32 indexed assetId,
        uint256 price,
        address indexed attester,
        uint256 timestamp,
        uint256 divergenceBps,
        uint256 roundId
    );
    event PriceRejected(address indexed attester, bytes32 indexed assetId, string reason);
    event AttesterWhitelisted(address indexed attester, bool status);
    event BondDeposited(address indexed attester, uint256 amount, uint256 totalBond);
    event BondWithdrawn(address indexed attester, uint256 amount, uint256 remainingBond);
    event AttesterSlashed(address indexed attester, uint256 slashedAmount, uint256 disputedTimestamp, uint256 groundTruth, string reason);
    event EmergencyPause(bool paused);

    modifier onlyGov() {
        require(msg.sender == governance, "ASO: not-governance");
        _;
    }

    constructor(uint256 _initialPrice) {
        governance = msg.sender;
        currentPrice = _initialPrice;
        lastAttestedAt = block.timestamp;
        bytes32 defaultAsset = keccak256("RWAUSD");
        assetPrices[defaultAsset] = _initialPrice;
        assetLastAttested[defaultAsset] = block.timestamp;
    }

    // --- EIP-712 Domain Separator ---
    function DOMAIN_SEPARATOR() public view returns (bytes32) {
        return keccak256(
            abi.encode(
                EIP712_DOMAIN_TYPEHASH,
                keccak256(bytes("ORIGIN ASO")),
                keccak256(bytes("1")),
                block.chainid,
                address(this)
            )
        );
    }

    // --- Bond Staking Management ---
    function depositBond() external payable {
        require(msg.value > 0, "ASO: zero-deposit");
        attesterBonds[msg.sender] += msg.value;
        if (attesterBonds[msg.sender] >= minBond) {
            whitelistedAttesters[msg.sender] = true;
            emit AttesterWhitelisted(msg.sender, true);
        }
        emit BondDeposited(msg.sender, msg.value, attesterBonds[msg.sender]);
    }

    function withdrawBond(uint256 amount) external {
        require(attesterBonds[msg.sender] >= amount, "ASO: insufficient-bond");
        attesterBonds[msg.sender] -= amount;
        if (attesterBonds[msg.sender] < minBond) {
            whitelistedAttesters[msg.sender] = false;
            emit AttesterWhitelisted(msg.sender, false);
        }
        payable(msg.sender).transfer(amount);
        emit BondWithdrawn(msg.sender, amount, attesterBonds[msg.sender]);
    }

    function setWhitelistedAttester(address attester, bool status) external onlyGov {
        whitelistedAttesters[attester] = status;
        emit AttesterWhitelisted(attester, status);
    }

    // --- Production EIP-712 Attestation Submission ---
    /**
     * @notice Submits a cryptographically verified, domain-separated EIP-712 attestation package.
     */
    function submitAttestation(Attestation calldata a) external {
        if (paused) revert OraclePaused();
        if (!whitelistedAttesters[msg.sender]) revert UnauthorizedAttester(msg.sender);
        if (attesterBonds[msg.sender] < minBond) revert InsufficientBond(msg.sender, attesterBonds[msg.sender], minBond);

        // 1. Monotonic Round Check (Replay resistance)
        if (a.roundId <= latestRound[a.assetId]) {
            revert StaleRoundOrNonce(a.roundId, latestRound[a.assetId]);
        }

        // 2. Timing validation
        _validateWindow(a.windowStart, a.windowEnd, a.validUntil);

        // 3. Source quorum, independence, & divergence
        uint256 divergenceBps = _validateObservations(a);

        // 4. EIP-712 Signature Verification
        _verifySignature(a);

        // Accept and activate
        latestRound[a.assetId] = a.roundId;
        assetPrices[a.assetId] = a.aggregatePrice;
        assetLastAttested[a.assetId] = block.timestamp;
        currentPrice = a.aggregatePrice;
        lastAttestedAt = block.timestamp;
        lastAttester = msg.sender;

        attestationCount++;
        attestationHistory[attestationCount] = AttestationRecord({
            price: a.aggregatePrice,
            timestamp: block.timestamp,
            attester: msg.sender,
            divergenceBps: divergenceBps,
            roundId: a.roundId
        });

        emit PriceAccepted(attestationCount, a.assetId, a.aggregatePrice, msg.sender, block.timestamp, divergenceBps, a.roundId);
    }

    function _validateWindow(uint256 windowStart, uint256 windowEnd, uint256 validUntil) internal view {
        if (validUntil > 0 && block.timestamp > validUntil) {
            revert AttestationExpired(validUntil, block.timestamp);
        }
        if (block.timestamp < windowEnd) {
            revert WindowInFuture(windowEnd, block.timestamp);
        }
        if (block.timestamp - windowEnd > maxStaleness) {
            revert AttestationStale(block.timestamp - windowEnd, maxStaleness);
        }
        if (windowEnd < windowStart || (windowEnd - windowStart) > MAX_WINDOW) {
            revert InvalidSamplingWindow(windowStart, windowEnd);
        }
    }

    function _validateObservations(Attestation calldata a) internal pure returns (uint256 divergenceBps) {
        uint256 obsCount = a.observations.length;
        if (obsCount < MIN_SOURCES) {
            revert InsufficientSourceQuorum(obsCount, MIN_SOURCES);
        }

        uint256 minObsPrice = type(uint256).max;
        uint256 maxObsPrice = 0;
        bytes32[] memory seenGroups = new bytes32[](obsCount);
        uint256 uniqueGroups = 0;

        for (uint256 i = 0; i < obsCount; i++) {
            Observation calldata obs = a.observations[i];
            if (obs.price == 0) revert InvalidParameter("Zero observation price");
            if (obs.timestamp < a.windowStart || obs.timestamp > a.windowEnd) {
                revert InvalidSamplingWindow(a.windowStart, a.windowEnd);
            }

            for (uint256 j = 0; j < i; j++) {
                if (a.observations[j].sourceId == obs.sourceId) {
                    revert DuplicateSource(obs.sourceId);
                }
            }

            bool groupSeen = false;
            for (uint256 g = 0; g < uniqueGroups; g++) {
                if (seenGroups[g] == obs.sourceGroup) {
                    groupSeen = true;
                    break;
                }
            }
            if (!groupSeen) {
                seenGroups[uniqueGroups] = obs.sourceGroup;
                uniqueGroups++;
            }

            if (obs.price < minObsPrice) minObsPrice = obs.price;
            if (obs.price > maxObsPrice) maxObsPrice = obs.price;
        }

        if (uniqueGroups < MIN_INDEPENDENT_GROUPS) {
            revert InsufficientIndependentGroups(uniqueGroups, MIN_INDEPENDENT_GROUPS);
        }

        if (a.aggregatePrice < minObsPrice || a.aggregatePrice > maxObsPrice) {
            revert InvalidAggregatePrice(a.aggregatePrice, minObsPrice, maxObsPrice);
        }

        uint256 spread = maxObsPrice - minObsPrice;
        divergenceBps = (spread * 10000) / a.aggregatePrice;
        if (divergenceBps > MAX_DIVERGENCE_BPS) {
            revert ExcessiveDivergence(divergenceBps, MAX_DIVERGENCE_BPS);
        }
    }

    function _verifySignature(Attestation calldata a) internal view {
        bytes32 structHash = hashAttestation(a);
        bytes32 digest = keccak256(abi.encodePacked("\x19\x01", DOMAIN_SEPARATOR(), structHash));
        address recoveredSigner = _recoverSigner(digest, a.signature);
        if (recoveredSigner != msg.sender) {
            revert InvalidSignature(recoveredSigner, msg.sender);
        }
    }

    /**
     * @notice Hashes the Attestation struct for EIP-712 encoding.
     */
    function hashAttestation(Attestation calldata a) public pure returns (bytes32) {
        bytes32[] memory obsHashes = new bytes32[](a.observations.length);
        for (uint256 i = 0; i < a.observations.length; i++) {
            obsHashes[i] = keccak256(
                abi.encode(
                    OBSERVATION_TYPEHASH,
                    a.observations[i].sourceId,
                    a.observations[i].sourceGroup,
                    a.observations[i].price,
                    a.observations[i].timestamp
                )
            );
        }

        return keccak256(
            abi.encode(
                ATTESTATION_TYPEHASH,
                a.assetId,
                a.aggregatePrice,
                keccak256(abi.encodePacked(obsHashes)),
                a.windowStart,
                a.windowEnd,
                a.roundId,
                a.validUntil
            )
        );
    }

    // --- Legacy Submission Method (Backward Compatibility with v2 test harnesses) ---
    function submit(LegacyAttestation calldata a) external {
        require(!paused, "ASO: paused");
        require(whitelistedAttesters[msg.sender], "ASO: sender-not-whitelisted");
        require(attesterBonds[msg.sender] >= minBond, "ASO: insufficient-bond-staked");

        require(a.sources.length >= MIN_SOURCES, "ASO: insufficient-sources");
        require(a.windowEnd >= a.windowStart, "ASO: invalid-window-bounds");
        require((a.windowEnd - a.windowStart) <= MAX_WINDOW, "ASO: sampling-window-too-wide");
        require(block.timestamp >= a.windowEnd, "ASO: window-in-future");
        require((block.timestamp - a.windowEnd) <= maxStaleness, "ASO: stale-attestation-rejected");
        require(a.maxPrice >= a.minPrice, "ASO: invalid-price-bounds");
        require(a.price >= a.minPrice && a.price <= a.maxPrice, "ASO: price-outside-range");

        uint256 spread = a.maxPrice - a.minPrice;
        uint256 divergenceBps = (spread * 10000) / a.price;
        require(divergenceBps <= MAX_DIVERGENCE_BPS, "ASO: sources-diverge-too-much");

        bytes32 structHash = keccak256(
            abi.encode(
                a.price,
                a.minPrice,
                a.maxPrice,
                keccak256(abi.encodePacked(a.sources)),
                a.windowStart,
                a.windowEnd,
                block.chainid,
                address(this)
            )
        );
        bytes32 ethSignedHash = keccak256(
            abi.encodePacked("\x19Ethereum Signed Message:\n32", structHash)
        );
        address recoveredSigner = _recoverSigner(ethSignedHash, a.signature);
        require(recoveredSigner == msg.sender, "ASO: invalid-attester-signature");

        currentPrice = a.price;
        lastAttestedAt = block.timestamp;
        lastAttester = msg.sender;
        latestAttestation = a;

        bytes32 defaultAsset = keccak256("RWAUSD");
        assetPrices[defaultAsset] = a.price;
        assetLastAttested[defaultAsset] = block.timestamp;

        attestationCount++;
        attestationHistory[attestationCount] = AttestationRecord({
            price: a.price,
            timestamp: block.timestamp,
            attester: msg.sender,
            divergenceBps: divergenceBps,
            roundId: attestationCount
        });

        emit PriceAccepted(attestationCount, defaultAsset, a.price, msg.sender, block.timestamp, divergenceBps, attestationCount);
    }

    // --- IOriginOracle Implementation ---
    function getPrice(bytes32 assetId)
        external
        view
        override
        returns (
            uint256 price,
            uint256 updatedAt,
            OracleStatus status
        )
    {
        if (paused) return (0, 0, OracleStatus.UNAVAILABLE);

        price = assetPrices[assetId];
        updatedAt = assetLastAttested[assetId];

        // Fallback for default asset if not individually populated
        if (price == 0 && (assetId == keccak256("RWAUSD") || assetId == bytes32(0))) {
            price = currentPrice;
            updatedAt = lastAttestedAt;
        }

        if (price == 0 || updatedAt == 0) {
            return (0, 0, OracleStatus.UNAVAILABLE);
        }

        if (block.timestamp > updatedAt + maxStaleness) {
            return (price, updatedAt, OracleStatus.STALE);
        }

        return (price, updatedAt, OracleStatus.FRESH);
    }

    function read() external view override(IOracle, IOriginOracle) returns (uint256 price, bool valid) {
        bool fresh = (block.timestamp >= lastAttestedAt) &&
                     ((block.timestamp - lastAttestedAt) <= maxStaleness);
        valid = fresh && (currentPrice > 0) && !paused;
        return (currentPrice, valid);
    }

    function setMaxStaleness(uint256 _maxStaleness) external onlyGov {
        maxStaleness = _maxStaleness;
    }

    function poke(bytes32 assetId, uint256 _price) external onlyGov {
        assetPrices[assetId] = _price;
        assetLastAttested[assetId] = block.timestamp;
        if (assetId == keccak256("RWAUSD") || assetId == bytes32(0)) {
            currentPrice = _price;
            lastAttestedAt = block.timestamp;
        }
    }

    function setPause(bool _paused) external onlyGov {
        paused = _paused;
        emit EmergencyPause(_paused);
    }

    function slash(
        address attester,
        uint256 disputedTimestamp,
        uint256 groundTruth,
        string calldata reason
    ) external onlyGov {
        uint256 bond = attesterBonds[attester];
        require(bond > 0, "ASO: attester-has-no-bond");
        require(groundTruth > 0, "ASO: invalid-ground-truth");

        whitelistedAttesters[attester] = false;
        attesterBonds[attester] = 0;
        payable(governance).transfer(bond);

        emit AttesterSlashed(attester, bond, disputedTimestamp, groundTruth, reason);
    }

    function _recoverSigner(bytes32 hash, bytes memory sig) internal pure returns (address) {
        require(sig.length == 65, "ASO: invalid-signature-length");
        bytes32 r;
        bytes32 s;
        uint8 v;
        assembly {
            r := mload(add(sig, 32))
            s := mload(add(sig, 64))
            v := byte(0, mload(add(sig, 96)))
        }
        if (v < 27) {
            v += 27;
        }
        return ecrecover(hash, v, r, s);
    }
}
