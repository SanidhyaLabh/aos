import { ethers } from "ethers";
import { AttestationService, DEFAULT_SOURCES } from "../service/attestationService.js";

async function testCrypto() {
  console.log("=== Testing ASO Cryptographic Attestation Pipeline ===");

  const service = new AttestationService({
    chainId: 31337n,
    adapterAddress: "0x9fE46736679d2D9a65F0992F2272dE9f3c7fa6e0"
  });

  const signerAddress = service.getSignerAddress();
  console.log(`Bonded Attester Address: ${signerAddress}`);

  // 1. Sample sources
  const { samples, windowStart, windowEnd } = service.sampleSources();
  console.log(`Sampled ${samples.length} feeds:`, samples.map(s => `${s.name}: $${s.price}`));

  // 2. Evaluate consensus
  const consensus = service.evaluateConsensus(samples, windowStart, windowEnd);
  console.log(`Consensus Result: success=${consensus.success}, median=$${consensus.price}, spread=${consensus.divergenceBps} bps`);

  if (!consensus.success) {
    throw new Error("Consensus failed unexpectedly");
  }

  // 3. Build & Sign Attestation
  const attestation = await service.buildAndSignAttestation(consensus);
  console.log("Attestation struct built successfully!");
  console.log(`Price (wei): ${attestation.struct.price.toString()}`);
  console.log(`Signature: ${attestation.struct.signature.slice(0, 32)}...`);

  // 4. Verify on-chain hash reconstruction matches
  const sourcesHash = ethers.solidityPackedKeccak256(
    new Array(attestation.struct.sources.length).fill("address"),
    attestation.struct.sources
  );

  const abiCoder = ethers.AbiCoder.defaultAbiCoder();
  const encodedStruct = abiCoder.encode(
    ["uint256", "uint256", "uint256", "bytes32", "uint256", "uint256", "uint256", "address"],
    [
      attestation.struct.price,
      attestation.struct.minPrice,
      attestation.struct.maxPrice,
      sourcesHash,
      attestation.struct.windowStart,
      attestation.struct.windowEnd,
      service.chainId,
      service.adapterAddress
    ]
  );
  const structHash = ethers.keccak256(encodedStruct);
  const ethSignedHash = ethers.hashMessage(ethers.getBytes(structHash));
  const recoveredSigner = ethers.recoverAddress(ethSignedHash, attestation.struct.signature);

  console.log(`Recovered Signer from signature: ${recoveredSigner}`);
  console.log(`Expected Signer:               ${signerAddress}`);

  if (recoveredSigner.toLowerCase() === signerAddress.toLowerCase()) {
    console.log(">>> [SUCCESS] Cryptographic signature matches 100% on-chain recovery expectations!");
  } else {
    throw new Error("Signature verification mismatch!");
  }
}

testCrypto().catch(err => {
  console.error(err);
  process.exit(1);
});
