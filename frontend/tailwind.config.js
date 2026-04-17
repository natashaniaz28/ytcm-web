/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      fontFamily: {
        display: ['"DM Serif Display"', 'Georgia', 'serif'],
        mono: ['"JetBrains Mono"', 'monospace'],
        body: ['"DM Sans"', 'sans-serif'],
      },
      colors: {
        ink: {
          950: '#0a0a0f',
          900: '#111118',
          800: '#1a1a26',
          700: '#252535',
          600: '#32324a',
          500: '#4a4a6a',
          400: '#6b6b9a',
          300: '#9595c0',
          200: '#c0c0dc',
          100: '#e8e8f4',
          50:  '#f4f4fa',
        },
        acid: {
          500: '#c8ff00',
          400: '#d4ff33',
          300: '#e0ff66',
        },
        coral: {
          500: '#ff6b6b',
          400: '#ff8585',
        },
        teal: {
          500: '#00d4aa',
          400: '#00e8bc',
        },
      },
      animation: {
        'fade-up': 'fadeUp 0.4s ease forwards',
        'pulse-slow': 'pulse 3s ease-in-out infinite',
        'spin-slow': 'spin 8s linear infinite',
      },
      keyframes: {
        fadeUp: {
          from: { opacity: 0, transform: 'translateY(12px)' },
          to:   { opacity: 1, transform: 'translateY(0)' },
        },
      },
    },
  },
  plugins: [],
}
