import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        brand: { DEFAULT: "#000000", foreground: "#ffffff" },
      },
    },
  },
  plugins: [],
} satisfies Config;
