import { createRequire } from "node:module";
import { existsSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const require = createRequire(path.join(root, "package.json"));
const failures = [];

function fail(message) {
  failures.push(message);
  console.error(`[ECHEC] ${message}`);
}

function ok(message) {
  console.log(`[OK] ${message}`);
}

const [major, minor] = process.versions.node.split(".").map(Number);
if (major < 20 || (major === 20 && minor < 9)) {
  fail(`Node.js ${process.versions.node} est trop ancien (minimum 20.9).`);
} else {
  ok(`Node.js ${process.versions.node} (ABI ${process.versions.modules})`);
}

for (const relativePath of ["package-lock.json", "node_modules", "backend/.venv/Scripts/python.exe"]) {
  if (!existsSync(path.join(root, relativePath))) {
    fail(`${relativePath} est introuvable.`);
  }
}

for (const moduleName of ["better-sqlite3", "sharp"]) {
  try {
    require(moduleName);
    const packageJson = JSON.parse(
      readFileSync(require.resolve(`${moduleName}/package.json`), "utf8"),
    );
    ok(`${moduleName} ${packageJson.version} charge correctement`);
  } catch (error) {
    fail(
      `${moduleName} ne charge pas avec Node ABI ${process.versions.modules}: ${error.message}`,
    );
  }
}

if (failures.length) {
  console.error(
    "\nRuntime invalide. Lancez INSTALLER-NOUVEAU-PC.bat ou npm rebuild better-sqlite3 sharp.",
  );
  process.exit(1);
}

console.log("Runtime Marvin OK.");
