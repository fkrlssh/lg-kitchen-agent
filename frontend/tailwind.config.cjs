/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    './src/pages/**/*.{js,ts,jsx,tsx,mdx}',
    './src/components/**/*.{js,ts,jsx,tsx,mdx}',
    './src/app/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: [
          'var(--font-pretendard)',
          'Pretendard',
          '-apple-system',
          'BlinkMacSystemFont',
          'system-ui',
          'Roboto',
          'sans-serif',
        ],
      },
      colors: {
        primary: {
          50: '#fef2f4',
          100: '#fde6ea',
          500: '#a50034',  // LG-ish red accent
          600: '#8a002b',
          700: '#6f0022',
        },
        status: {
          ok: '#10b981',     // emerald-500
          warn: '#f59e0b',   // amber-500
          danger: '#ef4444', // rose-500
        },
      },
      boxShadow: {
        card: '0 1px 3px 0 rgb(0 0 0 / 0.06), 0 1px 2px 0 rgb(0 0 0 / 0.04)',
      },
    },
  },
  plugins: [],
}
