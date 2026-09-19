import { ethers } from "ethers";
import fs from "fs";
import path from "path";

const deployment = JSON.parse(fs.readFileSync("./src/deployments.json", "utf8"));
const provider = new ethers.JsonRpcProvider("http://127.0.0.1:8545");
const attester = new ethers.Wallet("0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d", provider);

const aso = new ethers.Contract(deployment.contracts.ASOAdapter.address, deployment.contracts.ASOAdapter.abi, attester);

async function test() {
  const latestBlock = await provider.getBlock("latest");
  console.log("Current block timestamp:", latestBlock.timestamp);
  
  const now = latestBlock.timestamp;
  const windowStart = BigInt(now - 5);
  const windowEnd = BigInt(now);

  const priceWei = ethers.parseEther("100.0");
  const minPriceWei = ethers.parseEther("99.98");
  const maxPriceWei = ethers.parseEther("100.03");
  const sources = [
    "0x1111111111111111111111111111111111111111",
    "0x2222222222222222222222222222222222222222",
    "0x3333333333333333333333333333333333333333",
    "0x4444444444444444444444444444444444444444"
  ];

  const sourcesHash = ethers.solidityPackedKeccak256(
    new Array(sources.length).fill("address"),
    sources
  );

  const abiCoder = ethers.AbiCoder.defaultAbiCoder();
  const encoded = abiCoder.encode(
    ["uint256", "uint256", "uint256", "bytes32", "uint256", "uint256", "uint256", "address"],
    [priceWei, minPriceWei, maxPriceWei, sourcesHash, windowStart, windowEnd, 31337n, deployment.contracts.ASOAdapter.address]
  );
  const structHash = ethers.keccak256(encoded);
  const sig = await attester.signMessage(ethers.getBytes(structHash));

  console.log("Signer address:", attester.address);
  console.log("Struct hash:", structHash);
  console.log("Signature:", sig);

  try {
    const tx = await aso.submit({
      price: priceWei,
      minPrice: minPriceWei,
      maxPrice: maxPriceWei,
      sources,
      windowStart,
      windowEnd,
      signature: sig
    });
    const rc = await tx.wait();
    console.log("SUCCESS! Gas used:", rc.gasUsed);
  } catch (err) {
    console.error("FAIL REASON:", err);
  }
}

test();
