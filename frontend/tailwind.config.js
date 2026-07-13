/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        base: '#E0E5EC',
        ink: '#3D4852',
        muted: '#6B7280',
        accent: '#6C63FF',
        'accent-light': '#8B84FF',
        teal: '#38B2AC',
        danger: '#E05260',
        placeholder: '#A0AEC0',
      },
      fontFamily: {
        display: ['"Plus Jakarta Sans"', 'system-ui', 'sans-serif'],
        body: ['"DM Sans"', 'system-ui', 'sans-serif'],
      },
      borderRadius: {
        card: '32px',
      },
      boxShadow: {
        extruded:
          '9px 9px 16px rgb(163 177 198 / 0.6), -9px -9px 16px rgb(255 255 255 / 0.5)',
        'extruded-hover':
          '12px 12px 20px rgb(163 177 198 / 0.7), -12px -12px 20px rgb(255 255 255 / 0.6)',
        'extruded-sm':
          '5px 5px 10px rgb(163 177 198 / 0.6), -5px -5px 10px rgb(255 255 255 / 0.5)',
        inset:
          'inset 6px 6px 10px rgb(163 177 198 / 0.6), inset -6px -6px 10px rgb(255 255 255 / 0.5)',
        'inset-deep':
          'inset 10px 10px 20px rgb(163 177 198 / 0.7), inset -10px -10px 20px rgb(255 255 255 / 0.6)',
        'inset-sm':
          'inset 3px 3px 6px rgb(163 177 198 / 0.6), inset -3px -3px 6px rgb(255 255 255 / 0.5)',
      },
      keyframes: {
        float: {
          '0%, 100%': { transform: 'translateY(0)' },
          '50%': { transform: 'translateY(-10px)' },
        },
      },
      animation: {
        float: 'float 3s ease-in-out infinite',
      },
    },
  },
  plugins: [],
}
