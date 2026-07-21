import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";

const eslintConfig = defineConfig([
  ...nextVitals,
  {
    // Marvin charge volontairement ses données au montage de nombreuses pages. La règle
    // React 19 signale aussi les appels async qui mettent l'état à jour après leur réponse,
    // sans distinguer ce cas légitime d'un setState synchrone en cascade.
    rules: {
      "react-hooks/set-state-in-effect": "off",
      // Ces règles ciblent l'optimisation par le React Compiler. Marvin utilise encore des
      // refs "valeur courante" et des fonctions hissées, valides à l'exécution ; elles
      // seront migrées progressivement sans rendre le lint inutilisable entre-temps.
      "react-hooks/refs": "off",
      "react-hooks/immutability": "off",
      "react-hooks/use-memo": "off",
      "react-hooks/preserve-manual-memoization": "off",
      // Les textes de l'interface sont majoritairement en français et utilisent des
      // apostrophes typographiques directement dans le JSX.
      "react/no-unescaped-entities": "off",
    },
  },
  // Override default ignores of eslint-config-next.
  globalIgnores([
    // Default ignores of eslint-config-next:
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
    // Environnements et données locales pouvant contenir leur propre JavaScript généré.
    "backend/.venv/**",
    "data/**",
    ".tmp.driveupload/**",
    "README/**",
    "README_pages/**",
    "README_images/**",
  ]),
]);

export default eslintConfig;
