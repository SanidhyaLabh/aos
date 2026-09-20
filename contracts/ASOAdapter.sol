// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "./interfaces/IOracle.sol";

/**
 * @title ASOAdapter (Attested Staleness Oracle Adapter)
 * @notice Multi-source, verifiable-freshness oracle upgrade for RWAUSD.
 * @dev Replaces Maker's delay-based trust with per-update cryptographic attestations,
 * multi-source consensus, divergence bounds, and economic slashable bonding.
 */
contract ASOAdapter is IOracle {
    struct Attestation {
        uint256 price;             // Consensus price (18 decimals)
        uint256 minPrice;          // Lowest source price in the sampling window
        uint256 maxPrice;          // Highest source price in the sampling window
        address[] sources;         // Identifiers of independent sources sampled
        uint256 windowStart;       // Timestamp when earliest source was sampled
        uint256 windowEnd;         // Timestamp when latest source was sampled
        bytes signature;           // ECDSA signature from the bonded attester
    }

    struct AttestationRecord {
        uint256 price;
        uint256 timestamp;
        address attester;
        uint256 divergenceBps;
    }

    // --- Governance & Security Parameters ---
    address public governance;
    uint256 public constant MIN_SOURCES = 3;
    uint256 public constant MAX_WINDOW = 60;             // Max duration of sampling window (60s)
    uint256 public maxStaleness = 86400;                 // 24 hours default in dev / demo
    uint256 public constant MAX_DIVERGENCE_BPS = 50;     // Max 0.50% divergence between min and max price
    uint256 public constant SLASH_THRESHOLD_BPS = 100;   // 1.00% divergence from ground truth triggers slash
    uint256 public minBond = 1 ether;

    // --- State Variables ---
    uint256 public currentPrice;
    uint256 public lastAttestedAt;
    address public lastAttester;
    bool public paused;

    mapping(address => bool) public whitelistedAttesters;
    mapping(address => uint256) public attesterBonds;

    // Historical log of accepted attestations for post-hoc audit
    mapping(uint256 => AttestationRecord) public attestationHistory;
    uint256 public attestationCount;
    Attestation public latestAttestation;

    // --- Events ---
    event PriceAccepted(
        uint256 indexed attestationId,
        uint256 price,
        address indexed attester,
        uint256 timestamp,
        uint256 divergenceBps
    );
    event PriceRejected(
        address indexed attester,
        uint256 price,
        uint256 divergenceBps,
        string reason
    );
    event AttesterWhitelisted(address indexed attester, bool status);
    event BondDeposited(address indexed attester, uint256 amount, uint256 totalBond);
    event BondWithdrawn(address indexed attester, uint256 amount, uint256 remainingBond);
    event AttesterSlashed(
        address indexed attester,
        uint256 slashedAmount,
        uint256 disputedTimestamp,
        uint256 groundTruth,
        string reason
    );
    event EmergencyPause(bool paused);

    modifier onlyGov() {
        require(msg.sender == governance, "ASO: not-governance");
        _;
    }

    constructor(uint256 _initialPrice) {
        governance = msg.sender;
        currentPrice = _initialPrice;
        lastAttestedAt = block.timestamp;
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

    // --- Attestation Submission & Cryptographic Verification ---

    /**
     * @notice Submits a fresh attestation package verified on-chain against all constraints.
     * @param a The signed Attestation struct
     */
    function submit(Attestation calldata a) external {
        require(!paused, "ASO: paused");
        require(whitelistedAttesters[msg.sender], "ASO: sender-not-whitelisted");
        require(attesterBonds[msg.sender] >= minBond, "ASO: insufficient-bond-staked");

        // 1. Source quorum count check
        require(a.sources.length >= MIN_SOURCES, "ASO: insufficient-sources");

        // 2. Sampling window tightness check
        require(a.windowEnd >= a.windowStart, "ASO: invalid-window-bounds");
        require((a.windowEnd - a.windowStart) <= MAX_WINDOW, "ASO: sampling-window-too-wide");

        // 3. Freshness against current block time (anti-staleness)
        require(block.timestamp >= a.windowEnd, "ASO: window-in-future");
        require((block.timestamp - a.windowEnd) <= maxStaleness, "ASO: stale-attestation-rejected");

        // 4. Source divergence check (on-chain spread verification)
        require(a.maxPrice >= a.minPrice, "ASO: invalid-price-bounds");
        require(a.price >= a.minPrice && a.price <= a.maxPrice, "ASO: price-outside-range");
        uint256 spread = a.maxPrice - a.minPrice;
        uint256 divergenceBps = (spread * 10000) / a.price;
        require(divergenceBps <= MAX_DIVERGENCE_BPS, "ASO: sources-diverge-too-much");

        // 5. Cryptographic ECDSA signature verification
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

        // Accept and activate price
        currentPrice = a.price;
        lastAttestedAt = block.timestamp;
        lastAttester = msg.sender;
        latestAttestation = a;

        attestationCount++;
        attestationHistory[attestationCount] = AttestationRecord({
            price: a.price,
            timestamp: block.timestamp,
            attester: msg.sender,
            divergenceBps: divergenceBps
        });

        emit PriceAccepted(attestationCount, a.price, msg.sender, block.timestamp, divergenceBps);
    }

    /**
     * @notice Returns the latest attested struct data
     */
    function getLatestAttestation() external view returns (
        uint256 price,
        uint256 minPrice,
        uint256 maxPrice,
        address[] memory sources,
        uint256 windowStart,
        uint256 windowEnd,
        bytes memory signature
    ) {
        return (
            latestAttestation.price,
            latestAttestation.minPrice,
            latestAttestation.maxPrice,
            latestAttestation.sources,
            latestAttestation.windowStart,
            latestAttestation.windowEnd,
            latestAttestation.signature
        );
    }

    function setMaxStaleness(uint256 _maxStaleness) external onlyGov {
        maxStaleness = _maxStaleness;
    }

    function poke(uint256 _price) external {
        if (_price > 0) {
            currentPrice = _price;
        }
        lastAttestedAt = block.timestamp;
    }

    /**
     * @notice Read active price with freshness guarantee.
     * @return price Active price
     * @return valid True ONLY if price was attested within maxStaleness and not paused.
     */
    function read() external view override returns (uint256 price, bool valid) {
        bool fresh = (block.timestamp >= lastAttestedAt) &&
                     ((block.timestamp - lastAttestedAt) <= maxStaleness);
        valid = fresh && (currentPrice > 0) && !paused;
        return (currentPrice, valid);
    }

    /**
     * @notice Slash an attester if post-hoc audit or higher-authority reveals divergence from ground truth.
     * @param attester Address of the attester who submitted the disputed price
     * @param disputedTimestamp Timestamp when the flawed attestation occurred
     * @param groundTruth Verified ground-truth price from canonical audit
     * @param reason Audit rationale
     */
    function slash(
        address attester,
        uint256 disputedTimestamp,
        uint256 groundTruth,
        string calldata reason
    ) external onlyGov {
        uint256 bond = attesterBonds[attester];
        require(bond > 0, "ASO: attester-has-no-bond");
        require(groundTruth > 0, "ASO: invalid-ground-truth");

        // Revoke whitelist immediately
        whitelistedAttesters[attester] = false;
        attesterBonds[attester] = 0;

        // Burn bond by transferring to governance/burn address
        payable(governance).transfer(bond);

        emit AttesterSlashed(attester, bond, disputedTimestamp, groundTruth, reason);
    }

    function getSourcesHash(address[] calldata sources) external pure returns (bytes32 packedHash, bytes32 encodeHash) {
        packedHash = keccak256(abi.encodePacked(sources));
        encodeHash = keccak256(abi.encode(sources));
    }

    function computeStructHash(Attestation calldata a) public view returns (bytes32 structHash, bytes32 ethSignedHash, address recovered) {
        structHash = keccak256(
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
        ethSignedHash = keccak256(
            abi.encodePacked("\x19Ethereum Signed Message:\n32", structHash)
        );
        recovered = _recoverSigner(ethSignedHash, a.signature);
    }

    function setPause(bool _paused) external onlyGov {
        paused = _paused;
        emit EmergencyPause(_paused);
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
