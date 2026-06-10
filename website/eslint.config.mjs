// aviato:managed profile=aviato-library version=0 hash=9f45196445178404f9765f213dccf633cf8c00d02d21f653d4c083d793d414c6
import docusaurus from "@docusaurus/eslint-plugin";

export default [
  {
    files: ["**/*.{js,jsx,ts,tsx}"],
    ignores: ["build/**", ".docusaurus/**"],
    plugins: { "@docusaurus": docusaurus },
    rules: {
      ...docusaurus.configs.recommended.rules,
    },
  },
];
