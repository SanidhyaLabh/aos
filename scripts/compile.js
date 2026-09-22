import fs from 'fs';
import path from 'path';
import solc from 'solc';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const rootDir = path.resolve(__dirname, '..');
const contractsDir = path.join(rootDir, 'contracts');
const artifactsDir = path.join(rootDir, 'artifacts');

if (!fs.existsSync(artifactsDir)) {
  fs.mkdirSync(artifactsDir, { recursive: true });
}

console.log('[Compiler] Loading Solidity source files from', contractsDir);

const sources = {
  'interfaces/IOracle.sol': {
    content: fs.readFileSync(path.join(contractsDir, 'interfaces', 'IOracle.sol'), 'utf8')
  },
  'interfaces/IOriginOracle.sol': {
    content: fs.readFileSync(path.join(contractsDir, 'interfaces', 'IOriginOracle.sol'), 'utf8')
  },
  'VanillaOSM.sol': {
    content: fs.readFileSync(path.join(contractsDir, 'VanillaOSM.sol'), 'utf8')
  },
  'ASOAdapter.sol': {
    content: fs.readFileSync(path.join(contractsDir, 'ASOAdapter.sol'), 'utf8')
  },
  'ToyLendingMarket.sol': {
    content: fs.readFileSync(path.join(contractsDir, 'ToyLendingMarket.sol'), 'utf8')
  },
  'SentinelRegistry.sol': {
    content: fs.readFileSync(path.join(contractsDir, 'SentinelRegistry.sol'), 'utf8')
  },
  'RiskEngine.sol': {
    content: fs.readFileSync(path.join(contractsDir, 'RiskEngine.sol'), 'utf8')
  },
  'FrictionEngine.sol': {
    content: fs.readFileSync(path.join(contractsDir, 'FrictionEngine.sol'), 'utf8')
  },
  'EconomicExposureGuard.sol': {
    content: fs.readFileSync(path.join(contractsDir, 'EconomicExposureGuard.sol'), 'utf8')
  },
  'GlobalExposureGuard.sol': {
    content: fs.readFileSync(path.join(contractsDir, 'GlobalExposureGuard.sol'), 'utf8')
  },
  'RiskGroupExposureGuard.sol': {
    content: fs.readFileSync(path.join(contractsDir, 'RiskGroupExposureGuard.sol'), 'utf8')
  },
  'BorrowGateway.sol': {
    content: fs.readFileSync(path.join(contractsDir, 'BorrowGateway.sol'), 'utf8')
  }
};

const input = {
  language: 'Solidity',
  sources,
  settings: {
    optimizer: {
      enabled: true,
      runs: 200
    },
    outputSelection: {
      '*': {
        '*': ['abi', 'evm.bytecode']
      }
    }
  }
};

console.log('[Compiler] Compiling contracts with solc', solc.version());
const output = JSON.parse(solc.compile(JSON.stringify(input)));

if (output.errors) {
  let hasErrors = false;
  output.errors.forEach(err => {
    if (err.severity === 'error') {
      hasErrors = true;
      console.error('[Compiler Error]', err.formattedMessage);
    } else {
      console.warn('[Compiler Warning]', err.formattedMessage);
    }
  });
  if (hasErrors) {
    process.exit(1);
  }
}

const compiledContracts = {};

for (const sourceFile in output.contracts) {
  for (const contractName in output.contracts[sourceFile]) {
    const contract = output.contracts[sourceFile][contractName];
    const artifact = {
      contractName,
      sourceFile,
      abi: contract.abi,
      bytecode: contract.evm.bytecode.object
    };

    const outPath = path.join(artifactsDir, `${contractName}.json`);
    fs.writeFileSync(outPath, JSON.stringify(artifact, null, 2));
    compiledContracts[contractName] = artifact;
    console.log(`[Compiler] Successfully wrote artifact: ${contractName} -> ${outPath}`);
  }
}

console.log('[Compiler] Build complete! Compiled contracts:', Object.keys(compiledContracts));
