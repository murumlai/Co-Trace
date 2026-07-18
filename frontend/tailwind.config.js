/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        background: '#FAFAFA',
        foreground: '#0F172A',
        muted: '#64748B',
        surface: '#F1F5F9',
        card: '#FFFFFF',
        border: '#E2E8F0',
        accent: '#0052FF',
        'accent-secondary': '#4D7CFF',
        success: '#059669',
        danger: '#DC2626',
        warning: '#D97706',
        ink: '#0F172A',
        placeholder: '#94A3B8',
      },
      fontFamily: {
        display: ['Calistoga', 'Georgia', 'serif'],
        body: ['Inter', 'system-ui', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'monospace'],
      },
      borderRadius: {
        card: '16px',
      },
      boxShadow: {
        soft: '0 1px 3px rgb(15 23 42 / 0.06)',
        lift: '0 10px 24px rgb(15 23 42 / 0.08)',
        'lift-lg': '0 24px 48px rgb(15 23 42 / 0.12)',
        accent: '0 8px 24px rgb(0 82 255 / 0.25)',
      },
      keyframes: {
        float: {
          '0%, 100%': { transform: 'translateY(0)' },
          '50%': { transform: 'translateY(-10px)' },
        },
        pulseDot: {
          '0%, 100%': { transform: 'scale(1)', opacity: '1' },
          '50%': { transform: 'scale(1.35)', opacity: '0.7' },
        },
        rotateSlow: {
          to: { transform: 'rotate(360deg)' },
        },
        fadeUp: {
          from: { opacity: '0', transform: 'translateY(18px)' },
          to: { opacity: '1', transform: 'translateY(0)' },
        },
      },
      animation: {
        float: 'float 5s ease-in-out infinite',
        'pulse-dot': 'pulseDot 2s ease-in-out infinite',
        'rotate-slow': 'rotateSlow 60s linear infinite',
        'fade-up': 'fadeUp 600ms ease-out both',
      },
    },
  },
  plugins: [],
}
