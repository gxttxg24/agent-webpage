/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#17212b",
        panel: "#ffffff",
        line: "#dfe7ef",
        brand: "#2aabee",
        "brand-dark": "#168acd",
        "chat-bg": "#e7eef5"
      },
      boxShadow: {
        soft: "0 12px 32px rgba(23, 33, 43, 0.12)"
      }
    }
  },
  plugins: []
};
