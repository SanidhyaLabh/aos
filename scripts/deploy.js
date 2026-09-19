import { ethers } from "ethers";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const rootDir = path.resolve(__dirname, "..");
const artifactsDir = path.join(rootDir, "artifacts");

async function main() {
  const rpcUrl = process.env.RPC_URL || "http://127.0.0.1:8545";
  console.log(`[Deploy] Connecting to EVM node at ${rpcUrl}...`);

  const provider = new ethers.JsonRpcProvider(rpcUrl);
  
  // Verify provider connection
  const network = await provider.getNetwork();
  console.log(`[Deploy] Connected to chainId: ${network.chainId}`);

  // Test accounts from Anvil standard mnemonic
  const deployer = await provider.getSigner(0);
  const attester = await provider.getSigner(1);
  const feeder = await provider.getSigner(2);
  const borrower = await provider.getSigner(3);

  console.log(`[Deploy] Deployer / Gov: ${await deployer.getAddress()}`);
  console.log(`[Deploy] Attester:       ${await attester.getAddress()}`);
  console.log(`[Deploy] Feeder:         ${await feeder.getAddress()}`);
  console.log(`[Deploy] Borrower:       ${await borrower.getAddress()}`);

  const asoArtifact = JSON.parse(fs.readFileSync(path.join(artifactsDir, "ASOAdapter.json"), "utf8"));
  const osmArtifact = JSON.parse(fs.readFileSync(path.join(artifactsDir, "VanillaOSM.json"), "utf8"));
  const lendingArtifact = JSON.parse(fs.readFileSync(path.join(artifactsDir, "ToyLendingMarket.json"), "utf8"));
  const sentinelArtifact = JSON.parse(fs.readFileSync(path.join(artifactsDir, "SentinelRegistry.json"), "utf8"));
  const riskEngineArtifact = JSON.parse(fs.readFileSync(path.join(artifactsDir, "RiskEngine.json"), "utf8"));

  const initialPrice = ethers.parseEther("100"); // $100.00 base price

  // 1. Deploy ASOAdapter
  console.log("\n[Deploy] Deploying ASOAdapter...");
  const AsoFactory = new ethers.ContractFactory(asoArtifact.abi, asoArtifact.bytecode, deployer);
  const asoAdapter = await AsoFactory.deploy(initialPrice);
  await asoAdapter.waitForDeployment();
  const asoAddress = await asoAdapter.getAddress();
  console.log(`[Deploy] ASOAdapter deployed to: ${asoAddress}`);

  // Attester deposits 1.0 ETH bond to become whitelisted
  console.log("[Deploy] Attester staking 1.0 ETH bond into ASOAdapter...");
  const asoAttesterContract = asoAdapter.connect(attester);
  const bondTx = await asoAttesterContract.depositBond({ value: ethers.parseEther("1.0") });
  await bondTx.wait();
  console.log("[Deploy] Bond staked! Attester whitelisted status:", await asoAdapter.whitelistedAttesters(await attester.getAddress()));

  // 2. Deploy VanillaOSM
  console.log("\n[Deploy] Deploying VanillaOSM (hop = 3600s, feeder = Account #2)...");
  const OsmFactory = new ethers.ContractFactory(osmArtifact.abi, osmArtifact.bytecode, deployer);
  const vanillaOsm = await OsmFactory.deploy(await feeder.getAddress(), 3600, initialPrice);
  await vanillaOsm.waitForDeployment();
  const osmAddress = await vanillaOsm.getAddress();
  console.log(`[Deploy] VanillaOSM deployed to: ${osmAddress}`);

  // 3. Deploy RiskEngine
  console.log("\n[Deploy] Deploying RiskEngine (v2 Manipulation-Cost & Weighted Median Engine)...");
  const RiskFactory = new ethers.ContractFactory(riskEngineArtifact.abi, riskEngineArtifact.bytecode, deployer);
  const riskEngine = await RiskFactory.deploy();
  await riskEngine.waitForDeployment();
  const riskEngineAddress = await riskEngine.getAddress();
  console.log(`[Deploy] RiskEngine deployed to: ${riskEngineAddress}`);

  // 4. Deploy ToyLendingMarket for VanillaOSM
  console.log("\n[Deploy] Deploying ToyLendingMarket connected to VanillaOSM...");
  const LendingFactory = new ethers.ContractFactory(lendingArtifact.abi, lendingArtifact.bytecode, deployer);
  const lendingOSM = await LendingFactory.deploy(osmAddress, "VanillaOSM");
  await lendingOSM.waitForDeployment();
  const lendingOsmAddress = await lendingOSM.getAddress();
  console.log(`[Deploy] ToyLendingMarket (OSM) deployed to: ${lendingOsmAddress}`);

  // 5. Deploy ToyLendingMarket for ASOAdapter
  console.log("\n[Deploy] Deploying ToyLendingMarket connected to ASOAdapter...");
  const lendingASO = await LendingFactory.deploy(asoAddress, "ASOAdapter");
  await lendingASO.waitForDeployment();
  const lendingAsoAddress = await lendingASO.getAddress();
  console.log(`[Deploy] ToyLendingMarket (ASO) deployed to: ${lendingAsoAddress}`);

  // 6. Deploy SentinelRegistry (linked to ASOAdapter, base ceiling = 500,000 USD)
  console.log("\n[Deploy] Deploying SentinelRegistry (oracle = ASOAdapter, baseCeiling = $500,000)...");
  const SentinelFactory = new ethers.ContractFactory(sentinelArtifact.abi, sentinelArtifact.bytecode, deployer);
  const baseCeiling = ethers.parseEther("500000"); // $500,000
  const sentinel = await SentinelFactory.deploy(asoAddress, baseCeiling);
  await sentinel.waitForDeployment();
  const sentinelAddress = await sentinel.getAddress();
  console.log(`[Deploy] SentinelRegistry deployed to: ${sentinelAddress}`);

  // 7. Wire v2 linkages
  console.log("\n[Deploy] Wiring v2 Risk Engine & Sentinel linkages...");
  await (await sentinel.setRiskEngine(riskEngineAddress)).wait();
  await (await lendingASO.setSentinel(sentinelAddress)).wait();
  await (await lendingASO.setRiskEngine(riskEngineAddress)).wait();
  console.log("[Deploy] Linkages established: Sentinel <-> RiskEngine, LendingMarket <-> Sentinel");

  // 8. Seed borrower positions with 1,000 collateral units (nominal $100k)
  console.log("\n[Deploy] Seeding 1,000 collateral units for borrower in both lending pools...");
  const borrowerCollateral = ethers.parseEther("1000"); // 1,000 RWA tokens
  const lendingOsmBorrower = lendingOSM.connect(borrower);
  const lendingAsoBorrower = lendingASO.connect(borrower);

  const tx1 = await lendingOsmBorrower.depositCollateral(borrowerCollateral);
  await tx1.wait();
  const tx2 = await lendingAsoBorrower.depositCollateral(borrowerCollateral);
  await tx2.wait();
  console.log("[Deploy] Borrower collateral deposited (1,000 units each)!");

  // 9. Save deployment configuration
  const deploymentData = {
    network: {
      name: "Anvil Localhost",
      chainId: Number(network.chainId),
      rpcUrl: rpcUrl,
      wsUrl: "ws://127.0.0.1:8545"
    },
    contracts: {
      ASOAdapter: {
        address: asoAddress,
        abi: asoArtifact.abi
      },
      VanillaOSM: {
        address: osmAddress,
        abi: osmArtifact.abi
      },
      RiskEngine: {
        address: riskEngineAddress,
        abi: riskEngineArtifact.abi
      },
      ToyLendingMarketOSM: {
        address: lendingOsmAddress,
        abi: lendingArtifact.abi
      },
      ToyLendingMarketASO: {
        address: lendingAsoAddress,
        abi: lendingArtifact.abi
      },
      SentinelRegistry: {
        address: sentinelAddress,
        abi: sentinelArtifact.abi
      }
    },
    accounts: {
      deployer: await deployer.getAddress(),
      attester: await attester.getAddress(),
      feeder: await feeder.getAddress(),
      borrower: await borrower.getAddress()
    },
    deployedAt: new Date().toISOString()
  };

  const srcDeployPath = path.join(rootDir, "src", "deployments.json");
  const artifactDeployPath = path.join(artifactsDir, "deployments.json");

  fs.writeFileSync(srcDeployPath, JSON.stringify(deploymentData, null, 2));
  fs.writeFileSync(artifactDeployPath, JSON.stringify(deploymentData, null, 2));
  console.log(`\n[Deploy] Successfully saved deployments to ${srcDeployPath}`);
  console.log("[Deploy] Deployment complete!");
}

main().catch((err) => {
  console.error("[Deploy Failed]", err);
  process.exit(1);
});



